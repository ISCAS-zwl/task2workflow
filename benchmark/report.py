"""Benchmark 报告生成器"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from benchmark.models import BenchmarkResult, BenchmarkSummary
from benchmark.evaluator import BenchmarkEvaluator


class ReportGenerator:
    
    def __init__(self, results: List[BenchmarkResult], summary: BenchmarkSummary):
        self.results = results
        self.summary = summary
        self.evaluator = BenchmarkEvaluator(results)
    
    def generate_markdown(self) -> str:
        lines = []
        
        lines.append("# Task2Workflow Benchmark Report")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Total Test Cases:** {self.summary.total_cases}")
        lines.append("")
        
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Cases | {self.summary.total_cases} |")
        lines.append(f"| Successful | {self.summary.successful_cases} |")
        lines.append(f"| Failed | {self.summary.failed_cases} |")
        lines.append("")
        
        lines.append("## Accuracy")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| DAG Valid Rate | {self.summary.dag_valid_rate:.1%} |")
        lines.append(f"| Tool F1 | {self.summary.tool_f1:.1%} |")
        lines.append("")
        
        lines.append("## Efficiency")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Planning Latency | {self.summary.planning_latency_ms:.0f} ms |")
        lines.append(f"| Execution Latency | {self.summary.execution_latency_ms:.0f} ms |")
        lines.append("")
        
        lines.append("## Quality")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Node Success Rate | {self.summary.node_success_rate:.1%} |")
        lines.append(f"| Task Completion Rate | {self.summary.task_completion_rate:.1%} |")
        lines.append("")
        
        lines.append("## Results by Category")
        lines.append("")
        lines.append("| Category | Total | Success | Failed | Success Rate | Avg Planning (ms) | Avg Execution (ms) |")
        lines.append("|----------|-------|---------|--------|--------------|-------------------|-------------------|")
        for category, stats in self.summary.by_category.items():
            lines.append(
                f"| {category} | {stats['total']} | {stats['success']} | {stats['failed']} | "
                f"{stats['success_rate']:.1%} | {stats['avg_planning_latency_ms']:.0f} | "
                f"{stats['avg_execution_latency_ms']:.0f} |"
            )
        lines.append("")
        
        failed_cases = self.evaluator.get_failed_cases()
        if failed_cases:
            lines.append("## Failed Cases")
            lines.append("")
            lines.append("| ID | Task | Error |")
            lines.append("|----|------|-------|")
            for r in failed_cases:
                task_short = r.test_case_task[:40] + "..." if len(r.test_case_task) > 40 else r.test_case_task
                error_short = (r.error or "Unknown")[:50] + "..." if r.error and len(r.error) > 50 else (r.error or "Unknown")
                lines.append(f"| {r.test_case_id} | {task_short} | {error_short} |")
            lines.append("")
        
        slowest = self.evaluator.get_slowest_cases(5)
        if slowest:
            lines.append("## Slowest Cases (Top 5)")
            lines.append("")
            lines.append("| ID | Task | Planning (ms) | Execution (ms) | Total (ms) |")
            lines.append("|----|------|---------------|----------------|------------|")
            for r in slowest:
                task_short = r.test_case_task[:30] + "..." if len(r.test_case_task) > 30 else r.test_case_task
                total = r.planning.planning_latency_ms + r.execution.execution_latency_ms
                lines.append(
                    f"| {r.test_case_id} | {task_short} | "
                    f"{r.planning.planning_latency_ms:.0f} | {r.execution.execution_latency_ms:.0f} | {total:.0f} |"
                )
            lines.append("")
        
        tool_stats = self.evaluator.get_tool_usage_stats()
        if tool_stats:
            lines.append("## Tool Usage Statistics")
            lines.append("")
            lines.append("| Tool | Usage Count |")
            lines.append("|------|-------------|")
            for tool, count in list(tool_stats.items())[:15]:
                lines.append(f"| {tool} | {count} |")
            lines.append("")
        
        lines.append("## Detailed Results")
        lines.append("")
        lines.append("| ID | Category | Task | Success | Planning (ms) | Execution (ms) | Nodes | Tool Precision |")
        lines.append("|----|----------|------|---------|---------------|----------------|-------|----------------|")
        for r in self.results:
            task_short = r.test_case_task[:25] + "..." if len(r.test_case_task) > 25 else r.test_case_task
            success_icon = "✅" if r.success else "❌"
            lines.append(
                f"| {r.test_case_id} | {r.category.value} | {task_short} | {success_icon} | "
                f"{r.planning.planning_latency_ms:.0f} | {r.execution.execution_latency_ms:.0f} | "
                f"{r.planning.node_count} | {r.planning.tool_precision:.1%} |"
            )
        lines.append("")
        
        return "\n".join(lines)
    
    def save_markdown(self, output_path: Path) -> Path:
        content = self.generate_markdown()
        with output_path.open("w", encoding="utf-8") as f:
            f.write(content)
        return output_path
    
    def save_json_summary(self, output_path: Path) -> Path:
        data = {
            "generated_at": datetime.now().isoformat(),
            "summary": self.summary.to_dict(),
            "failed_cases": [
                {"id": r.test_case_id, "task": r.test_case_task, "error": r.error}
                for r in self.evaluator.get_failed_cases()
            ],
            "tool_usage": self.evaluator.get_tool_usage_stats(),
        }
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return output_path
