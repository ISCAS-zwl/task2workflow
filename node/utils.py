import json
from typing import Any, Optional


TRUNCATED_SUFFIX = "\n... [输出已截断，原始长度: {original_length} 字符，显示前 {max_length} 字符] ..."
INPUT_TRUNCATED_SUFFIX = "\n... [input truncated]"


def truncate_output(output: Any, max_length: Optional[int] = 8000) -> Any:
    if not max_length:
        return output
    
    if isinstance(output, str):
        output_str = output
    elif isinstance(output, (dict, list)):
        output_str = json.dumps(output, ensure_ascii=False)
    else:
        output_str = str(output)
    
    if len(output_str) <= max_length:
        return output
    
    original_length = len(output_str)
    truncated_str = output_str[:max_length] + TRUNCATED_SUFFIX.format(
        original_length=original_length,
        max_length=max_length
    )
    
    if isinstance(output, str):
        return truncated_str
    
    return {
        "_truncated": True,
        "_original_type": type(output).__name__,
        "_original_length": original_length,
        "_preview": truncated_str
    }
