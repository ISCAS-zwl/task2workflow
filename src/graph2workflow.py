from __future__ import annotations

import logging
import os
import re
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict, Annotated, Set
from datetime import datetime

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from tools.mcp_manager import MCPToolManager
from src.param_guard import ParamGuard

# 假设这些类定义在 src.subtask_planner 中，这里为了独立运行保留引用
# from src.subtask_planner import WorkflowIR, Subtask

# ============================================================
# 配置参数：输出截断控制
# ============================================================
# 节点输入/输出的最大长度（字符数），超过此长度将被截断
# 
# 影响范围:
#   - trace_entry["input"]  : 工具节点、LLM 节点、GUARD 节点的输入参数
#   - trace_entry["output"] : 所有节点的输出结果
#   - workflow.json         : 执行追踪文件
#   - WebSocket 推送        : 前端实时显示
#   - 日志输出              : 控制台日志
# 
# 不影响范围:
#   - state["outputs"]      : 节点间数据传递（始终保持完整）
#   - 工具实际执行          : 工具函数收到完整参数
#   - LLM 实际执行          : LLM 收到完整 prompt
# 
# 配置说明:
#   - 设为 None 或 0 表示不截断
#   - 建议值: 10000 (10KB), 50000 (50KB), 100000 (100KB)
#   - 当前值: 1000 (1KB，适合调试)
MAX_OUTPUT_LENGTH = 1000

# 截断提示信息模板
TRUNCATED_SUFFIX = "\n... [输出已截断，原始长度: {original_length} 字符，显示前 {max_length} 字符] ..."
# ============================================================

logger = logging.getLogger(__name__)

def truncate_output(output: Any, max_length: Optional[int] = MAX_OUTPUT_LENGTH) -> Any:
    """
    截断输出内容，防止过大的输出影响性能
    
    Args:
        output: 原始输出（任意类型）
        max_length: 最大长度，None 或 0 表示不截断
    
    Returns:
        截断后的输出（保持原始类型或转为字符串）
    """
    if not max_length:
        return output
    
    # 转换为字符串以计算长度
    if isinstance(output, str):
        output_str = output
    elif isinstance(output, (dict, list)):
        output_str = json.dumps(output, ensure_ascii=False)
    else:
        output_str = str(output)
    
    # 如果未超长，返回原始输出
    if len(output_str) <= max_length:
        return output
    
    # 截断并添加提示
    original_length = len(output_str)
    truncated_str = output_str[:max_length] + TRUNCATED_SUFFIX.format(
        original_length=original_length,
        max_length=max_length
    )
    
    # 如果原始输出是字符串，返回截断后的字符串
    if isinstance(output, str):
        return truncated_str
    
    # 否则返回包含截断信息的字典
    return {
        "_truncated": True,
        "_original_type": type(output).__name__,
        "_original_length": original_length,
        "_preview": truncated_str
    }

def merge_current_tasks(existing: Optional[List[str]], new: List[str]) -> List[str]:
    """合并当前任务列表"""
    if existing is None:
        return new
    return existing + new

def merge_outputs(existing: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
    """合并输出字典，支持并发更新"""
    if existing is None:
        return new
    return {**existing, **new}

def merge_errors(existing: Optional[str], new: str) -> str:
    """合并错误信息，支持并发更新"""
    if existing is None:
        return new
    return f"{existing}; {new}"

class WorkflowState(TypedDict):
    messages: Annotated[List[Any], add_messages]
    current_task: Annotated[List[str], merge_current_tasks]
    outputs: Annotated[Dict[str, Any], merge_outputs]
    error: Annotated[Optional[str], merge_errors]

class Graph2Workflow:
    def __init__(
        self,
        workflow_ir,
        tools: Dict[str, Any],
        mcp_manager: Optional[MCPToolManager] = None,
    ):
        self.workflow_ir = workflow_ir
        self.tools = tools
        self.llm = ChatOpenAI(
            api_key=os.getenv("PLANNER_KEY"),
            base_url=os.getenv("PLANNER_URL"),
            model=os.getenv("PLANNER_MODEL", "gpt-4o"),
            timeout=60,
        )
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.execution_trace = []
        self.mcp_manager = mcp_manager
        self.failed_nodes: List[Dict[str, Any]] = []
        self.node_dependencies: Dict[str, Set[str]] = {}
        self.completed_nodes: Set[str] = set()
        self.tool_schemas: Dict[str, Any] = self._load_tool_schemas()
        self.param_guard = ParamGuard(self.tool_schemas)

    def _load_tool_schemas(self) -> Dict[str, Any]:
        """
        加载生成的工具元数据，供参数校验节点复用。
        """
        meta_path = Path(__file__).parent.parent / "tools" / "generated_tools.json"
        if not meta_path.exists():
            return {}
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
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

    def _should_execute_node(self, node_id: str, state: WorkflowState) -> bool:
        if node_id in self.completed_nodes:
            return False
        return self._dependencies_ready(node_id, state)

    def _mark_node_completed(self, node_id: str) -> None:
        self.completed_nodes.add(node_id)

    @staticmethod
    def _strip_think_tags(value: Any) -> Any:
        if isinstance(value, str):
            cleaned = re.sub(r"<think>.*?</think>", "", value, flags=re.DOTALL)
            return cleaned.strip()
        return value


    def _create_tool_node(self, subtask):
        def tool_node(state: WorkflowState) -> WorkflowState:
            if not self._should_execute_node(subtask.id, state):
                return state
            start_time = datetime.now()
            self.logger.info(f"执行工具节点: {subtask.id} - {subtask.name}")
            
            trace_entry = {
                "node_id": subtask.id,
                "node_name": subtask.name,
                "node_type": "tool",
                "tool_name": subtask.tool_name,
                "start_time": start_time.isoformat(),
                "status": "running"
            }
            
            tool_input = None
            raw_input = subtask.input if subtask.input else {}
            
            try:
                # 提前记录规划参数（失败时的 fallback）
                trace_entry["input"] = truncate_output(raw_input)
                tool_func = self.tools.get(subtask.tool_name)
                if (
                    not tool_func
                    and self.mcp_manager
                    and self.mcp_manager.has_tool(subtask.tool_name)
                ):
                    tool_func = self.mcp_manager.create_tool_runner(subtask.tool_name)
                    self.tools[subtask.tool_name] = tool_func
                if not tool_func:
                    raise ValueError(f"工具 {subtask.tool_name} 未找到")

                if "__from_guard__" in raw_input:
                    # 单个 guard 节点
                    guard_id = raw_input.get("__from_guard__")
                    guard_output = state["outputs"].get(guard_id, {})
                    if not isinstance(guard_output, dict):
                        raise ValueError(f"参数校验节点 {guard_id} 输出异常，期望字典")
                    tool_input = guard_output
                    
                    # 应用参数覆盖（如果有）
                    if "_param_overrides" in raw_input:
                        param_overrides = raw_input["_param_overrides"]
                        tool_input = {**tool_input, **param_overrides}
                        self.logger.info(f"工具节点 {subtask.id} 应用参数覆盖: {param_overrides}")
                        
                elif "__from_guards__" in raw_input:
                    # 多个 guard 节点：合并所有 guard 的输出
                    guard_ids = raw_input.get("__from_guards__", [])
                    tool_input = {}
                    for guard_id in guard_ids:
                        guard_output = state["outputs"].get(guard_id, {})
                        if not isinstance(guard_output, dict):
                            raise ValueError(f"参数校验节点 {guard_id} 输出异常，期望字典")
                        # 合并字典，后面的 guard 会覆盖前面的同名键
                        tool_input.update(guard_output)
                    self.logger.info(f"工具节点 {subtask.id} 从 {len(guard_ids)} 个 guard 节点合并参数")
                    
                    # 应用参数覆盖（如果有）
                    if "_param_overrides" in raw_input:
                        param_overrides = raw_input["_param_overrides"]
                        tool_input = {**tool_input, **param_overrides}
                        self.logger.info(f"工具节点 {subtask.id} 应用参数覆盖: {param_overrides}")
                        
                else:
                    # 检查是否包含引用语法（理论上不应该出现，因为 guard 节点会处理）
                    raw_input_str = json.dumps(raw_input, ensure_ascii=False)
                    if re.search(r"\{ST\d+\.", raw_input_str):
                        self.logger.warning(
                            f"工具节点 {subtask.id} 的 input 包含引用语法但未经过 guard 节点处理，"
                            f"这可能是规划器的 bug。正在使用 fallback 逻辑解析。"
                        )
                    tool_input = self._resolve_dependencies(raw_input, state["outputs"])

                # 更新为实际解析后的参数
                trace_entry["input"] = truncate_output(tool_input)

                # 执行工具，将字典解包为关键字参数
                # result = tool_func(**tool_input)
                # if self._is_tool_failure_output(result):
                #     raise RuntimeError(f"工具 {subtask.tool_name} 返回失败：{result}")

                result = tool_func(**tool_input)
                result = self._normalize_tool_output(result)
                if self._is_tool_failure_output(result):
                    raise RuntimeError(f"工具 {subtask.tool_name} 返回失败：{result}")
                
                # 保存原始输出到 state (用于下游节点引用)
                state["outputs"][subtask.id] = result
                
                # 截断输出用于 trace 和日志
                truncated_result = truncate_output(result)
                
                end_time = datetime.now()
                trace_entry["output"] = truncated_result
                trace_entry["status"] = "success"
                trace_entry["end_time"] = end_time.isoformat()
                trace_entry["duration_ms"] = (end_time - start_time).total_seconds() * 1000
                self.logger.info(f"工具节点 {subtask.id} 执行成功: {truncated_result}")
                
            except Exception as e:
                end_time = datetime.now()
                self.logger.error(f"工具节点 {subtask.id} 执行失败: {e}")
                state["error"] = str(e)
                trace_entry["status"] = "failed"
                trace_entry["error"] = str(e)
                trace_entry["end_time"] = end_time.isoformat()
                trace_entry["duration_ms"] = (end_time - start_time).total_seconds() * 1000
                
                # 如果成功解析了参数，确保使用实际参数而非规划参数
                if tool_input is not None:
                    trace_entry["input"] = truncate_output(tool_input)

            self.execution_trace.append(trace_entry)
            self._mark_node_completed(subtask.id)
            return state

        return tool_node

    @staticmethod
    def _is_tool_failure_output(result: Any) -> bool:
        if isinstance(result, str):
            lowered = result.lower()
            if "获取网页内容失败" in result:
                return True
            if lowered.startswith("error") or "failed" in lowered:
                return True
        if isinstance(result, dict) and "error" in result:
            return True
        return False

    @staticmethod
    def _normalize_tool_output(result: Any) -> Any:
        if isinstance(result, str):
            stripped = result.strip()
            if stripped:
                try:
                    return json.loads(stripped)
                except (json.JSONDecodeError, TypeError):
                    return result
        return result

    def _create_llm_node(self, subtask):
        # 配置 LLM
        if subtask.llm_config:
            node_llm = ChatOpenAI(
                api_key=subtask.llm_config.api_key or os.getenv("PLANNER_KEY"),
                base_url=subtask.llm_config.base_url or os.getenv("PLANNER_URL"),
                model=subtask.llm_config.model or os.getenv("PLANNER_MODEL", "gpt-4o"),
            )
            model_info = subtask.llm_config.model or os.getenv("PLANNER_MODEL", "gpt-4o")
        else:
            node_llm = self.llm
            model_info = os.getenv("PLANNER_MODEL", "gpt-4o")
        
        def llm_node(state: WorkflowState) -> WorkflowState:
            if not self._should_execute_node(subtask.id, state):
                return state
            start_time = datetime.now()
            self.logger.info(f"执行LLM节点: {subtask.id} - {subtask.name} (模型: {model_info})")
            
            trace_entry = {
                "node_id": subtask.id,
                "node_name": subtask.name,
                "node_type": "llm",
                "model": model_info,
                "start_time": start_time.isoformat(),
                "status": "running"
            }
            
            prompt_str = None
            
            try:
                # --- 修改点：解析输入依赖并提取 Prompt ---
                raw_input = subtask.input if subtask.input else {}
                
                # 提前记录规划参数（失败时的 fallback）
                trace_entry["input"] = {"prompt": truncate_output(raw_input)}
                
                resolved_input = self._resolve_dependencies(raw_input, state["outputs"])
                
                # 确定最终发送给 LLM 的字符串 Prompt
                # 策略：优先查找 'prompt' 或 'content' 字段，否则将整个字典转为 JSON 字符串
                if "prompt" in resolved_input:
                    prompt_str = str(resolved_input["prompt"])
                elif "content" in resolved_input:
                    prompt_str = str(resolved_input["content"])
                else:
                    # 如果没有特定字段，直接 dump 整个输入作为上下文
                    prompt_str = json.dumps(resolved_input, ensure_ascii=False)
                # -------------------------------------

                # 更新为实际解析后的 prompt
                trace_entry["input"] = {"prompt": truncate_output(prompt_str)}
                
                messages = [HumanMessage(content=prompt_str)]
                response = node_llm.invoke(messages)
                result = self._strip_think_tags(response.content)
                
                # 保存原始输出到 state
                state["outputs"][subtask.id] = result
                
                # 截断输出用于 trace
                truncated_result = truncate_output(result)
                
                end_time = datetime.now()
                trace_entry["output"] = truncated_result
                trace_entry["status"] = "success"
                trace_entry["end_time"] = end_time.isoformat()
                trace_entry["duration_ms"] = (end_time - start_time).total_seconds() * 1000
                self.logger.info(f"LLM节点 {subtask.id} 执行成功")
                
            except Exception as e:
                end_time = datetime.now()
                self.logger.error(f"LLM节点 {subtask.id} 执行失败: {e}")
                state["error"] = str(e)
                trace_entry["status"] = "failed"
                trace_entry["error"] = str(e)
                trace_entry["end_time"] = end_time.isoformat()
                trace_entry["duration_ms"] = (end_time - start_time).total_seconds() * 1000
                
                # 如果成功解析了 prompt，确保使用实际 prompt 而非规划参数
                if prompt_str is not None:
                    trace_entry["input"] = {"prompt": truncate_output(prompt_str)}
            
            self.execution_trace.append(trace_entry)
            self._mark_node_completed(subtask.id)
            return state

        return llm_node

    def _create_param_guard_node(self, subtask):
        payload = subtask.input or {}
        target_input_template = payload.get("target_input_template") or {}
        schema = payload.get("schema") or self.param_guard.get_input_schema(subtask.tool_name, self.mcp_manager)
        
        # 兼容新旧两种格式
        source_nodes = payload.get("source_nodes")  # 新格式：多个上游节点
        if source_nodes:
            source_node = source_nodes[0] if source_nodes else None  # 取第一个作为主要来源
        else:
            source_node = payload.get("source_node")  # 旧格式：单个上游节点
        
        target_node = payload.get("target_node")
        target_tool = payload.get("target_tool") or subtask.tool_name
        
        if subtask.llm_config:
            from src.param_guard import ParamGuard
            param_guard_instance = ParamGuard(self.tool_schemas)
            param_guard_instance.llm = ChatOpenAI(
                api_key=subtask.llm_config.api_key or os.getenv("GUARD_KEY") or os.getenv("PLANNER_KEY"),
                base_url=subtask.llm_config.base_url or os.getenv("GUARD_URL") or os.getenv("PLANNER_URL"),
                model=subtask.llm_config.model or os.getenv("GUARD_MODEL") or os.getenv("PLANNER_MODEL", "gpt-4o"),
                timeout=60,
            )
            model_info = subtask.llm_config.model or os.getenv("GUARD_MODEL") or os.getenv("PLANNER_MODEL", "gpt-4o")
        else:
            param_guard_instance = self.param_guard
            model_info = os.getenv("GUARD_MODEL") or os.getenv("PLANNER_MODEL", "gpt-4o")

        def guard_node(state: WorkflowState) -> WorkflowState:
            if not self._should_execute_node(subtask.id, state):
                return state
            start_time = datetime.now()
            self.logger.info(f"执行参数整形节点: {subtask.id} -> {target_node}")

            trace_entry = {
                "node_id": subtask.id,
                "node_name": subtask.name,
                "node_type": "param_guard",
                "target_tool": target_tool,
                "model": model_info,
                "start_time": start_time.isoformat(),
                "status": "running",
            }

            try:
                candidate_input = self._resolve_dependencies(target_input_template, state["outputs"])
                upstream_output = state["outputs"].get(source_node)

                result = param_guard_instance.validate_and_repair(
                    candidate_input, schema, upstream_output, target_tool
                )

                # 截断大型输入数据用于 trace
                trace_entry["input"] = {
                    "mode": result["mode"], 
                    "candidate": truncate_output(candidate_input),
                    "upstream_output": truncate_output(upstream_output),
                    "schema": schema  # schema 通常不大，不截断
                }
                trace_entry["output"] = truncate_output(result["output"])
                if "raw_response" in result:
                    trace_entry["raw_response"] = truncate_output(result["raw_response"])
                trace_entry["status"] = "success"
                end_time = datetime.now()
                trace_entry["end_time"] = end_time.isoformat()
                trace_entry["duration_ms"] = (end_time - start_time).total_seconds() * 1000

                state["outputs"][subtask.id] = result["output"]
            except Exception as e:
                end_time = datetime.now()
                self.logger.error(f"参数整形节点 {subtask.id} 执行失败: {e}")
                state["error"] = str(e)
                trace_entry["status"] = "failed"
                trace_entry["error"] = str(e)
                trace_entry["input"] = {
                    "candidate": truncate_output(self._resolve_dependencies(target_input_template, state["outputs"])),
                    "upstream_output": truncate_output(state["outputs"].get(source_node)),
                    "schema": schema
                }
                
                # 提取 LLM 原始响应（如果有）
                if hasattr(e, 'guard_metadata') and e.guard_metadata.get('raw_response'):
                    trace_entry["raw_response"] = truncate_output(e.guard_metadata['raw_response'])
                    self.logger.info(f"已保存失败的 LLM 原始输出 (长度: {len(e.guard_metadata['raw_response'])})")
                
                trace_entry["end_time"] = end_time.isoformat()
                trace_entry["duration_ms"] = (end_time - start_time).total_seconds() * 1000

            self.execution_trace.append(trace_entry)
            self._mark_node_completed(subtask.id)
            return state

        return guard_node

    def build_graph(self) -> StateGraph:
        workflow = StateGraph(WorkflowState)

        node_ids = {node.id for node in self.workflow_ir.nodes}
        self.node_dependencies = {node_id: set() for node_id in node_ids}
        for edge in self.workflow_ir.edges:
            if edge.source in node_ids and edge.target in self.node_dependencies:
                self.node_dependencies[edge.target].add(edge.source)

        node_map = {}
        for node in self.workflow_ir.nodes:
            if node.executor == "tool":
                node_func = self._create_tool_node(node)
            elif node.executor == "param_guard":
                node_func = self._create_param_guard_node(node)
            else:
                node_func = self._create_llm_node(node)
            
            workflow.add_node(node.id, node_func)
            node_map[node.id] = node

        # 设置入口节点（没有 source 的节点）
        start_nodes = [n for n in self.workflow_ir.nodes if not n.source or n.source == "null"]
        
        if len(start_nodes) > 1:
            # 多起点：创建虚拟 START 节点
            self.logger.info(f"检测到 {len(start_nodes)} 个起点，创建虚拟 START 节点")
            
            def start_node_func(state: WorkflowState) -> WorkflowState:
                self.logger.info("虚拟 START 节点：开始执行工作流")
                return state
            
            workflow.add_node("__START__", start_node_func)
            workflow.set_entry_point("__START__")
            
            # 从 START 连接到所有真实起点
            for start_node in start_nodes:
                workflow.add_edge("__START__", start_node.id)
                self.logger.info(f"添加边: __START__ -> {start_node.id}")
        elif start_nodes:
            # 单起点：直接设置
            workflow.set_entry_point(start_nodes[0].id)
        else:
            self.logger.warning("未找到起点节点")

        # 添加边
        for edge in self.workflow_ir.edges:
            if edge.source in node_map and edge.target in node_map:
                workflow.add_edge(edge.source, edge.target)

        # 设置结束节点（没有 target 的节点）
        end_nodes = [n for n in self.workflow_ir.nodes if not n.target or n.target == "null"]
        for node in end_nodes:
            workflow.add_edge(node.id, END)

        self.logger.info("LangGraph 工作流构建完成")
        return workflow

    def execute(self) -> Dict[str, Any]:
        self.execution_trace = []
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
