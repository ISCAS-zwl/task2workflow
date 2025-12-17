import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional, Set

from src.workflow_types import WorkflowState


class NodeExecutionContext:
    def __init__(
        self,
        tools: Dict[str, Any],
        llm: Any,
        logger: logging.Logger,
        execution_trace: list,
        completed_nodes: Set[str],
        node_dependencies: Dict[str, Set[str]],
        mcp_manager: Optional[Any] = None,
        tool_schemas: Optional[Dict[str, Any]] = None,
        param_guard: Optional[Any] = None,
        resolve_dependencies=None,
        broadcast_callback=None,
    ):
        self.tools = tools
        self.llm = llm
        self.logger = logger
        self.execution_trace = execution_trace
        self.completed_nodes = completed_nodes
        self.node_dependencies = node_dependencies
        self.mcp_manager = mcp_manager
        self.tool_schemas = tool_schemas or {}
        self.param_guard = param_guard
        self.resolve_dependencies = resolve_dependencies
        self.broadcast_callback = broadcast_callback


class WorkflowNode(ABC):
    
    def __init__(self, subtask, context: NodeExecutionContext):
        self.subtask = subtask
        self.context = context
        self.logger = context.logger
    
    @abstractmethod
    def execute(self, state: WorkflowState) -> WorkflowState:
        pass
    
    def _should_execute(self, state: WorkflowState) -> bool:
        if self.subtask.id in self.context.completed_nodes:
            return False
        return self._dependencies_ready(state)
    
    def _dependencies_ready(self, state: WorkflowState) -> bool:
        dependencies = self.context.node_dependencies.get(self.subtask.id)
        if not dependencies:
            return True
        outputs = state.get("outputs") or {}
        return all(dep in outputs for dep in dependencies)
    
    def _create_trace_entry(self, node_type: str, **extra) -> Dict[str, Any]:
        return {
            "node_id": self.subtask.id,
            "node_name": self.subtask.name,
            "node_type": node_type,
            "start_time": datetime.now().isoformat(),
            "status": "running",
            **extra
        }
    
    def _finalize_trace(self, trace_entry: Dict[str, Any], result: Any = None, error: Optional[Exception] = None):
        end_time = datetime.now()
        start_time = datetime.fromisoformat(trace_entry["start_time"])
        trace_entry["end_time"] = end_time.isoformat()
        trace_entry["duration_ms"] = (end_time - start_time).total_seconds() * 1000
        
        if error:
            trace_entry["status"] = "failed"
            trace_entry["error"] = str(error)
        else:
            trace_entry["status"] = "success"
            trace_entry["output"] = result
        
        self.context.execution_trace.append(trace_entry)
        self.context.completed_nodes.add(self.subtask.id)
        
        if self.context.broadcast_callback:
            try:
                self.context.broadcast_callback(trace_entry)
            except Exception as e:
                self.logger.warning(f"广播 trace 失败: {e}")
    
    @staticmethod
    def _strip_think_tags(value: Any) -> Any:
        if isinstance(value, str):
            cleaned = re.sub(r"<think>.*?</think>", "", value, flags=re.DOTALL)
            return cleaned.strip()
        return value
