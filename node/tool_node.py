import json
import re
from typing import Any, Dict, Optional

from node.base_node import WorkflowNode, NodeExecutionContext
from src.workflow_types import WorkflowState


MAX_OUTPUT_LENGTH = 1000
TRUNCATED_SUFFIX = "\n... [输出已截断，原始长度: {original_length} 字符，显示前 {max_length} 字符] ..."


def truncate_output(output: Any, max_length: Optional[int] = MAX_OUTPUT_LENGTH) -> Any:
    """Tool节点的输出截断功能"""
    if not max_length:
        return output
    
    if isinstance(output, str):
        output_str = output
    elif isinstance(output, (dict, list)):
        output_str = json.dumps(output, ensure_ascii=False)
    else:
        output_str = str(output)
    
    if len(output_str) <= max_length:
        return output
    
    original_length = len(output_str)
    truncated_str = output_str[:max_length] + TRUNCATED_SUFFIX.format(
        original_length=original_length,
        max_length=max_length
    )
    
    if isinstance(output, str):
        return truncated_str
    
    return {
        "_truncated": True,
        "_original_type": type(output).__name__,
        "_original_length": original_length,
        "_preview": truncated_str
    }


class ToolNode(WorkflowNode):
    
    def execute(self, state: WorkflowState) -> WorkflowState:
        if not self._should_execute(state):
            return state
        
        self.logger.info(f"执行工具节点: {self.subtask.id} - {self.subtask.name}")
        
        trace_entry = self._create_trace_entry(
            "tool",
            tool_name=self.subtask.tool_name
        )
        
        tool_input = None
        raw_input = self.subtask.input if self.subtask.input else {}
        
        try:
            trace_entry["input"] = truncate_output(raw_input)
            
            tool_func = self._get_tool_function()
            
            if "__from_guard__" in raw_input:
                guard_id = raw_input.get("__from_guard__")
                guard_output = state["outputs"].get(guard_id, {})
                if not isinstance(guard_output, dict):
                    raise ValueError(f"参数校验节点 {guard_id} 输出异常，期望字典")
                tool_input = guard_output
                
                if "_param_overrides" in raw_input:
                    param_overrides = raw_input["_param_overrides"]
                    tool_input = {**tool_input, **param_overrides}
                    self.logger.info(f"工具节点 {self.subtask.id} 应用参数覆盖: {param_overrides}")
                    
            elif "__from_guards__" in raw_input:
                guard_ids = raw_input.get("__from_guards__", [])
                tool_input = {}
                for guard_id in guard_ids:
                    guard_output = state["outputs"].get(guard_id, {})
                    if not isinstance(guard_output, dict):
                        raise ValueError(f"参数校验节点 {guard_id} 输出异常，期望字典")
                    tool_input.update(guard_output)
                self.logger.info(f"工具节点 {self.subtask.id} 从 {len(guard_ids)} 个 guard 节点合并参数")
                
                if "_param_overrides" in raw_input:
                    param_overrides = raw_input["_param_overrides"]
                    tool_input = {**tool_input, **param_overrides}
                    self.logger.info(f"工具节点 {self.subtask.id} 应用参数覆盖: {param_overrides}")
                    
            else:
                raw_input_str = json.dumps(raw_input, ensure_ascii=False)
                if re.search(r"\{ST\d+\.", raw_input_str):
                    self.logger.warning(
                        f"工具节点 {self.subtask.id} 的 input 包含引用语法但未经过 guard 节点处理，"
                        f"这可能是规划器的 bug。正在使用 fallback 逻辑解析。"
                    )
                tool_input = self.context.resolve_dependencies(raw_input, state["outputs"])
            
            trace_entry["input"] = truncate_output(tool_input)
            
            result = tool_func(**tool_input)
            result = self._normalize_tool_output(result)
            if self._is_tool_failure_output(result):
                raise RuntimeError(f"工具 {self.subtask.tool_name} 返回失败：{result}")
            
            state["outputs"][self.subtask.id] = result
            
            truncated_result = truncate_output(result)
            
            self._finalize_trace(trace_entry, result)
            
            self.logger.info(f"工具节点 {self.subtask.id} 执行成功: {truncated_result}")
            
        except Exception as e:
            self.logger.error(f"工具节点 {self.subtask.id} 执行失败: {e}")
            state["error"] = str(e)
            
            if tool_input is not None:
                trace_entry["input"] = truncate_output(tool_input)
            
            self._finalize_trace(trace_entry, None, error=e)
        
        return state
    
    def _get_tool_function(self):
        tool_func = self.context.tools.get(self.subtask.tool_name)
        if (
            not tool_func
            and self.context.mcp_manager
            and self.context.mcp_manager.has_tool(self.subtask.tool_name)
        ):
            tool_func = self.context.mcp_manager.create_tool_runner(self.subtask.tool_name)
            self.context.tools[self.subtask.tool_name] = tool_func
        if not tool_func:
            raise ValueError(f"工具 {self.subtask.tool_name} 未找到")
        return tool_func
    
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
