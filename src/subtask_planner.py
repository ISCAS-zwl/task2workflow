import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from openai import OpenAI
from pydantic import ValidationError

from src.config import get_config
from src.graph_validator import validate_workflow_ir
from src.tool_retriever import ToolRetriever
from src.task_optimizer import TaskOptimizer
from src.planner.models import NodeInput, LLMConfig, Subtask, Edge, WorkflowIR
from src.planner.json_extractor import JsonExtractor
from src.planner.guard_injector import GuardInjector

__all__ = [
    "SubtaskPlanner",
    "NodeInput",
    "LLMConfig", 
    "Subtask",
    "Edge",
    "WorkflowIR",
]

logger = logging.getLogger(__name__)


def _load_tools_definition() -> Dict[str, Any]:
    config = get_config()
    path = config.tools_generated_path
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            content = json.load(f)
            return content if isinstance(content, dict) else {}
    except Exception as exc:
        logger.warning("读取工具文件 %s 失败：%s", path, exc)
        return {}


def _load_prompt(path: Path, fallback: Path) -> str:
    for candidate in (path, fallback):
        if candidate and candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt template not found: {path} (fallback: {fallback})")


def _build_stage1_tools_payload(tools: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for name, meta in (tools or {}).items():
        description = ""
        input_schema = {}
        if isinstance(meta, dict):
            description = str(meta.get("description") or "")
            input_schema = meta.get("input_schema") or {}
        
        properties = input_schema.get("properties") or {} if isinstance(input_schema, dict) else {}
        required = input_schema.get("required") or [] if isinstance(input_schema, dict) else []
        required_set = set(required) if isinstance(required, list) else set()
        
        properties_summary: List[Dict[str, Any]] = []
        if isinstance(properties, dict):
            for key, prop in properties.items():
                if not isinstance(prop, dict):
                    prop = {}
                field_info: Dict[str, Any] = {"name": str(key)}
                if "type" in prop:
                    field_info["type"] = prop.get("type")
                if "description" in prop:
                    field_info["description"] = prop.get("description")
                if "enum" in prop:
                    field_info["enum"] = prop.get("enum")
                field_info["required"] = str(key) in required_set
                properties_summary.append(field_info)
        
        payload.append({
            "name": str(name),
            "description": description,
            "properties": properties_summary,
        })
    return payload


def _extract_tool_names_from_stage1(draft_json: str) -> List[str]:
    if not draft_json:
        return []
    try:
        parsed = json.loads(draft_json)
    except Exception:
        return []
    if not isinstance(parsed, dict):
        return []
    nodes = parsed.get("nodes")
    if not isinstance(nodes, list):
        return []
    tool_names: List[str] = []
    seen = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("executor") != "tool":
            continue
        tool_name = node.get("tool_name")
        if isinstance(tool_name, str) and tool_name and tool_name not in seen:
            tool_names.append(tool_name)
            seen.add(tool_name)
    return tool_names


def _extract_missing_tool_queries(draft_json: str) -> List[str]:
    if not draft_json:
        return []
    try:
        parsed = json.loads(draft_json)
    except Exception:
        return []
    if not isinstance(parsed, dict):
        return []
    missing_tools = parsed.get("missing_tools")
    if not isinstance(missing_tools, list):
        return []
    queries: List[str] = []
    for item in missing_tools:
        if not isinstance(item, dict):
            continue
        capability = item.get("capability")
        keywords = item.get("keywords")
        parts: List[str] = []
        if isinstance(capability, str) and capability.strip():
            parts.append(capability.strip())
        if isinstance(keywords, list):
            parts.extend([str(k).strip() for k in keywords if str(k).strip()])
        query = " ".join(parts).strip()
        if query:
            queries.append(query)
    return queries


def _filter_tools_by_name(tools: Dict[str, Any], names: List[str]) -> Dict[str, Any]:
    if not tools or not names:
        return {}
    return {name: tools[name] for name in names if name in tools}


class SubtaskPlanner:

    def __init__(self, model: str | None = None):
        self.config = get_config()
        self.model = model or self.config.planner_model
        self.client = OpenAI(
            api_key=self.config.planner_key,
            base_url=self.config.planner_url,
        )
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.last_run: Dict[str, Any] = {}
        self.tools_definition = _load_tools_definition()
        self.json_extractor = JsonExtractor(max_fix_attempts=self.config.max_fix_attempts)
        self.guard_injector = GuardInjector(self.tools_definition)
        self.task_optimizer = TaskOptimizer(model=self.model)

    def _render_stage1_prompt(self, tools: str, task: str) -> str:
        template = _load_prompt(
            self.config.plan_stage1_prompt_path,
            self.config.plan_prompt_path,
        )
        return template.format(tools=tools, task=task)

    def _render_stage2_prompt(self, tools: str, task: str, draft: str) -> str:
        template = _load_prompt(
            self.config.plan_stage2_prompt_path,
            self.config.plan_prompt_path,
        )
        return template.format(tools=tools, task=task, draft=draft)

    def _call_planner_llm(self, prompt: str) -> Tuple[str, Dict[str, Any]]:
        system_prompt = "You are a workflow planning assistant. Output JSON only."
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

        content = resp.choices[0].message.content if resp.choices else ""
        if content:
            content = content.strip()

        metadata = {
            "model": self.model,
            "finish_reason": resp.choices[0].finish_reason if resp.choices else None,
            "content_length": len(content),
            "has_content": bool(content),
            "prompt_tokens": resp.usage.prompt_tokens if resp.usage else None,
            "completion_tokens": resp.usage.completion_tokens if resp.usage else None,
            "total_tokens": resp.usage.total_tokens if resp.usage else None,
        }
        return content, metadata

    def _generate_workflow_json(self, task: str) -> str:
        full_tools = _load_tools_definition()
        tools_content = full_tools
        retriever = ToolRetriever(full_tools)
        tools_subset = retriever.retrieve_subset(task, top_k=self.config.tool_retriever_top_k)
        if tools_subset:
            self.logger.info(
                "ToolRetriever selected %s/%s tools for planning",
                len(tools_subset),
                len(full_tools),
            )
            tools_content = tools_subset
        
        stage1_tools_payload = _build_stage1_tools_payload(tools_content)
        stage1_tools_json = json.dumps(stage1_tools_payload, ensure_ascii=False)

        stage1_prompt = self._render_stage1_prompt(stage1_tools_json, task)
        stage1_content, stage1_meta = self._call_planner_llm(stage1_prompt)
        self.last_run["stage1_llm_response_metadata"] = stage1_meta
        self.last_run["draft_json_raw"] = stage1_content or None

        if not stage1_content:
            self.logger.error("Stage 1: LLM returned empty content.")
            draft_json = ""
        else:
            try:
                draft_json = self.json_extractor.extract(stage1_content)
            except ValueError:
                self.logger.warning("Stage 1: failed to extract JSON, using raw content.")
                draft_json = stage1_content

        self.last_run["draft_json"] = draft_json
        
        initial_missing_queries = _extract_missing_tool_queries(draft_json)
        if initial_missing_queries:
            extra_tools: Dict[str, Any] = {}
            for query in initial_missing_queries:
                more = retriever.retrieve_subset(query, top_k=self.config.tool_retriever_expand_k)
                if more:
                    extra_tools.update(more)
            if extra_tools:
                expanded_tools = {**tools_content, **extra_tools}
                if len(expanded_tools) > len(tools_content):
                    self.logger.info(
                        "Stage 1: expanded tools from %s to %s based on missing_tools",
                        len(tools_content),
                        len(expanded_tools),
                    )
                    stage1_tools_payload = _build_stage1_tools_payload(expanded_tools)
                    stage1_tools_json = json.dumps(stage1_tools_payload, ensure_ascii=False)
                    stage1_prompt = self._render_stage1_prompt(stage1_tools_json, task)
                    stage1_content, stage1_meta = self._call_planner_llm(stage1_prompt)
                    self.last_run["stage1_llm_response_metadata"] = stage1_meta
                    self.last_run["draft_json_raw"] = stage1_content or None
                    if stage1_content:
                        try:
                            draft_json = self.json_extractor.extract(stage1_content)
                        except ValueError:
                            self.logger.warning("Stage 1 retry: failed to extract JSON, using raw content.")
                            draft_json = stage1_content
                    self.last_run["draft_json"] = draft_json
                    tools_content = expanded_tools

        missing_queries = _extract_missing_tool_queries(draft_json)
        self.last_run["stage1_missing_tool_queries"] = missing_queries

        selected_tool_names = _extract_tool_names_from_stage1(draft_json)
        self.last_run["stage1_selected_tool_names"] = selected_tool_names

        stage2_tools_content = _filter_tools_by_name(full_tools, selected_tool_names)
        if selected_tool_names and not stage2_tools_content:
            self.logger.warning("Stage 2: no selected tools matched available tools.")
        if not selected_tool_names:
            self.logger.warning("Stage 2: no tools selected in stage 1.")
        stage2_tools_json = json.dumps(stage2_tools_content, ensure_ascii=False)
        self.last_run["stage2_tools_json"] = stage2_tools_json
        self.last_run["stage2_tools"] = list(stage2_tools_content.keys())

        stage2_prompt = self._render_stage2_prompt(stage2_tools_json, task, draft_json)
        stage2_content, stage2_meta = self._call_planner_llm(stage2_prompt)
        self.last_run["llm_response_metadata"] = stage2_meta

        if not stage2_content:
            self.logger.error("Stage 2: LLM returned empty content.")
            return "{}"

        try:
            return self.json_extractor.extract(stage2_content)
        except ValueError:
            self.logger.warning("Stage 2: failed to extract JSON, entering auto-fix.")
            return stage2_content

    def _auto_fix_json(self, raw_json: str) -> dict:
        for attempt in range(1, self.config.max_fix_attempts + 1):
            self.logger.info("Stage 2: attempt %s to parse/fix JSON", attempt)
            try:
                parsed = self.json_extractor.extract_and_validate(raw_json)
                
                self.last_run["fix_attempts"].append({
                    "attempt": attempt,
                    "status": "success",
                    "input": raw_json[:self.config.log_truncate_length],
                    "output": json.dumps(parsed, ensure_ascii=False)[:self.config.log_truncate_length],
                    "nodes_count": len(parsed.get("nodes", [])),
                    "edges_count": len(parsed.get("edges", [])),
                })
                
                self.logger.info("Stage 2: JSON fix success, nodes: %d, edges: %d", 
                               len(parsed["nodes"]), len(parsed["edges"]))
                return parsed
            except Exception as e:
                self.last_run["fix_attempts"].append({
                    "attempt": attempt,
                    "status": "failed",
                    "input": raw_json[:self.config.log_truncate_length],
                    "error": str(e),
                })
                
                tools_json = self.last_run.get("stage2_tools_json")
                if not tools_json:
                    tools_content = _load_tools_definition()
                    selected_tools = self.last_run.get("stage1_selected_tool_names") or []
                    tools_content = _filter_tools_by_name(tools_content, selected_tools)
                    tools_json = json.dumps(tools_content, ensure_ascii=False)
                draft_json = self.last_run.get("draft_json") or self.last_run.get("draft_json_raw") or ""
                original_prompt = self._render_stage2_prompt(
                    tools_json,
                    self.last_run.get('task', ''),
                    draft_json,
                )
                
                fix_prompt = f"""
{original_prompt}

---

你之前生成的内容不符合要求：

```
{raw_json[:self.config.fix_prompt_truncate_length]}
```

请重新生成完整的工作流 JSON。注意：
1. 不要输出 <think> 标签或任何解释
2. 只输出纯 JSON
"""
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": fix_prompt}],
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
                raw_json = resp.choices[0].message.content.strip()
                self.logger.info("Stage 2: retrying JSON fix based on LLM response")

        self.logger.error("Stage 2: all %d fix attempts failed", self.config.max_fix_attempts)
        self.last_run["error_stage"] = "auto_fix_json"
        raise ValueError(f"{self.config.max_fix_attempts} fix attempts failed: unable to generate valid JSON")

    def _build_workflow_ir(self, fixed_json: dict) -> WorkflowIR:
        try:
            workflow_ir = WorkflowIR(
                nodes=[Subtask(**n) for n in fixed_json["nodes"]],
                edges=fixed_json["edges"],
            )
            workflow_ir = self.guard_injector.inject(workflow_ir)
            self.logger.info("Stage 3: WorkflowIR validation complete")
            
            selected_tools = self.last_run.get("stage1_selected_tool_names")
            if selected_tools is not None:
                available_tools = set(selected_tools)
            else:
                available_tools = set(self.tools_definition.keys())
            
            validation_result = validate_workflow_ir(workflow_ir, available_tools)
            if not validation_result.is_valid:
                self.logger.error(f"Stage 3: graph validation failed\n{validation_result}")
                raise ValueError(f"Graph validation failed: {validation_result}")
            
            if validation_result.warnings:
                self.logger.warning(f"Stage 3: graph validation warnings\n{validation_result}")
            
            return workflow_ir
        except ValidationError as e:
            self.logger.error("Stage 3: Pydantic validation failed")
            raise ValueError(f"Pydantic validation failed: {e}")

    def plan(self, task: str) -> WorkflowIR:
        self.last_run = {
            "task": task,
            "optimized_task": None,
            "plan_text": None,
            "draft_json_raw": None,
            "draft_json": None,
            "raw_json": None,
            "fixed_json": None,
            "workflow_ir": None,
            "workflow_json_str": None,
            "error": None,
            "error_stage": None,
            "fix_attempts": [],
            "stage1_llm_response_metadata": None,
            "llm_response_metadata": None,
            "stage1_selected_tool_names": None,
            "stage1_missing_tool_queries": None,
            "stage2_tools_json": None,
            "stage2_tools": None,
        }

        try:
            self.logger.info("Stage 0: optimizing task: %s", task)
            optimized_task = self.task_optimizer.optimize(task)
            self.last_run["optimized_task"] = optimized_task
            
            self.logger.info("Stage 1: generating JSON plan for task: %s", optimized_task)
            raw_json = self._generate_workflow_json(optimized_task)
            self.last_run["plan_text"] = "[Direct JSON generation, no natural language plan]"
            self.last_run["raw_json"] = raw_json
            self.logger.info("Stage 1: JSON plan generation complete")

            try:
                fixed_json = self._auto_fix_json(raw_json)
                self.last_run["fixed_json"] = fixed_json
            except Exception as e:
                self.last_run["error"] = str(e)
                self.last_run["error_stage"] = "auto_fix_json"
                self.logger.exception("Stage 2: JSON fix failed")
                raise

            try:
                workflow_ir = self._build_workflow_ir(fixed_json)
                self.last_run["workflow_ir"] = workflow_ir
                workflow_json_str = workflow_ir.model_dump_json(indent=2, ensure_ascii=False)
                self.last_run["workflow_json_str"] = workflow_json_str
                self.logger.info("Stage 3: WorkflowIR generation complete")
            except Exception as e:
                self.last_run["error"] = str(e)
                self.last_run["error_stage"] = "build_workflow_ir"
                self.logger.exception("Stage 3: WorkflowIR build failed")
                raise
            
            return workflow_ir
        except Exception as exc:
            if "error" not in self.last_run or not self.last_run["error"]:
                self.last_run["error"] = str(exc)
                self.last_run["error_stage"] = "unknown"
            self.logger.exception("Task planning failed")
            raise

    def get_last_run(self) -> Dict[str, Any]:
        return self.last_run


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s - %(message)s",
    )
    planner = SubtaskPlanner()
    task = "设计一个在线书店的系统架构"
    workflow_ir = planner.plan(task)
    print(workflow_ir.model_dump_json(indent=2, ensure_ascii=False))
