from typing import Dict, Type

from node.base_node import WorkflowNode, NodeExecutionContext
from node.llm_node import LLMNode
from node.tool_node import ToolNode
from node.param_guard_node import ParamGuardNode


class NodeFactory:
    
    _node_classes: Dict[str, Type[WorkflowNode]] = {
        "llm": LLMNode,
        "tool": ToolNode,
        "param_guard": ParamGuardNode,
    }
    
    @classmethod
    def create(cls, subtask, context: NodeExecutionContext) -> WorkflowNode:
        node_class = cls._node_classes.get(subtask.executor)
        if not node_class:
            raise ValueError(f"未知的executor类型: {subtask.executor}")
        return node_class(subtask, context)
    
    @classmethod
    def register(cls, executor_type: str, node_class: Type[WorkflowNode]):
        cls._node_classes[executor_type] = node_class
    
    @classmethod
    def get_supported_types(cls):
        return list(cls._node_classes.keys())
