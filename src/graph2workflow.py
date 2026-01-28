from __future__ import annotations

import logging
import os
import re
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from datetime import datetime

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

from tools.mcp_manager import MCPToolManager
from src.param_guard import ParamGuard
from src.workflow_types import WorkflowState
from src.config import get_config
from node import NodeFactory, NodeExecutionContext

# 假设这些类定义在 src.subtask_planner 中，这里为了独立运行保留引用
# from src.subtask_planner import WorkflowIR, Subtask

logger = logging.getLogger(__name__)

class Graph2Workflow:
    def __init__(
        self,
        workflow_ir,
        tools: Dict[str, Any],
        mcp_manager: Optional[MCPToolManager] = None,
    ):
        self.config = get_config()
        self.workflow_ir = workflow_ir
        self.tools = tools
        self.llm = ChatOpenAI(
            api_key=self.config.planner_key,
            base_url=self.config.planner_url,
            model=self.config.planner_model,
            timeout=self.config.planner_timeout,
        )
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.execution_trace = []
        self.mcp_manager = mcp_manager
        self.failed_nodes: List[Dict[str, Any]] = []
        self.node_dependencies: Dict[str, Set[str]] = {}
        self.completed_nodes: Set[str] = set()
        self.tool_schemas: Dict[str, Any] = self._load_tool_schemas()
        self.param_guard = ParamGuard(self.tool_schemas)
        
        self.context = NodeExecutionContext(
            tools=self.tools,
            llm=self.llm,
            logger=self.logger,
            execution_trace=self.execution_trace,
            completed_nodes=self.completed_nodes,
            node_dependencies=self.node_dependencies,
            mcp_manager=self.mcp_manager,
            tool_schemas=self.tool_schemas,
            param_guard=self.param_guard,
            resolve_dependencies=self._resolve_dependencies,
        )

    def _load_tool_schemas(self) -> Dict[str, Any]:
        meta_path = self.config.tools_generated_path
        if not meta_path.exists():
            self.logger.warning("工具元数据文件不存在: %s", meta_path)
            return {}
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            self.logger.error("加载工具元数据失败: %s", e, exc_info=True)
            return {}

    def _resolve_dependencies(self, input_data: Dict[str, Any], outputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        递归解析输入参数中的占位符 {STx.output}。
        如果参数值是字符串，尝试查找并替换占位符。
        """
        if input_data is None:
            return {}

        pattern = re.compile(r"\{([a-zA-Z0-9_]+)\.output([^}]*)\}")

        def _resolve_value(val: Any):
            if isinstance(val, str):
                def replace_match(match):
                    node_id = match.group(1)
                    path_expr = match.group(2) or ""
                    ref_val = outputs.get(node_id)

                    if ref_val is None:
                        return f"{{Missing Output: {node_id}}}"

                    try:
                        resolved = self._resolve_output_path(ref_val, path_expr)
                    except Exception:
                        return f"{{Invalid Output Path: {node_id}{path_expr}}}"

                    if isinstance(resolved, (dict, list)):
                        return json.dumps(resolved, ensure_ascii=False)
                    return str(resolved)

                return re.sub(pattern, replace_match, val)
            if isinstance(val, dict):
                return {k: _resolve_value(v) for k, v in val.items()}
            if isinstance(val, list):
                return [_resolve_value(item) for item in val]
            return val

        if isinstance(input_data, dict):
            return {k: _resolve_value(v) for k, v in input_data.items()}
        return {}

    def _resolve_output_path(self, value: Any, path_expr: str) -> Any:
        expr = path_expr.strip()
        idx = 0
        while idx < len(expr):
            if expr[idx] == '.':
                idx += 1
                start = idx
                while idx < len(expr) and (expr[idx].isalnum() or expr[idx] == '_'):
                    idx += 1
                key = expr[start:idx]
                if not key:
                    raise ValueError("空的字段名")
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    value = getattr(value, key, None)
            elif expr[idx] == '[':
                idx += 1
                start = idx
                while idx < len(expr) and expr[idx].isdigit():
                    idx += 1
                index_str = expr[start:idx]
                if idx >= len(expr) or expr[idx] != ']':
                    raise ValueError("索引缺少关闭符号")
                idx += 1
                if not index_str:
                    raise ValueError("索引不能为空")
                index = int(index_str)
                if isinstance(value, (list, tuple)):
                    try:
                        value = value[index]
                    except IndexError:
                        raise ValueError("索引超出范围")
                else:
                    raise ValueError("当前值不支持索引访问")
            else:
                break
        return value

    def _dependencies_ready(self, node_id: str, state: WorkflowState) -> bool:
        dependencies = self.node_dependencies.get(node_id)
        if not dependencies:
            return True
        outputs = state.get("outputs") or {}
        return all(dep in outputs for dep in dependencies)

    def build_graph(self) -> StateGraph:
        workflow = StateGraph(WorkflowState)

        node_ids = {node.id for node in self.workflow_ir.nodes}
        self.node_dependencies = {node_id: set() for node_id in node_ids}
        for edge in self.workflow_ir.edges:
            if edge.source in node_ids and edge.target in self.node_dependencies:
                self.node_dependencies[edge.target].add(edge.source)

        node_map = {}
        for subtask in self.workflow_ir.nodes:
            node = NodeFactory.create(subtask, self.context)
            workflow.add_node(subtask.id, node.execute)
            node_map[subtask.id] = subtask

        start_nodes = [n for n in self.workflow_ir.nodes if not n.source or n.source == "null"]
        
        if len(start_nodes) > 1:
            self.logger.info(f"检测到 {len(start_nodes)} 个起点，创建虚拟 START 节点")
            
            def start_node_func(state: WorkflowState) -> WorkflowState:
                self.logger.info("虚拟 START 节点：开始执行工作流")
                return state
            
            workflow.add_node("__START__", start_node_func)
            workflow.set_entry_point("__START__")
            
            for start_node in start_nodes:
                workflow.add_edge("__START__", start_node.id)
                self.logger.info(f"添加边: __START__ -> {start_node.id}")
        elif start_nodes:
            workflow.set_entry_point(start_nodes[0].id)
        else:
            self.logger.warning("未找到起点节点")

        # 统计每个节点的入边数量
        incoming_edges = {}
        for edge in self.workflow_ir.edges:
            if edge.target not in incoming_edges:
                incoming_edges[edge.target] = []
            incoming_edges[edge.target].append(edge.source)

        # 为有多个入边的节点使用列表形式的 add_edge
        processed_targets = set()
        for target_node_id, sources in incoming_edges.items():
            if len(sources) > 1:
                # 使用列表形式的 add_edge，LangGraph 会等待所有源节点完成
                workflow.add_edge(sources, target_node_id)
                self.logger.info(f"添加多源边: {sources} -> {target_node_id}")
                processed_targets.add(target_node_id)

        # 为单入边节点添加边
        for edge in self.workflow_ir.edges:
            if edge.source in node_map and edge.target in node_map:
                if edge.target not in processed_targets:
                    workflow.add_edge(edge.source, edge.target)

        end_nodes = [n for n in self.workflow_ir.nodes if not n.target or n.target == "null"]
        for node in end_nodes:
            workflow.add_edge(node.id, END)

        self.logger.info("LangGraph 工作流构建完成")
        return workflow

    def execute(self) -> Dict[str, Any]:
        self.execution_trace.clear()  # 清空而非重新赋值
        self.completed_nodes.clear()
        if self.mcp_manager:
            tool_names = [
                node.tool_name
                for node in self.workflow_ir.nodes
                if node.executor == "tool" and node.tool_name and self.mcp_manager.has_tool(node.tool_name)
            ]
            self.mcp_manager.prepare_tools(tool_names)
        graph = self.build_graph()
        app = graph.compile()

        initial_state: WorkflowState = {
            "messages": [],
            "current_task": [],  # 改为空列表
            "outputs": {},
            "error": None,
        }

        self.logger.info("开始执行工作流")
        try:
            final_state = app.invoke(initial_state)
            self.logger.info("工作流执行完成")
            return final_state
        except Exception as e:
            self.logger.exception("工作流执行过程中发生未捕获异常")
            return {"error": str(e), "outputs": {}}
        finally:
            self.failed_nodes = [
                trace
                for trace in self.execution_trace
                if trace.get("status") == "failed"
            ]

    def get_execution_trace(self) -> List[Dict[str, Any]]:
        return self.execution_trace

    def get_failed_nodes(self) -> List[Dict[str, Any]]:
        return self.failed_nodes
