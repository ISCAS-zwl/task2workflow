"""Benchmark 数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskCategory(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    EDGE_CASE = "edge_case"


@dataclass
class TestCase:
    id: str
    task: str
    category: TaskCategory
    expected_tools: List[str] = field(default_factory=list)
    expected_node_count: Optional[int] = None
    expected_output_keywords: List[str] = field(default_factory=list)
    timeout: int = 120
    description: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestCase":
        category = data.get("category", "simple")
        if isinstance(category, str):
            category = TaskCategory(category)
        return cls(
            id=data["id"],
            task=data["task"],
            category=category,
            expected_tools=data.get("expected_tools", []),
            expected_node_count=data.get("expected_node_count"),
            expected_output_keywords=data.get("expected_output_keywords", []),
            timeout=data.get("timeout", 120),
            description=data.get("description", ""),
        )


@dataclass
class PlanningMetrics:
    json_valid: bool = False
    json_fix_attempts: int = 0
    dag_valid: bool = False
    dag_has_cycle: bool = False
    dag_has_orphan: bool = False
    node_count: int = 0
    edge_count: int = 0
    selected_tools: List[str] = field(default_factory=list)
    tool_precision: float = 0.0
    tool_recall: float = 0.0
    tool_f1: float = 0.0
    node_count_diff: int = 0
    planning_latency_ms: float = 0.0
    stage1_latency_ms: float = 0.0
    stage2_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error: Optional[str] = None


@dataclass
class ExecutionMetrics:
    executed: bool = False
    total_nodes: int = 0
    success_nodes: int = 0
    failed_nodes: int = 0
    node_success_rate: float = 0.0
    execution_latency_ms: float = 0.0
    node_latencies_ms: List[float] = field(default_factory=list)
    avg_node_latency_ms: float = 0.0
    output_keywords_matched: int = 0
    output_keywords_total: int = 0
    output_keyword_match_rate: float = 0.0
    task_completed: bool = False
    error: Optional[str] = None
    final_output: Optional[Any] = None


@dataclass
class BenchmarkResult:
    test_case_id: str
    test_case_task: str
    category: TaskCategory
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    planning: PlanningMetrics = field(default_factory=PlanningMetrics)
    execution: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    success: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_case_id": self.test_case_id,
            "test_case_task": self.test_case_task,
            "category": self.category.value,
            "timestamp": self.timestamp,
            "planning": self.planning.__dict__,
            "execution": {
                **self.execution.__dict__,
                "final_output": str(self.execution.final_output)[:500] if self.execution.final_output else None,
            },
            "success": self.success,
            "error": self.error,
        }


@dataclass
class BenchmarkSummary:
    total_cases: int = 0
    successful_cases: int = 0
    failed_cases: int = 0
    
    dag_valid_rate: float = 0.0
    tool_f1: float = 0.0
    
    planning_latency_ms: float = 0.0
    execution_latency_ms: float = 0.0
    
    node_success_rate: float = 0.0
    task_completion_rate: float = 0.0
    
    by_category: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "successful_cases": self.successful_cases,
            "failed_cases": self.failed_cases,
            "accuracy": {
                "dag_valid_rate": self.dag_valid_rate,
                "tool_f1": self.tool_f1,
            },
            "efficiency": {
                "planning_latency_ms": self.planning_latency_ms,
                "execution_latency_ms": self.execution_latency_ms,
            },
            "quality": {
                "node_success_rate": self.node_success_rate,
                "task_completion_rate": self.task_completion_rate,
            },
            "by_category": self.by_category,
        }
