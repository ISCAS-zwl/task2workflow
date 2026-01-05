import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from src.config import get_config

INPUT_TRUNCATED_SUFFIX = "\n... [input truncated]"
logger = logging.getLogger(__name__)


class ParamGuard:
    def __init__(self, tool_schemas: Optional[Dict[str, Any]] = None):
        config = get_config()
        self.llm = ChatOpenAI(
            api_key=config.guard_key,
            base_url=config.guard_url,
            model=config.guard_model,
            timeout=config.guard_timeout,
        )
        self.system_prompt = config.guard_system_prompt
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

    @staticmethod
    def truncate_prompt(prompt: str) -> str:
        max_len = os.getenv("GUARD_INPUT_MAX_CHARS")
        if not max_len:
            return prompt
        try:
            limit = int(max_len)
        except ValueError:
            return prompt
        if limit <= 0 or len(prompt) <= limit:
            return prompt
        return prompt[:limit] + INPUT_TRUNCATED_SUFFIX


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
            f'''请根据下游工具的输入 schema 生成一份合规的参数 JSON（仅输出 JSON文件，不要解释，也不要带有其他字符如json等）。\n"
            # Goals
            1. **精准提取**：从上游节点的冗长输出中定位核心关键信息（数字、时间、地点、名称）。
            2. **数据降噪**：彻底清除文本干扰。在生成数学表达式或数值字段时，必须剔除所有单位、货币符号（$、¥）、千分位逗号（,）以及描述性标签。
            3. **格式对齐**：严格遵守下游工具定义的字段名称、数据类型（Number, String, Boolean）和结构。

            # Rules (必须严格遵守)
            - **计算逻辑**：如果目标工具是 calculate，`expression` 字段内必须仅包含：数字、小数点、运算符（+ - * / % ^）和标准函数（如 round, abs）。**严禁出现任何自然语言单词或冒号**（如 Symbol: BTC 必须简化为数字）。
            - **时间格式**：除非另有说明，日期和时间应统一转换为 ISO 8601 格式（YYYY-MM-DD HH:mm:ss）。
            - **地理位置**：提取具体的地点名或坐标，剔除“在...附近”、“大概位于”等修饰语。
            - **禁止废话**：你的输出必须是一个纯净的 JSON 字符串，不得包含任何开场白（如 "好的，为您整形如下"）或解释说明。

            # Processing Steps
            1. **分析 Schema**：查看下游工具需要的字段 key 和类型。
            2. **扫描上游**：从上游输出中检索对应的 value。
            3. **清洗数据**：
            - 示例：将 "87,212.67 USD" 清洗为 "87212.67"。
            - 示例：将 "2025年12月30日" 清洗为 "2025-12-30"。
            4. **验证组装**：构建 JSON，确保不缺失必填项。

            # Example
            **Input (Upstream Output):** "当前比特币价格为 $87,212.67，以太坊价格为 2,941.58 USD。请计算两者的比例。"
            **Target Schema:** {{"expression": {{"type": "string"}}}}
            **Output:** {{"expression": "87212.67 / 2941.58"}}
            下游工具: {tool_name or 'unknown'}\n"
            f"Schema:\n{schema_str}\n"
            f"上游输出（可用作参考上下文）:\n{upstream_str}\n"
            f"原始入参模板填充结果:\n{candidate_str}\n"
            "请输出满足 schema 的 JSON 对象，确保字段、类型、必填项正确，禁止返回额外说明。
            '''
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
            prompt = self.truncate_prompt(prompt)
            messages = []
            if self.system_prompt:
                messages.append(SystemMessage(content=self.system_prompt))
            messages.append(HumanMessage(content=prompt))
            response = self.llm.invoke(messages)
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
