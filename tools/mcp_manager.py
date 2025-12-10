"""MCP 工具管理器，实现工具注册与生命周期管理。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


logger = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = TOOLS_DIR / "mcp_config.json"
DEFAULT_METADATA_PATH = TOOLS_DIR / "generated_tools.json"


class MCPManagerError(RuntimeError):
    """MCP 管理器顶层异常类型。"""


@dataclass
class MCPToolRecord:
    name: str
    description: str
    input_schema: Dict[str, Any]
    executor: str
    mcp_server: str
    mcp_tool: str


class MCPClientConnection:
    """管理与单个 MCP Server 的持久连接。"""

    def __init__(self, server_name: str, server_cfg: Dict[str, Any]):
        self.server_name = server_name
        self.server_cfg = server_cfg
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.stack: Optional[AsyncExitStack] = None
        self.session: Optional[ClientSession] = None
        self._ready_event = threading.Event()
        self._stop_event: Optional[asyncio.Event] = None
        self._connection_future: Optional[concurrent.futures.Future] = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _connection_main(self) -> None:
        command = self.server_cfg.get("command")
        if not command:
            raise MCPManagerError(f"MCP Server '{self.server_name}' 缺少 command 配置")

        args = self.server_cfg.get("args", [])
        if not isinstance(args, list):
            raise MCPManagerError(f"MCP Server '{self.server_name}' 的 args 必须为数组")

        env = os.environ.copy()
        env.update(self.server_cfg.get("env", {}))

        params = StdioServerParameters(command=command, args=args, env=env)

        self.stack = AsyncExitStack()
        async with self.stack:
            read, write = await self.stack.enter_async_context(stdio_client(params))
            session = await self.stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.session = session
            self._stop_event = asyncio.Event()
            self._ready_event.set()
            logger.info("MCP Server '%s' 已启动", self.server_name)
            await self._stop_event.wait()
        self.session = None
        self._ready_event.clear()
        self._stop_event = None
        logger.info("MCP Server '%s' 会话已结束", self.server_name)

    def start(self) -> None:
        if self._connection_future and not self._connection_future.done():
            return
        self._connection_future = asyncio.run_coroutine_threadsafe(
            self._connection_main(), self.loop
        )
        if not self._ready_event.wait(timeout=10):
            raise MCPManagerError(f"MCP Server '{self.server_name}' 启动超时")

    async def _async_call_tool(self, tool_name: str, arguments: Dict[str, Any]):
        if not self.session:
            raise MCPManagerError(f"MCP Server '{self.server_name}' 尚未启动")
        response = await self.session.call_tool(tool_name, arguments)
        return response

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]):
        future = asyncio.run_coroutine_threadsafe(
            self._async_call_tool(tool_name, arguments), self.loop
        )
        return future.result()

    def close(self) -> None:
        if not self._connection_future:
            return
        def _signal_stop():
            if self._stop_event and not self._stop_event.is_set():
                self._stop_event.set()

        self.loop.call_soon_threadsafe(_signal_stop)

        try:
            self._connection_future.result(timeout=5)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "关闭 MCP Server '%s' 超时，即将强制终止", self.server_name
            )
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                logger.warning(
                    "MCP Server '%s' 所在线程未能正常退出", self.server_name
                )
        self._connection_future = None
        logger.info("MCP Server '%s' 已停止", self.server_name)


class MCPToolManager:
    """负责加载工具描述、启动 MCP Server，并提供同步调用接口。"""

    def __init__(
        self,
        config_path: Path = DEFAULT_CONFIG_PATH,
        metadata_path: Path = DEFAULT_METADATA_PATH,
    ) -> None:
        self.config_path = config_path
        self.metadata_path = metadata_path
        self.server_configs = self._load_server_configs(config_path)
        self.tool_index = self._load_metadata(metadata_path)
        self.connections: Dict[str, MCPClientConnection] = {}

    @staticmethod
    def _load_server_configs(path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise MCPManagerError(f"未找到 MCP 配置文件: {path}")
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        servers = data.get("mcpServers") or {}
        if not isinstance(servers, dict) or not servers:
            raise MCPManagerError("配置文件中缺少 'mcpServers' 定义")
        return servers

    @staticmethod
    def _load_metadata(path: Path) -> Dict[str, MCPToolRecord]:
        if not path.exists():
            raise MCPManagerError(
                f"未找到 MCP 工具描述文件: {path}\n"
                "请先运行 tools/extract_mcp_tools.py 生成"
            )
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        tool_index: Dict[str, MCPToolRecord] = {}
        for tool_name, meta in raw.items():
            if "mcp_server" not in meta:
                raise MCPManagerError(f"工具 '{tool_name}' 缺少 'mcp_server' 字段")
            record = MCPToolRecord(
                name=tool_name,
                description=meta.get("description", ""),
                input_schema=meta.get("input_schema", {}),
                executor=meta.get("executor", "tool"),
                mcp_server=meta["mcp_server"],
                mcp_tool=meta.get("mcp_tool", tool_name),
            )
            tool_index[tool_name] = record
        return tool_index

    def has_tool(self, tool_name: Optional[str]) -> bool:
        return bool(tool_name) and tool_name in self.tool_index

    def prepare_tools(self, tool_names: Iterable[str]) -> None:
        required_servers = {
            self.tool_index[name].mcp_server
            for name in tool_names
            if self.has_tool(name)
        }
        for server in required_servers:
            self._ensure_server(server)

    def _ensure_server(self, server_name: str) -> None:
        if server_name in self.connections:
            return
        server_cfg = self.server_configs.get(server_name)
        if not server_cfg:
            raise MCPManagerError(f"无法找到 MCP Server '{server_name}' 的配置")
        connection = MCPClientConnection(server_name, server_cfg)
        connection.start()
        self.connections[server_name] = connection

    def _simplify_response(self, response) -> Any:
        content = getattr(response, "content", None)
        if not content:
            return getattr(response, "model_dump", lambda: response)()

        simplified: List[Any] = []
        for block in content:
            if hasattr(block, "model_dump"):
                data = block.model_dump()
            elif isinstance(block, dict):
                data = block
            else:
                data = getattr(block, "__dict__", block)
            if isinstance(data, dict) and data.get("type") == "text" and "text" in data:
                simplified.append(data["text"])
            else:
                simplified.append(data)

        if len(simplified) == 1:
            return simplified[0]
        return simplified

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        if tool_name not in self.tool_index:
            raise MCPManagerError(f"未知的 MCP 工具: {tool_name}")
        record = self.tool_index[tool_name]
        self._ensure_server(record.mcp_server)
        connection = self.connections[record.mcp_server]
        response = connection.call_tool(record.mcp_tool, arguments)
        return self._simplify_response(response)

    def create_tool_runner(self, tool_name: str):
        def runner(**kwargs):
            return self.call_tool(tool_name, kwargs)

        return runner

    def shutdown(self) -> None:
        for connection in list(self.connections.values()):
            try:
                connection.close()
            except Exception as exc:
                logger.warning("关闭 MCP Server '%s' 时出错: %s", connection.server_name, exc)
        self.connections.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.shutdown()
