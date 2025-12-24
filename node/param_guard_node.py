import os
from typing import Optional

from langchain_openai import ChatOpenAI

from node.base_node import WorkflowNode, NodeExecutionContext
from node.utils import truncate_output
from src.workflow_types import WorkflowState
from src.param_guard import ParamGuard


GUARD_MAX_OUTPUT_LENGTH = 1000


class ParamGuardNode(WorkflowNode):
    
    def __init__(self, subtask, context: NodeExecutionContext):
        super().__init__(subtask, context)
        
        if subtask.llm_config:
            self.param_guard = ParamGuard(context.tool_schemas)
            self.param_guard.llm = ChatOpenAI(
                api_key=subtask.llm_config.api_key or os.getenv("GUARD_KEY") or os.getenv("PLANNER_KEY"),
                base_url=subtask.llm_config.base_url or os.getenv("GUARD_URL") or os.getenv("PLANNER_URL"),
                model=subtask.llm_config.model or os.getenv("GUARD_MODEL") or os.getenv("PLANNER_MODEL", "gpt-4o"),
                timeout=60,
            )
            self.model_name = subtask.llm_config.model or os.getenv("GUARD_MODEL") or os.getenv("PLANNER_MODEL", "gpt-4o")
        else:
            self.param_guard = context.param_guard
            self.model_name = os.getenv("GUARD_MODEL") or os.getenv("PLANNER_MODEL", "gpt-4o")
        
        payload = subtask.input or {}
        self.target_input_template = payload.get("target_input_template") or {}
        self.schema = payload.get("schema") or self._get_schema_from_tool(
            payload.get("target_tool") or subtask.tool_name
        )
        
        source_nodes = payload.get("source_nodes")
        if source_nodes:
            self.source_node = source_nodes[0] if source_nodes else None
        else:
            self.source_node = payload.get("source_node")
        
        self.target_node = payload.get("target_node")
        self.target_tool = payload.get("target_tool") or subtask.tool_name
    
    def _get_schema_from_tool(self, tool_name: Optional[str]):
        if not tool_name:
            return {}
        return self.param_guard.get_input_schema(tool_name, self.context.mcp_manager)
    
    def execute(self, state: WorkflowState) -> WorkflowState:
        if not self._should_execute(state):
            return state
        
        self.logger.info(f"执行参数整形节点: {self.subtask.id} -> {self.target_node}")
        
        trace_entry = self._create_trace_entry(
            "param_guard",
            target_tool=self.target_tool,
            model=self.model_name
        )
        
        try:
            candidate_input = self.context.resolve_dependencies(
                self.target_input_template,
                state["outputs"]
            )
            upstream_output = state["outputs"].get(self.source_node)
            
            result = self.param_guard.validate_and_repair(
                candidate_input,
                self.schema,
                upstream_output,
                self.target_tool
            )
            
            trace_entry["input"] = {
                "mode": result["mode"],
                "candidate": truncate_output(candidate_input, GUARD_MAX_OUTPUT_LENGTH),
                "upstream_output": truncate_output(upstream_output, GUARD_MAX_OUTPUT_LENGTH),
                "schema": self.schema
            }
            trace_entry["output"] = truncate_output(result["output"], GUARD_MAX_OUTPUT_LENGTH)
            if "raw_response" in result:
                trace_entry["raw_response"] = truncate_output(result["raw_response"], GUARD_MAX_OUTPUT_LENGTH)
            
            state["outputs"][self.subtask.id] = result["output"]
            
            self._finalize_trace(trace_entry, result["output"])
            
        except Exception as e:
            self.logger.error(f"参数整形节点 {self.subtask.id} 执行失败: {e}")
            state["error"] = str(e)
            
            trace_entry["input"] = {
                "candidate": truncate_output(
                    self.context.resolve_dependencies(
                        self.target_input_template,
                        state["outputs"]
                    ),
                    GUARD_MAX_OUTPUT_LENGTH
                ),
                "upstream_output": truncate_output(state["outputs"].get(self.source_node), GUARD_MAX_OUTPUT_LENGTH),
                "schema": self.schema
            }
            
            if hasattr(e, 'guard_metadata') and e.guard_metadata.get('raw_response'):
                trace_entry["raw_response"] = truncate_output(e.guard_metadata['raw_response'], GUARD_MAX_OUTPUT_LENGTH)
                self.logger.info(f"已保存失败的 LLM 原始输出 (长度: {len(e.guard_metadata['raw_response'])})")
            
            self._finalize_trace(trace_entry, None, error=e)
        
        return state
