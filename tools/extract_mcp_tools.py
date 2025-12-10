"""从 mcp_config.json 自动提取 MCP 工具元信息。

该脚本会遍历配置中的所有 MCP Server，逐一启动并调用
`list_tools` 接口，然后将得到的工具信息转换成类似 tools.json
的结构：

{
    "server.tool_name": {
        "description": "...",
        "input_schema": {...},
        "executor": "tool"
    }
}

默认输出文件名为 `generated_tools.json`，可通过命令行参数修改。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = TOOLS_DIR / "mcp_config.json"
DEFAULT_OUTPUT = TOOLS_DIR / "generated_tools.json"


class ToolExtractionError(RuntimeError):
    """脚本运行时的异常类型，便于外部捕获。"""


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ToolExtractionError(f"配置文件不存在: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        raise ToolExtractionError(f"解析配置失败: {exc}") from exc

    servers = config.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        raise ToolExtractionError("配置文件中缺少有效的 'mcpServers' 定义")

    return servers


async def list_server_tools(server_name: str, server_cfg: Dict[str, Any]) -> Dict[str, Any]:
    command = server_cfg.get("command")
    if not command:
        raise ToolExtractionError(f"Server '{server_name}' 缺少 command 配置")

    args = server_cfg.get("args", [])
    if not isinstance(args, list):
        raise ToolExtractionError(f"Server '{server_name}' 的 args 必须为数组")

    env = os.environ.copy()
    env.update(server_cfg.get("env", {}))

    params = StdioServerParameters(command=command, args=args, env=env)

    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        result = await session.list_tools()

    tools_data: Dict[str, Any] = {}
    for tool in result.tools:
        key = tool.name
        tools_data[key] = {
            "description": tool.description or "",
            "input_schema": tool.inputSchema or {},
            "executor": "tool",
            "mcp_server": server_name,
            "mcp_tool": tool.name,
        }

    return tools_data


async def extract_tools(config_path: Path, output_path: Path) -> Dict[str, Any]:
    servers = load_config(config_path)
    aggregated: Dict[str, Any] = {}

    for server_name, server_cfg in servers.items():
        try:
            tools = await list_server_tools(server_name, server_cfg)
        except Exception as exc:
            raise ToolExtractionError(
                f"连接 MCP Server '{server_name}' 失败: {exc}"
            ) from exc
        
        duplicated_keys = set(aggregated).intersection(tools)
        if duplicated_keys:
            raise ToolExtractionError(
                "发现重复的工具键: " + ", ".join(sorted(duplicated_keys))
            )
        aggregated.update(tools)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(aggregated, f, indent=2, ensure_ascii=False)

    return aggregated


def refresh_tool_metadata(
    config_path: Path = DEFAULT_CONFIG,
    output_path: Path = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    """便利函数：同步方式刷新 MCP 工具元信息。"""

    return asyncio.run(extract_tools(config_path, output_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="提取 MCP 工具并生成 JSON 文件")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"配置文件路径 (默认: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"输出文件路径 (默认: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        aggregated = refresh_tool_metadata(args.config, args.output)
    except ToolExtractionError as exc:
        raise SystemExit(f"❌ 提取失败: {exc}") from exc
    except Exception as exc:  # 捕获底层运行时错误
        raise SystemExit(f"❌ 运行失败: {exc}") from exc

    print(f"✅ 共写入 {len(aggregated)} 个工具定义 -> {args.output}")


if __name__ == "__main__":
    main()
