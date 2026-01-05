"""Benchmark 评估器 - 计算汇总指标"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark.models import BenchmarkResult, BenchmarkSummary, TaskCategory


class BenchmarkEvaluator:
    
    def __init__(self, results: Optional[List[BenchmarkResult]] = None):
        self.results = results or []
    
    def load_results(self, results_path: Path) -> List[BenchmarkResult]:
        with results_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        self.results = []
        for r in data.get("results", []):
            result = BenchmarkResult(
                test_case_id=r["test_case_id"],
                test_case_task=r["test_case_task"],
                category=TaskCategory(r["category"]),
                timestamp=r.get("timestamp", ""),
                success=r.get("success", False),
                error=r.get("error"),
            )
            
            planning = r.get("planning", {})
            for key, value in planning.items():
                if hasattr(result.planning, key):
                    setattr(result.planning, key, value)
            
            execution = r.get("execution", {})
            for key, value in execution.items():
                if hasattr(result.execution, key) and key != "final_output":
                    setattr(result.execution, key, value)
            
            self.results.append(result)
        
        return self.results
    
    def compute_summary(self) -> BenchmarkSummary:
        if not self.results:
            return BenchmarkSummary()
        
        summary = BenchmarkSummary()
        summary.total_cases = len(self.results)
        summary.successful_cases = sum(1 for r in self.results if r.success)
        summary.failed_cases = summary.total_cases - summary.successful_cases
        
        dag_valid_count = sum(1 for r in self.results if r.planning.dag_valid)
        summary.dag_valid_rate = dag_valid_count / summary.total_cases
        
        tool_f1s = [r.planning.tool_f1 for r in self.results if r.planning.tool_f1 > 0]
        summary.tool_f1 = sum(tool_f1s) / len(tool_f1s) if tool_f1s else 0
        
        planning_latencies = [r.planning.planning_latency_ms for r in self.results if r.planning.planning_latency_ms > 0]
        execution_latencies = [r.execution.execution_latency_ms for r in self.results if r.execution.execution_latency_ms > 0]
        
        summary.planning_latency_ms = sum(planning_latencies) / len(planning_latencies) if planning_latencies else 0
        summary.execution_latency_ms = sum(execution_latencies) / len(execution_latencies) if execution_latencies else 0
        
        node_success_rates = [r.execution.node_success_rate for r in self.results if r.execution.executed]
        task_completions = [1 if r.execution.task_completed else 0 for r in self.results if r.execution.executed]
        
        summary.node_success_rate = sum(node_success_rates) / len(node_success_rates) if node_success_rates else 0
        summary.task_completion_rate = sum(task_completions) / len(task_completions) if task_completions else 0
        
        summary.by_category = self._compute_by_category()
        
        return summary
    
    def _compute_by_category(self) -> Dict[str, Dict[str, Any]]:
        by_category: Dict[str, List[BenchmarkResult]] = defaultdict(list)
        for r in self.results:
            by_category[r.category.value].append(r)
        
        category_stats = {}
        for category, results in by_category.items():
            total = len(results)
            success = sum(1 for r in results if r.success)
            
            planning_latencies = [r.planning.planning_latency_ms for r in results if r.planning.planning_latency_ms > 0]
            execution_latencies = [r.execution.execution_latency_ms for r in results if r.execution.execution_latency_ms > 0]
            
            category_stats[category] = {
                "total": total,
                "success": success,
                "failed": total - success,
                "success_rate": success / total if total else 0,
                "avg_planning_latency_ms": sum(planning_latencies) / len(planning_latencies) if planning_latencies else 0,
                "avg_execution_latency_ms": sum(execution_latencies) / len(execution_latencies) if execution_latencies else 0,
            }
        
        return category_stats
    
    def get_failed_cases(self) -> List[BenchmarkResult]:
        return [r for r in self.results if not r.success]
    
    def get_slowest_cases(self, top_n: int = 5) -> List[BenchmarkResult]:
        sorted_results = sorted(
            self.results,
            key=lambda r: r.planning.planning_latency_ms + r.execution.execution_latency_ms,
            reverse=True
        )
        return sorted_results[:top_n]
    
    def get_tool_usage_stats(self) -> Dict[str, int]:
        tool_counts: Dict[str, int] = defaultdict(int)
        for r in self.results:
            for tool in r.planning.selected_tools:
                tool_counts[tool] += 1
        return dict(sorted(tool_counts.items(), key=lambda x: x[1], reverse=True))
