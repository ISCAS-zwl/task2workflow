from typing import Optional, List, Dict, Any, Literal, Union
from pydantic import BaseModel, Field


class NodeInput(BaseModel):
    pre_output: Optional[str]
    parameter: Union[str, Dict]


class LLMConfig(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class Subtask(BaseModel):
    id: str
    name: str
    description: str

    executor: Literal["llm", "tool", "param_guard"] = "llm"
    tool_name: Optional[str] = None

    source: Optional[Union[str, List[str]]] = Field(default=None, description="前置节点，没有则为 null")
    target: Optional[Union[str, List[str]]] = Field(default=None, description="后置节点，没有则为 null")

    output: Optional[str] = Field(default=None, description="子任务预期输出")
    input: Optional[Dict[str, Any]] = Field(default=None, description="输入定义")
    
    llm_config: Optional[LLMConfig] = Field(default=None, description="LLM节点和param_guard节点的自定义模型配置")


class Edge(BaseModel):
    source: str
    target: str


class WorkflowIR(BaseModel):
    nodes: List[Subtask]
    edges: List[Edge]
