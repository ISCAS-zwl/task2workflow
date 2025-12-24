import argparse
import json
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from src.subtask_planner import SubtaskPlanner


def _write_text(path: Path, content: str) -> None:
    path.write_text(content if content else "", encoding="utf-8")


def main() -> int:

    parser = argparse.ArgumentParser(description="Run two-stage planner demo.")
    parser.add_argument(
        "--task",
        default="Please help me analyze the weather changes in Beijing over the past seven days and save it as an Excel file.",
        help="Task to plan.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory (default: test/demo_outputs/<timestamp>).",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent / "test"
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = base_dir / "demo_outputs" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    planner = SubtaskPlanner()
    planner.last_run = {"task": args.task}

    stage2_output = planner._generate_workflow_json(args.task)
    planner.last_run["raw_json"] = stage2_output

    stage1_raw = planner.last_run.get("draft_json_raw") or ""
    stage1_draft = planner.last_run.get("draft_json") or ""
    stage1_tools = planner.last_run.get("stage1_selected_tool_names") or []
    stage2_tools = planner.last_run.get("stage2_tools") or []

    _write_text(out_dir / "stage1_raw.txt", stage1_raw)
    _write_text(out_dir / "stage1_draft.json", stage1_draft)
    _write_text(out_dir / "stage1_selected_tools.json", json.dumps(stage1_tools, ensure_ascii=False))
    _write_text(out_dir / "stage2_tools_filtered.json", json.dumps(stage2_tools, ensure_ascii=False))
    _write_text(out_dir / "stage2_output.json", stage2_output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
