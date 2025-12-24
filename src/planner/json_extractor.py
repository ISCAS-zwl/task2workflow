import json
import logging
import re
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class JsonExtractor:
    
    def __init__(self, max_fix_attempts: int = 3):
        self.max_fix_attempts = max_fix_attempts
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def extract(self, content: str) -> str:
        stripped = content.strip()
        if not stripped:
            raise ValueError("LLM 输出为空")
        
        cleaned = self._remove_think_tags(stripped)
        if not cleaned:
            cleaned = stripped

        if self._try_parse(cleaned):
            return cleaned

        from_code_block = self._extract_from_code_block(cleaned)
        if from_code_block:
            return from_code_block

        from_brackets = self._extract_by_bracket_matching(cleaned)
        if from_brackets:
            return from_brackets

        raise ValueError("未能从 LLM 输出中提取 JSON")

    def _remove_think_tags(self, content: str) -> str:
        cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        return cleaned.strip()

    def _try_parse(self, content: str) -> bool:
        try:
            json.loads(content)
            return True
        except Exception:
            return False

    def _extract_from_code_block(self, content: str) -> Optional[str]:
        code_blocks = re.findall(r"```(?:json)?\s*(.*?)```", content, flags=re.IGNORECASE | re.DOTALL)
        for block in code_blocks:
            candidate = block.strip()
            if candidate and self._try_parse(candidate):
                return candidate
        return None

    def _extract_by_bracket_matching(self, content: str) -> Optional[str]:
        closing_map = {"{": "}", "[": "]"}
        opening_chars = set(closing_map.keys())
        closing_chars = set(closing_map.values())

        start_idx = None
        stack: List[str] = []
        in_string = False
        escape = False
        idx = 0
        length = len(content)

        while idx < length:
            ch = content[idx]
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
                candidate = content[start_idx : idx + 1]
                if self._try_parse(candidate):
                    return candidate.strip()
                idx = start_idx + 1
                start_idx = None
                stack = []
                in_string = False
                escape = False
                continue

            idx += 1

        return None

    def validate_workflow_structure(self, parsed: Any) -> None:
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

    def extract_and_validate(self, content: str) -> Dict[str, Any]:
        json_str = self.extract(content)
        parsed = json.loads(json_str)
        self.validate_workflow_structure(parsed)
        return parsed
