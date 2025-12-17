import copy
import json
import logging
import os
import re
from typing import Optional, List, Dict, Any, Literal, Union

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

import pathlib

PROMPT_DIR = pathlib.Path(__file__).parent.parent /"prompt" / "plan_prompt.txt"
TOOLS_DIR = pathlib.Path(__file__).parent.parent / "tools"
TOOLS_GENERATED_PATH = TOOLS_DIR / "generated_tools.json"

with PROMPT_DIR.open('r',encoding="utf-8") as f:
    prompt_raw = f.read()


def _load_tools_definition() -> Dict[str, Any]:
    tools_data: Dict[str, Any] = {}
    for path in [TOOLS_GENERATED_PATH]:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, dict):
                    tools_data.update(content)
        except Exception as exc:
            logger.warning("读取工具文件 %s 失败：%s", path, exc)
    return tools_data

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

    source: Optional[str] = Field(default=None, description="前置节点，没有则为 null")
    target: Optional[str] = Field(default=None, description="后置节点，没有则为 null")

    output: Optional[str] = Field(default=None, description="子任务预期输出")
    input: Optional[Dict[str, Any]] = Field(default=None, description="输入定义")
    
    llm_config: Optional[LLMConfig] = Field(default=None, description="LLM节点和param_guard节点的自定义模型配置")


class Edge(BaseModel):
    source: str
    target: str


class WorkflowIR(BaseModel):
    nodes: List[Subtask]
    edges: List[Edge]

class SubtaskPlanner:
    """
    三阶段规划器：
    1) 直接输出结构化 JSON
    2) 自动修复 JSON
    3) 生成 WorkflowIR
    """

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("PLANNER_MODEL", "gpt-4o")
        self.client = OpenAI(
            api_key=os.getenv("PLANNER_KEY"),
            base_url=os.getenv("PLANNER_URL"),
        )
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.last_run: Dict[str, Any] = {}
        # è½½å…¥å·¥å…·å®šä¹‰ä¾ä¸‹æ¸¸ schema æŸ¥è¯¢
        self.tools_definition = _load_tools_definition()


    def _generate_workflow_json(self, task: str) -> str:
        """直接向 LLM 请求生成符合 Schema 的 JSON 工作流。"""
        tools_content = _load_tools_definition()
        tools = json.dumps(tools_content, ensure_ascii=False)

        prompt = prompt_raw.format(tools=tools, task=task)

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一名workflow 规划专家，擅长将复杂任务拆解为子任务并生成结构化 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
                extra_body={
        "chat_template_kwargs": {"enable_thinking": False}
    }
        )
        
        # 记录 LLM 响应元信息
        content = resp.choices[0].message.content if resp.choices else ""
        if content:
            content = content.strip()
        
        self.last_run["llm_response_metadata"] = {
            "model": self.model,
            "finish_reason": resp.choices[0].finish_reason if resp.choices else None,
            "content_length": len(content),
            "has_content": bool(content),
            "prompt_tokens": resp.usage.prompt_tokens if resp.usage else None,
            "completion_tokens": resp.usage.completion_tokens if resp.usage else None,
            "total_tokens": resp.usage.total_tokens if resp.usage else None,
        }
        
        if not content:
            self.logger.error("阶段1：LLM 返回空内容")
            return "{}"  # 返回空 JSON，让后续验证捕获
        
        try:
            return self._extract_json_block(content)
        except ValueError:
            self.logger.warning("阶段1：未能直接提取合法 JSON，进入阶段2尝试自动修复")
            return content


    def _extract_json_block(self, content: str) -> str:
        """从 LLM 输出 text 中提取 JSON 字符串。"""

        stripped = content.strip()
        if not stripped:
            raise ValueError("LLM 输出为空")
        
        # 先移除 <think> 标签及其内容（包括未闭合的）
        cleaned_content = re.sub(r"<think>.*?</think>", "", stripped, flags=re.DOTALL | re.IGNORECASE)
        cleaned_content = re.sub(r"<think>.*", "", cleaned_content, flags=re.DOTALL | re.IGNORECASE)
        cleaned_content = cleaned_content.strip()
        
        # 如果清理后为空，使用原内容
        if not cleaned_content:
            cleaned_content = stripped

        try:
            json.loads(cleaned_content)
            return cleaned_content
        except Exception:
            pass

        code_blocks = re.findall(r"```(?:json)?\s*(.*?)```", cleaned_content, flags=re.IGNORECASE | re.DOTALL)
        for block in code_blocks:
            candidate = block.strip()
            if not candidate:
                continue
            try:
                json.loads(candidate)
                return candidate
            except Exception:
                continue

        closing_map = {"{": "}", "[": "]"}
        opening_chars = set(closing_map.keys())
        closing_chars = set(closing_map.values())

        start_idx = None
        stack: List[str] = []
        in_string = False
        escape = False
        idx = 0
        length = len(cleaned_content)

        while idx < length:
            ch = cleaned_content[idx]
            if start_idx is None:
                if ch in opening_chars:
                    start_idx = idx
                    stack = [closing_map[ch]]
                    in_string = False
                    escape = False
                idx += 1
                continue

            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch in opening_chars:
                    stack.append(closing_map[ch])
                elif ch in closing_chars:
                    if not stack or ch != stack.pop():
                        start_idx = None
                        stack = []
                        in_string = False
                        escape = False
                        idx += 1
                        continue

            if start_idx is not None and not stack:
                candidate = cleaned_content[start_idx : idx + 1]
                try:
                    json.loads(candidate)
                    return candidate.strip()
                except Exception:
                    idx = start_idx + 1
                    start_idx = None
                    stack = []
                    in_string = False
                    escape = False
                    continue

            idx += 1

        raise ValueError("未能从 LLM 输出中提取 JSON")



    def _auto_fix_json(self, raw_json: str) -> dict:
        """
        自动修复 LLM 输出的 JSON，直到可解析。
        最多尝试 3 次。
        """

        for attempt in range(1, 4):
            self.logger.info("阶段2：第 %s 次尝试解析/修复 JSON", attempt)
            try:
                candidate = self._extract_json_block(raw_json)
                parsed = json.loads(candidate)
                
                # 验证必需字段
                if not isinstance(parsed, dict):
                    raise ValueError(f"JSON 必须是对象类型，当前类型: {type(parsed).__name__}")
                
                if "nodes" not in parsed:
                    raise ValueError("JSON 缺少必需字段 'nodes'")
                
                if "edges" not in parsed:
                    raise ValueError("JSON 缺少必需字段 'edges'")
                
                if not isinstance(parsed["nodes"], list):
                    raise ValueError(f"'nodes' 必须是数组类型，当前类型: {type(parsed['nodes']).__name__}")
                
                if not isinstance(parsed["edges"], list):
                    raise ValueError(f"'edges' 必须是数组类型，当前类型: {type(parsed['edges']).__name__}")
                
                if len(parsed["nodes"]) == 0:
                    raise ValueError("'nodes' 数组不能为空")
                
                self.last_run["fix_attempts"].append({
                    "attempt": attempt,
                    "status": "success",
                    "input": raw_json[:500],
                    "output": candidate[:500],
                    "parsed_keys": list(parsed.keys()) if isinstance(parsed, dict) else None,
                    "nodes_count": len(parsed.get("nodes", [])),
                    "edges_count": len(parsed.get("edges", [])),
                })
                
                self.logger.info("阶段2：JSON 修复成功，nodes: %d, edges: %d", len(parsed["nodes"]), len(parsed["edges"]))
                return parsed
            except Exception as e:
                self.last_run["fix_attempts"].append({
                    "attempt": attempt,
                    "status": "failed",
                    "input": raw_json[:500],
                    "error": str(e),
                })
                
                # 重用原始 prompt
                tools_content = _load_tools_definition()
                tools = json.dumps(tools_content, ensure_ascii=False)
                original_prompt = prompt_raw.format(tools=tools, task=self.last_run.get('task', ''))
                
                fix_prompt = f"""
{original_prompt}

---

你之前生成的内容不符合要求：

```
{raw_json[:1500]}
```

请重新生成完整的工作流 JSON。注意：
1. 不要输出 <think> 标签或任何解释
2. 只输出纯 JSON
"""
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": fix_prompt}],
                        extra_body={
        "chat_template_kwargs": {"enable_thinking": False}
    }
                )
                raw_json = resp.choices[0].message.content.strip()
                self.logger.info("阶段2：已根据模型返回内容尝试修复 JSON")

        self.logger.error("阶段2：三次修复失败，无法生成合法 JSON")
        self.last_run["error_stage"] = "auto_fix_json"
        raise ValueError("三次修复失败：无法生成合法 JSON")

    def _build_workflow_ir(self, fixed_json: dict) -> WorkflowIR:
        try:
            workflow_ir = WorkflowIR(
                nodes=[Subtask(**n) for n in fixed_json["nodes"]],
                edges=fixed_json["edges"],
            )
            workflow_ir = self._inject_param_guard_nodes(workflow_ir)
            self.logger.info("阶段3：WorkflowIR 校验完成")
            
            from src.graph_validator import validate_workflow_ir
            tools_data = _load_tools_definition()
            available_tools = set(tools_data.keys())
            
            validation_result = validate_workflow_ir(workflow_ir, available_tools)
            if not validation_result.is_valid:
                self.logger.error(f"阶段3：图结构验证失败\n{validation_result}")
                raise ValueError(f"图结构验证失败：{validation_result}")
            
            if validation_result.warnings:
                self.logger.warning(f"阶段3：图结构验证警告\n{validation_result}")
            
            return workflow_ir
        except ValidationError as e:
            self.logger.error("阶段3：Pydantic 校验失败")
            raise ValueError(f"Pydantic 校验失败：{e}")

    def _inject_param_guard_nodes(self, workflow_ir: WorkflowIR) -> WorkflowIR:
        """
        在相邻工具节点之间插入参数整形/校验节点：
        - 上游输出 -> 守护节点 -> 下游工具
        - 守护节点输出合规入参，下游工具通过 __from_guard__ 直接消费
        """
        node_data_map: Dict[str, Dict[str, Any]] = {
            node.id: node.model_dump() for node in workflow_ir.nodes
        }
        edges_data: List[Dict[str, str]] = [edge.model_dump() for edge in workflow_ir.edges]

        tools_definition = self.tools_definition or _load_tools_definition()

        # 计算新的节点编号起点
        def _extract_idx(node_id: str) -> int:
            match = re.match(r"ST(\d+)", node_id)
            return int(match.group(1)) if match else 0
        
        def _extract_guard_idx(node_id: str) -> int:
            match = re.match(r"GUARD(\d+)", node_id)
            return int(match.group(1)) if match else 0

        next_idx = max((_extract_idx(nid) for nid in node_data_map.keys()), default=0) + 1
        next_guard_idx = max((_extract_guard_idx(nid) for nid in node_data_map.keys()), default=0) + 1

        new_edges: List[Dict[str, str]] = []
        inserted_count = 0
        
        # 保存每个节点的原始 input，避免被多次修改
        original_inputs: Dict[str, Dict[str, Any]] = {
            node_id: copy.deepcopy(node_data.get("input") or {})
            for node_id, node_data in node_data_map.items()
        }

        def _needs_param_guard(target_node_data: Dict[str, Any]) -> bool:
            """
            检查目标节点是否需要参数整形节点
            
            判断标准：
            1. 目标节点必须是 tool 类型
            2. input 中包含对上游节点输出的引用（{STx.output}）
            
            为什么需要 guard：
            - 上游工具的输出可能是复杂对象（如 {"city": {"code": "SHH"}}）
            - 下游工具期望的是特定字段（如 "SHH"）
            - guard 节点负责提取正确的字段并整形参数
            """
            if target_node_data.get("executor") != "tool":
                return False
            
            target_input = target_node_data.get("input") or {}
            
            # 检查 input 中是否包含引用语法（如 {ST1.output}）
            # 使用精确正则：完整匹配 {STx.output}
            input_str = json.dumps(target_input, ensure_ascii=False)
            if re.search(r"\{ST\d+\.output\}", input_str):
                return True
            
            return False

        # ===== 阶段 1：收集需要插入 guard 的边 =====
        target_guards_map: Dict[str, List[Dict[str, Any]]] = {}  # {target_id: [guard_info]}
        
        for edge in edges_data:
            source_id = edge["source"]
            target_id = edge["target"]

            source_node = node_data_map.get(source_id)
            target_node = node_data_map.get(target_id)

            # 检查是否需要插入 guard（使用原始 input 判断）
            # 注意：不限制上游节点类型，只要目标节点需要参数整形就插入 guard
            if (
                source_node
                and target_node
                and _needs_param_guard(target_node)
            ):
                if target_id not in target_guards_map:
                    target_guards_map[target_id] = []
                
                target_guards_map[target_id].append({
                    "source_id": source_id,
                    "edge": edge
                })
            else:
                # 不需要 guard 的边直接保留
                new_edges.append(edge)

        # ===== 阶段 2：每个目标节点只创建一个 guard 节点 =====
        for target_id, guard_infos in target_guards_map.items():
            target_node = node_data_map[target_id]
            target_tool = target_node.get("tool_name")
            target_schema = (tools_definition.get(target_tool) or {}).get("input_schema") or {}
            target_input_template = copy.deepcopy(original_inputs.get(target_id, {}))
            
            # 收集所有上游节点 ID
            source_ids = [info["source_id"] for info in guard_infos]
            
            # 创建单个 guard 节点
            guard_id = f"GUARD{next_guard_idx}"
            next_guard_idx += 1
            inserted_count += 1
            
            # 确定 guard 的主要上游来源（用于 source 字段）
            # 优先选择提供关键参数的节点，如果有多个则选第一个
            primary_source = source_ids[0] if source_ids else None
            
            guard_node = Subtask(
                id=guard_id,
                name=f"参数整形: {target_tool or target_id}",
                description=f"校验并整形下游工具 {target_tool or target_id} 的入参",
                executor="param_guard",
                tool_name=target_tool,
                source=primary_source,
                target=target_id,
                output="整形后的下游工具入参",
                input={
                    "source_nodes": source_ids,  # 记录所有上游节点
                    "target_node": target_id,
                    "target_tool": target_tool,
                    "target_input_template": target_input_template,
                    "schema": target_schema,
                },
            )
            
            node_data_map[guard_id] = guard_node.model_dump()
            
            # 更新所有上游节点的 target 指针
            for source_id in source_ids:
                if node_data_map[source_id].get("target") == target_id:
                    node_data_map[source_id]["target"] = guard_id
            
            # 添加边：所有 source → guard，guard → target
            for source_id in source_ids:
                new_edges.append({"source": source_id, "target": guard_id})
            new_edges.append({"source": guard_id, "target": target_id})
            
            # 修改目标节点的 input 和 source
            node_data_map[target_id]["input"] = {"__from_guard__": guard_id}
            node_data_map[target_id]["source"] = guard_id

        if inserted_count:
            self.logger.info("已自动插入 %s 个参数整形节点", inserted_count)

        # 重新生成 WorkflowIR，按类型和编号排序
        def _sort_key(n):
            node_id = n.get("id", "")
            if node_id.startswith("GUARD"):
                return (1, _extract_guard_idx(node_id))  # guard 节点排后面
            else:
                return (0, _extract_idx(node_id))  # ST 节点排前面
        
        sorted_nodes = sorted(node_data_map.values(), key=_sort_key)
        return WorkflowIR(
            nodes=[Subtask(**n) for n in sorted_nodes],
            edges=new_edges,
        )



    def plan(self, task: str) -> WorkflowIR:
        """
        Task -> JSON -> AutoFix -> WorkflowIR
        """

        self.last_run = {
            "task": task,
            "plan_text": None,
            "raw_json": None,
            "fixed_json": None,
            "workflow_ir": None,
            "workflow_json_str": None,
            "error": None,
            "error_stage": None,
            "fix_attempts": [],
            "llm_response_metadata": None,
        }

        try:
            self.logger.info("阶段1：开始生成 JSON 方案，任务：%s", task)
            raw_json = self._generate_workflow_json(task)
            self.last_run["plan_text"] = "[直接生成 JSON，未产生自然语言计划]"
            self.last_run["raw_json"] = raw_json
            self.logger.info("阶段1：JSON 方案生成完成")

            try:
                fixed_json = self._auto_fix_json(raw_json)
                self.last_run["fixed_json"] = fixed_json
            except Exception as e:
                self.last_run["error"] = str(e)
                self.last_run["error_stage"] = "auto_fix_json"
                self.logger.exception("阶段2：JSON 修复失败")
                raise

            try:
                workflow_ir = self._build_workflow_ir(fixed_json)
                self.last_run["workflow_ir"] = workflow_ir
                workflow_json_str = workflow_ir.model_dump_json(indent=2, ensure_ascii=False)
                self.last_run["workflow_json_str"] = workflow_json_str
                self.logger.info("阶段3：WorkflowIR 生成完成")
            except Exception as e:
                self.last_run["error"] = str(e)
                self.last_run["error_stage"] = "build_workflow_ir"
                self.logger.exception("阶段3：WorkflowIR 构建失败")
                raise
            
            return workflow_ir
        except Exception as exc:
            if "error" not in self.last_run or not self.last_run["error"]:
                self.last_run["error"] = str(exc)
                self.last_run["error_stage"] = "unknown"
            self.logger.exception("任务规划失败")
            raise

    def get_last_run(self) -> Dict[str, Any]:
        """返回最近一次运行的阶段产物。"""
        return self.last_run




if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s - %(message)s",
    )
    planner = SubtaskPlanner()
    task = "设计一个在线书店的系统架构"
    workflow_ir = planner.plan(task)
    print(workflow_ir.json(indent=2, ensure_ascii=False))
