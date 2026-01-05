#!/usr/bin/env python
"""Task2Workflow Benchmark 入口脚本"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from benchmark.runner import BenchmarkRunner
from benchmark.evaluator import BenchmarkEvaluator
from benchmark.report import ReportGenerator


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(description="Task2Workflow Benchmark")
    parser.add_argument(
        "--test-cases", "-t",
        type=str,
        nargs="*",
        help="Specific test case IDs to run (e.g., TC001 TC002)"
    )
    parser.add_argument(
        "--categories", "-c",
        type=str,
        nargs="*",
        choices=["simple", "medium", "complex", "edge_case"],
        help="Categories to run"
    )
    parser.add_argument(
        "--skip-execution", "-s",
        action="store_true",
        help="Skip workflow execution, only test planning"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        help="Output directory for results"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--report-only", "-r",
        type=str,
        help="Generate report from existing results file (skip running)"
    )
    
    args = parser.parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    project_root = Path(__file__).parent
    output_dir = Path(args.output_dir) if args.output_dir else project_root / "benchmark" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if args.report_only:
        logger.info("Loading results from: %s", args.report_only)
        evaluator = BenchmarkEvaluator()
        results = evaluator.load_results(Path(args.report_only))
        summary = evaluator.compute_summary()
    else:
        runner = BenchmarkRunner(
            output_dir=output_dir,
            skip_execution=args.skip_execution,
        )
        
        logger.info("=" * 60)
        logger.info("Task2Workflow Benchmark")
        logger.info("=" * 60)
        
        results = runner.run_all(
            test_case_ids=args.test_cases,
            categories=args.categories,
        )
        
        results_path = runner.save_results(f"benchmark_results_{timestamp}.json")
        logger.info("Results saved to: %s", results_path)
        
        evaluator = BenchmarkEvaluator(results)
        summary = evaluator.compute_summary()
    
    report_gen = ReportGenerator(results, summary)
    
    md_path = output_dir / f"benchmark_report_{timestamp}.md"
    report_gen.save_markdown(md_path)
    logger.info("Markdown report saved to: %s", md_path)
    
    summary_path = output_dir / f"benchmark_summary_{timestamp}.json"
    report_gen.save_json_summary(summary_path)
    logger.info("JSON summary saved to: %s", summary_path)
    
    print("\n" + "=" * 50)
    print("BENCHMARK SUMMARY")
    print("=" * 50)
    print(f"Total: {summary.total_cases}  Success: {summary.successful_cases}  Failed: {summary.failed_cases}")
    print("-" * 50)
    print("Accuracy")
    print(f"  DAG Valid Rate:      {summary.dag_valid_rate:.1%}")
    print(f"  Tool F1:             {summary.tool_f1:.1%}")
    print("-" * 50)
    print("Efficiency")
    print(f"  Planning Latency:    {summary.planning_latency_ms:.0f} ms")
    print(f"  Execution Latency:   {summary.execution_latency_ms:.0f} ms")
    print("-" * 50)
    print("Quality")
    print(f"  Node Success Rate:   {summary.node_success_rate:.1%}")
    print(f"  Task Completion:     {summary.task_completion_rate:.1%}")
    print("=" * 50)
    
    if summary.failed_cases > 0:
        print(f"\nFailed: {[r.test_case_id for r in evaluator.get_failed_cases()]}")
    
    return 0 if summary.dag_valid_rate >= 0.5 else 1


if __name__ == "__main__":
    sys.exit(main())
