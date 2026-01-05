"""Benchmark 运行器"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark.models import (
    BenchmarkResult,
    ExecutionMetrics,
    PlanningMetrics,
    TestCase,
)

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    
    def __init__(
        self,
        test_cases_path: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        skip_execution: bool = False,
    ):
        self.project_root = Path(__file__).parent.parent
        self.test_cases_path = test_cases_path or self.project_root / "benchmark" / "test_cases.json"
        self.output_dir = output_dir or self.project_root / "benchmark" / "results"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.skip_execution = skip_execution
        self.results: List[BenchmarkResult] = []
        
    def load_test_cases(self) -> List[TestCase]:
        with self.test_cases_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [TestCase.from_dict(tc) for tc in data.get("test_cases", [])]
    
    def run_single(self, test_case: TestCase) -> BenchmarkResult:
        from src.subtask_planner import SubtaskPlanner
        from src.graph2workflow import Graph2Workflow
        from src.graph_validator import validate_workflow_ir
        from tools.mcp_manager import MCPToolManager, MCPManagerError
        
        result = BenchmarkResult(
            test_case_id=test_case.id,
            test_case_task=test_case.task,
            category=test_case.category,
        )
        
        if not test_case.task.strip():
            result.error = "Empty task"
            result.planning.error = "Empty task"
            return result
        
        planner = None
        mcp_manager = None
        
        try:
            mcp_manager = MCPToolManager()
        except MCPManagerError as e:
            logger.warning("MCP manager not available: %s", e)
        
        try:
            start_time = time.time()
            planner = SubtaskPlanner()
            
            try:
                workflow_ir = planner.plan(test_case.task)
                planning_end_time = time.time()
                
                last_run = planner.get_last_run()
                result.planning = self._extract_planning_metrics(
                    last_run, 
                    test_case,
                    planning_end_time - start_time
                )
                result.planning.json_valid = True
                result.planning.dag_valid = True
                
            except Exception as e:
                planning_end_time = time.time()
                logger.error("Planning failed for %s: %s", test_case.id, e)
                last_run = planner.get_last_run() if planner else {}
                result.planning = self._extract_planning_metrics(
                    last_run,
                    test_case, 
                    planning_end_time - start_time
                )
                result.planning.error = str(e)
                result.error = f"Planning failed: {e}"
                return result
            
            if self.skip_execution:
                result.success = result.planning.dag_valid
                return result
            
            try:
                exec_start_time = time.time()
                tools = {}
                g2w = Graph2Workflow(workflow_ir, tools, mcp_manager=mcp_manager)
                final_state = g2w.execute()
                exec_end_time = time.time()
                
                execution_trace = g2w.get_execution_trace()
                result.execution = self._extract_execution_metrics(
                    execution_trace,
                    final_state,
                    test_case,
                    exec_end_time - exec_start_time
                )
                
                result.success = (
                    result.planning.dag_valid 
                    and result.execution.node_success_rate >= 0.8
                    and result.execution.error is None
                )
                
            except Exception as e:
                exec_end_time = time.time()
                logger.error("Execution failed for %s: %s", test_case.id, e)
                result.execution.error = str(e)
                result.execution.execution_latency_ms = (exec_end_time - exec_start_time) * 1000
                result.error = f"Execution failed: {e}"
                
        except Exception as e:
            logger.exception("Unexpected error for %s", test_case.id)
            result.error = f"Unexpected error: {e}"
            
        finally:
            if mcp_manager:
                try:
                    mcp_manager.shutdown()
                except Exception:
                    pass
                    
        return result
    
    def _extract_planning_metrics(
        self, 
        last_run: Dict[str, Any], 
        test_case: TestCase,
        elapsed_seconds: float
    ) -> PlanningMetrics:
        metrics = PlanningMetrics()
        metrics.planning_latency_ms = elapsed_seconds * 1000
        
        metrics.json_fix_attempts = len(last_run.get("fix_attempts", []))
        
        stage1_meta = last_run.get("stage1_llm_response_metadata") or {}
        stage2_meta = last_run.get("llm_response_metadata") or {}
        
        metrics.prompt_tokens = (stage1_meta.get("prompt_tokens") or 0) + (stage2_meta.get("prompt_tokens") or 0)
        metrics.completion_tokens = (stage1_meta.get("completion_tokens") or 0) + (stage2_meta.get("completion_tokens") or 0)
        metrics.total_tokens = metrics.prompt_tokens + metrics.completion_tokens
        
        workflow_ir = last_run.get("workflow_ir")
        if workflow_ir:
            metrics.node_count = len(workflow_ir.nodes)
            metrics.edge_count = len(workflow_ir.edges)
            
            metrics.selected_tools = [
                node.tool_name for node in workflow_ir.nodes 
                if node.executor == "tool" and node.tool_name
            ]
            
            if test_case.expected_tools:
                expected_set = set(test_case.expected_tools)
                selected_set = set(metrics.selected_tools)
                
                if selected_set:
                    metrics.tool_precision = len(expected_set & selected_set) / len(selected_set)
                if expected_set:
                    metrics.tool_recall = len(expected_set & selected_set) / len(expected_set)
                if metrics.tool_precision + metrics.tool_recall > 0:
                    metrics.tool_f1 = 2 * metrics.tool_precision * metrics.tool_recall / (metrics.tool_precision + metrics.tool_recall)
            
            if test_case.expected_node_count is not None:
                metrics.node_count_diff = abs(metrics.node_count - test_case.expected_node_count)
                
            metrics.dag_valid = True
            metrics.dag_has_cycle = False
            metrics.dag_has_orphan = False
            
        return metrics
    
    def _extract_execution_metrics(
        self,
        execution_trace: List[Dict[str, Any]],
        final_state: Dict[str, Any],
        test_case: TestCase,
        elapsed_seconds: float
    ) -> ExecutionMetrics:
        metrics = ExecutionMetrics()
        metrics.executed = True
        metrics.execution_latency_ms = elapsed_seconds * 1000
        
        metrics.total_nodes = len(execution_trace)
        metrics.success_nodes = sum(1 for t in execution_trace if t.get("status") == "success")
        metrics.failed_nodes = sum(1 for t in execution_trace if t.get("status") == "failed")
        
        if metrics.total_nodes > 0:
            metrics.node_success_rate = metrics.success_nodes / metrics.total_nodes
        
        metrics.node_latencies_ms = [
            t.get("duration_ms", 0) for t in execution_trace if t.get("duration_ms")
        ]
        if metrics.node_latencies_ms:
            metrics.avg_node_latency_ms = sum(metrics.node_latencies_ms) / len(metrics.node_latencies_ms)
        
        outputs = final_state.get("outputs", {})
        final_output_str = json.dumps(outputs, ensure_ascii=False) if outputs else ""
        metrics.final_output = outputs
        
        if test_case.expected_output_keywords:
            metrics.output_keywords_total = len(test_case.expected_output_keywords)
            metrics.output_keywords_matched = sum(
                1 for kw in test_case.expected_output_keywords 
                if kw.lower() in final_output_str.lower()
            )
            metrics.output_keyword_match_rate = metrics.output_keywords_matched / metrics.output_keywords_total
        
        metrics.task_completed = (
            metrics.node_success_rate >= 0.8 
            and (not test_case.expected_output_keywords or metrics.output_keyword_match_rate >= 0.5)
        )
        
        if final_state.get("error"):
            metrics.error = final_state["error"]
            
        return metrics
    
    def run_all(
        self, 
        test_case_ids: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        incremental_save: bool = True,
    ) -> List[BenchmarkResult]:
        test_cases = self.load_test_cases()
        
        if test_case_ids:
            test_cases = [tc for tc in test_cases if tc.id in test_case_ids]
        if categories:
            test_cases = [tc for tc in test_cases if tc.category.value in categories]
        
        logger.info("Running benchmark with %d test cases", len(test_cases))
        
        self.results = []
        for i, tc in enumerate(test_cases):
            logger.info("[%d/%d] Running test case: %s - %s", i + 1, len(test_cases), tc.id, tc.task[:50])
            result = self.run_single(tc)
            self.results.append(result)
            logger.info("[%d/%d] Result: success=%s, error=%s", i + 1, len(test_cases), result.success, result.error)
            
            if incremental_save:
                self._save_incremental()
        
        return self.results
    
    def _save_incremental(self):
        output_path = self.output_dir / "benchmark_results_latest.json"
        data = {
            "timestamp": datetime.now().isoformat(),
            "total_cases": len(self.results),
            "results": [r.to_dict() for r in self.results],
        }
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def save_results(self, filename: Optional[str] = None) -> Path:
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"benchmark_results_{timestamp}.json"
        
        output_path = self.output_dir / filename
        
        data = {
            "timestamp": datetime.now().isoformat(),
            "total_cases": len(self.results),
            "results": [r.to_dict() for r in self.results],
        }
        
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info("Results saved to: %s", output_path)
        return output_path
