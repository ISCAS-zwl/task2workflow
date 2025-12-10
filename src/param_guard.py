import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


class ParamGuard:
    def __init__(self, tool_schemas: Optional[Dict[str, Any]] = None):
        
        self.llm = ChatOpenAI(
            api_key=os.getenv("GUARD_KEY"),
            base_url=os.getenv("GUARD_URL"),
            model=os.getenv("GUARD_MODEL"),
            timeout=60,
        )
        self.tool_schemas = tool_schemas or {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @staticmethod
    def strip_think_tags(value: Any) -> Any:
        if isinstance(value, str):
            # 移除 <think> 标签
            cleaned = re.sub(r"<think>.*?</think>", "", value, flags=re.DOTALL)
            cleaned = cleaned.strip()
            
            # 移除 markdown 代码块标记
            if cleaned.startswith("```"):
                # 匹配 ```json 或 ``` 开头
                cleaned = re.sub(r"^```(?:json|python|yaml)?\s*\n?", "", cleaned)
                # 移除结尾的 ```
                cleaned = re.sub(r"\n?```\s*$", "", cleaned)
                cleaned = cleaned.strip()
            
            return cleaned
        return value

    @staticmethod
    def coerce_json_value(value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return {}
            try:
                return json.loads(stripped)
            except (json.JSONDecodeError, TypeError):
                return value
        return value

    def get_input_schema(self, tool_name: Optional[str], mcp_manager=None) -> Dict[str, Any]:
        if not tool_name:
            return {}
        if mcp_manager and tool_name in mcp_manager.tool_index:
            return mcp_manager.tool_index[tool_name].input_schema or {}
        return (self.tool_schemas.get(tool_name) or {}).get("input_schema") or {}

    def safe_load_json(self, content: str) -> Any:
        try:
            return json.loads(content)
        except Exception:
            return None

    def build_guard_prompt(
        self,
        tool_name: Optional[str],
        schema: Dict[str, Any],
        candidate: Any,
        upstream_output: Any,
    ) -> str:
        schema_str = json.dumps(schema, ensure_ascii=False, indent=2) if schema else "{}"
        candidate_str = json.dumps(candidate, ensure_ascii=False, indent=2) if isinstance(candidate, (dict, list)) else str(candidate)
        upstream_str = json.dumps(upstream_output, ensure_ascii=False, indent=2) if isinstance(upstream_output, (dict, list)) else str(upstream_output)

        return (
            "请根据下游工具的输入 schema 生成一份合规的参数 JSON（仅输出 JSON文件，不要解释，也不要带有其他字符如json等）。\n"
            f"下游工具: {tool_name or 'unknown'}\n"
            f"Schema:\n{schema_str}\n"
            f"上游输出（可用作参考上下文）:\n{upstream_str}\n"
            f"原始入参模板填充结果:\n{candidate_str}\n"
            "请输出满足 schema 的 JSON 对象，确保字段、类型、必填项正确，禁止返回额外说明。"
        )

    def validate_and_repair(
        self,
        candidate_input: Any,
        schema: Dict[str, Any],
        upstream_output: Any,
        target_tool: Optional[str],
    ) -> Dict[str, Any]:
        """
        直接使用 LLM 对参数进行整形
        返回格式: {"mode": str, "output": dict, "raw_response": str, "error": str (可选)}
        """
        candidate_input = self.coerce_json_value(candidate_input)
        
        self.logger.info(f"使用 LLM 整形参数: {target_tool}, 模型: {self.llm.model_name}")
        
        fixed_raw = None
        try:
            # 直接调用 LLM 进行参数整形
            prompt = self.build_guard_prompt(target_tool, schema, candidate_input, upstream_output)
            response = self.llm.invoke([HumanMessage(content=prompt)])
            fixed_raw = self.strip_think_tags(response.content)
            fixed_input = self.safe_load_json(fixed_raw)
            
            if fixed_input is None:
                error_msg = f"LLM 整形后的参数无法解析为 JSON"
                error_detail = {"error": error_msg, "raw_response": fixed_raw}
                raise ValueError(error_msg)

            if not isinstance(fixed_input, dict):
                error_msg = f"参数整形节点输出必须为字典，当前类型: {type(fixed_input).__name__}"
                error_detail = {"error": error_msg, "raw_response": fixed_raw, "parsed_type": type(fixed_input).__name__}
                raise ValueError(error_msg)

            self.logger.info(f"参数整形成功: {target_tool}")
            return {"mode": "llm_adjusted", "output": fixed_input, "raw_response": fixed_raw}
        except Exception as e:
            # 确保异常对象携带原始响应
            if not hasattr(e, 'guard_metadata'):
                e.guard_metadata = {"raw_response": fixed_raw}
            raise
