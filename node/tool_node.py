import json
import os
import re
from typing import Any

from node.base_node import WorkflowNode, NodeExecutionContext
from node.utils import truncate_output, truncate_node_output
from src.workflow_types import WorkflowState


TOOL_MAX_OUTPUT_LENGTH = 10000


def get_tool_output_max_length() -> int:
    """获取工具输出的最大长度限制"""
    max_len = os.getenv("TOOL_OUTPUT_MAX_CHARS")
    if max_len:
        try:
            return int(max_len)
        except ValueError:
            pass
    return 20000  # 默认值


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
            trace_entry["input"] = truncate_output(raw_input, TOOL_MAX_OUTPUT_LENGTH)

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

            trace_entry["input"] = truncate_output(tool_input, TOOL_MAX_OUTPUT_LENGTH)

            result = tool_func(**tool_input)
            result = self._normalize_tool_output(result)
            if self._is_tool_failure_output(result):
                raise RuntimeError(f"工具 {self.subtask.tool_name} 返回失败：{result}")

            # 应用输出截断，防止过长内容传递给下游节点
            truncated_result = truncate_node_output(result, get_tool_output_max_length())

            state["outputs"][self.subtask.id] = truncated_result

            truncated_result_for_display = truncate_output(truncated_result, TOOL_MAX_OUTPUT_LENGTH)

            self._finalize_trace(trace_entry, truncated_result)

            self.logger.info(f"工具节点 {self.subtask.id} 执行成功: {truncated_result_for_display}")

        except Exception as e:
            self.logger.error(f"工具节点 {self.subtask.id} 执行失败: {e}")
            state["error"] = str(e)

            if tool_input is not None:
                trace_entry["input"] = truncate_output(tool_input, TOOL_MAX_OUTPUT_LENGTH)

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

