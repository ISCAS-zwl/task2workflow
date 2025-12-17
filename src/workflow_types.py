from typing import Any, Dict, List, Optional, TypedDict, Annotated
from operator import add

def merge_current_tasks(existing: Optional[List[str]], new: List[str]) -> List[str]:
    if existing is None:
        return new
    return existing + new

def merge_outputs(existing: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
    if existing is None:
        return new
    return {**existing, **new}

def merge_errors(existing: Optional[str], new: str) -> str:
    if existing is None:
        return new
    return f"{existing}; {new}"

class WorkflowState(TypedDict):
    messages: Annotated[List[Any], add]
    current_task: Annotated[List[str], merge_current_tasks]
    outputs: Annotated[Dict[str, Any], merge_outputs]
    error: Annotated[Optional[str], merge_errors]
