import json
import os
from typing import Dict, Any

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from node.base_node import WorkflowNode, NodeExecutionContext
from node.utils import truncate_output, INPUT_TRUNCATED_SUFFIX
from src.workflow_types import WorkflowState


LLM_MAX_OUTPUT_LENGTH = 8000


def truncate_input(prompt: str) -> str:
    max_len = os.getenv("LLM_INPUT_MAX_CHARS")
    if not max_len:
        return prompt
    try:
        limit = int(max_len)
    except ValueError:
        return prompt
    if limit <= 0 or len(prompt) <= limit:
        return prompt
    return prompt[:limit] + INPUT_TRUNCATED_SUFFIX


class LLMNode(WorkflowNode):
    
    def __init__(self, subtask, context: NodeExecutionContext):
        super().__init__(subtask, context)
        
        if subtask.llm_config:
            self.llm = ChatOpenAI(
                api_key=subtask.llm_config.api_key or os.getenv("PLANNER_KEY"),
                base_url=subtask.llm_config.base_url or os.getenv("PLANNER_URL"),
                model=subtask.llm_config.model or os.getenv("PLANNER_MODEL", "gpt-4o"),
                timeout=60,
            )
            self.model_name = subtask.llm_config.model or os.getenv("PLANNER_MODEL", "gpt-4o")
        else:
            self.llm = context.llm
            self.model_name = os.getenv("PLANNER_MODEL", "gpt-4o")
    
    def execute(self, state: WorkflowState) -> WorkflowState:
        if not self._should_execute(state):
            return state
        
        self.logger.info(f"执行LLM节点: {self.subtask.id} - {self.subtask.name} (模型: {self.model_name})")
        
        trace_entry = self._create_trace_entry("llm", model=self.model_name)
        prompt_str = None
        
        try:
            raw_input = self.subtask.input if self.subtask.input else {}
            
            trace_entry["input"] = {"prompt": truncate_output(raw_input, LLM_MAX_OUTPUT_LENGTH)}
            
            resolved_input = self.context.resolve_dependencies(raw_input, state["outputs"])
            
            prompt_str = self._extract_prompt(resolved_input)
            prompt_str = truncate_input(prompt_str)
            
            trace_entry["input"] = {"prompt": truncate_output(prompt_str, LLM_MAX_OUTPUT_LENGTH)}
            
            messages = [HumanMessage(content=prompt_str)]
            response = self.llm.invoke(messages)
            result = self._strip_think_tags(response.content)
            
            state["outputs"][self.subtask.id] = result
            
            self._finalize_trace(trace_entry, result)
            
            self.logger.info(f"LLM节点 {self.subtask.id} 执行成功")
            
        except Exception as e:
            self.logger.error(f"LLM节点 {self.subtask.id} 执行失败: {e}")
            state["error"] = str(e)
            
            if prompt_str is not None:
                trace_entry["input"] = {"prompt": truncate_output(prompt_str, LLM_MAX_OUTPUT_LENGTH)}
            
            self._finalize_trace(trace_entry, None, error=e)
        
        return state
    
    def _extract_prompt(self, resolved_input: Dict[str, Any]) -> str:
        if "prompt" in resolved_input:
            return str(resolved_input["prompt"])
        elif "content" in resolved_input:
            return str(resolved_input["content"])
        else:
            return json.dumps(resolved_input, ensure_ascii=False)
