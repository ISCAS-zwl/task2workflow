import json
import os
from typing import Any, Optional


TRUNCATED_SUFFIX = "\n... [输出已截断，原始长度: {original_length} 字符，显示前 {max_length} 字符] ..."
INPUT_TRUNCATED_SUFFIX = "\n... [input truncated]"


def truncate_output(output: Any, max_length: Optional[int] = 8000) -> Any:
    """
    截断输出用于显示（trace）。
    这个函数只用于显示，不影响实际存储的数据。
    """
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


def truncate_node_output(output: Any, max_length: Optional[int] = None) -> Any:
    """
    智能截断节点输出，用于存储到 state["outputs"]。
    这个函数会实际截断数据，防止过长内容传递给下游节点。

    Args:
        output: 节点输出数据
        max_length: 最大字符长度，如果为 None 则从环境变量读取

    Returns:
        截断后的输出
    """
    if max_length is None:
        max_length_str = os.getenv("NODE_OUTPUT_MAX_CHARS")
        if max_length_str:
            try:
                max_length = int(max_length_str)
            except ValueError:
                max_length = 15000
        else:
            max_length = 15000

    if max_length <= 0:
        return output

    # 字符串类型：直接截断
    if isinstance(output, str):
        if len(output) <= max_length:
            return output
        return output[:max_length] + f"\n... [已截断，原始长度: {len(output)} 字符]"

    # 字典类型：智能截断，确保所有字段都被保留
    if isinstance(output, dict):
        output_str = json.dumps(output, ensure_ascii=False)
        if len(output_str) <= max_length:
            return output

        # 策略1: 尝试均匀截断所有字段，确保每个字段都被保留
        num_fields = len(output)
        if num_fields > 0:
            # 预留空间给 JSON 结构（键名、引号、逗号等）
            overhead_per_field = 50  # 估算每个字段的 JSON 开销
            available_space = max_length - (num_fields * overhead_per_field)

            if available_space > 0:
                max_per_field = available_space // num_fields

                # 如果每个字段至少能分配到 100 字符，使用均匀截断策略
                if max_per_field >= 100:
                    truncated_dict = {}
                    for key, value in output.items():
                        if isinstance(value, str):
                            if len(value) > max_per_field:
                                truncated_dict[key] = value[:max_per_field] + "...[已截断]"
                            else:
                                truncated_dict[key] = value
                        elif isinstance(value, (dict, list)):
                            value_str = json.dumps(value, ensure_ascii=False)
                            if len(value_str) > max_per_field:
                                truncated_dict[key] = value_str[:max_per_field] + "...[已截断]"
                            else:
                                truncated_dict[key] = value
                        else:
                            truncated_dict[key] = value

                    # 验证截断后的大小
                    truncated_str = json.dumps(truncated_dict, ensure_ascii=False)
                    if len(truncated_str) <= max_length * 1.1:  # 允许 10% 的误差
                        return truncated_dict

        # 策略2: 如果均匀截断失败，尝试保留结构，截断长字段
        truncated_dict = {}
        for key, value in output.items():
            if isinstance(value, str) and len(value) > max_length // 2:
                truncated_dict[key] = value[:max_length // 2] + f"\n... [字段已截断]"
            else:
                truncated_dict[key] = value

        # 检查截断后的大小
        truncated_str = json.dumps(truncated_dict, ensure_ascii=False)
        if len(truncated_str) <= max_length:
            return truncated_dict

        # 策略3: 如果还是太长，返回字符串形式的截断
        return output_str[:max_length] + f"\n... [已截断，原始长度: {len(output_str)} 字符]"

    # 列表类型：限制元素数量
    if isinstance(output, list):
        output_str = json.dumps(output, ensure_ascii=False)
        if len(output_str) <= max_length:
            return output

        # 尝试保留前面的元素
        truncated_list = []
        current_length = 2  # [] 的长度

        for item in output:
            item_str = json.dumps(item, ensure_ascii=False)
            if current_length + len(item_str) + 1 > max_length:  # +1 for comma
                break
            truncated_list.append(item)
            current_length += len(item_str) + 1

        if truncated_list:
            return truncated_list + [f"... [已截断，原始长度: {len(output)} 个元素]"]

        # 如果第一个元素就太长，返回字符串形式的截断
        return output_str[:max_length] + f"\n... [已截断，原始长度: {len(output_str)} 字符]"

    # 其他类型：转字符串后截断
    output_str = str(output)
    if len(output_str) <= max_length:
        return output
    return output_str[:max_length] + f"\n... [已截断，原始长度: {len(output_str)} 字符]"

