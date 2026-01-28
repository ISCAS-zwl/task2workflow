"""测试多输入截断问题"""
import json
from node.utils import truncate_node_output

def test_multiple_inputs_truncation():
    """
    模拟一个LLM节点有多个输入的场景：
    - input1: 来自工具A的输出（5000字符）
    - input2: 来自工具B的输出（5000字符）
    - input3: 来自工具C的输出（5000字符）

    如果直接拼接后截断，可能会丢失 input2 和 input3
    """
    print("=" * 60)
    print("测试场景：LLM节点有3个输入，每个5000字符")
    print("=" * 60)

    # 模拟3个工具的输出
    input1 = "A" * 5000  # 工具A的输出
    input2 = "B" * 5000  # 工具B的输出
    input3 = "C" * 5000  # 工具C的输出

    # 场景1: 简单拼接后截断（当前可能的做法）
    print("\n场景1: 简单拼接后截断（max_length=8000）")
    combined = f"Input1: {input1}\nInput2: {input2}\nInput3: {input3}"
    print(f"拼接后总长度: {len(combined)} 字符")

    truncated = truncate_node_output(combined, max_length=8000)
    print(f"截断后长度: {len(truncated)} 字符")

    # 检查哪些输入被保留
    has_input1 = "A" * 100 in truncated
    has_input2 = "B" * 100 in truncated
    has_input3 = "C" * 100 in truncated

    print(f"Input1 是否保留: {has_input1}")
    print(f"Input2 是否保留: {has_input2}")
    print(f"Input3 是否保留: {has_input3}")

    if not has_input2 or not has_input3:
        print("\n[WARNING] 问题：Input2 和/或 Input3 被完全丢失！")

    # 场景2: 字典形式的多输入
    print("\n" + "=" * 60)
    print("场景2: 字典形式的多输入")
    print("=" * 60)

    multi_input = {
        "context1": input1,
        "context2": input2,
        "context3": input3,
    }

    print(f"原始字典大小: {len(json.dumps(multi_input, ensure_ascii=False))} 字符")

    truncated_dict = truncate_node_output(multi_input, max_length=8000)
    print(f"截断后类型: {type(truncated_dict)}")

    if isinstance(truncated_dict, dict):
        print(f"截断后字典大小: {len(json.dumps(truncated_dict, ensure_ascii=False))} 字符")
        print(f"保留的键: {list(truncated_dict.keys())}")

        # 检查每个字段的长度
        for key, value in truncated_dict.items():
            if isinstance(value, str):
                print(f"  {key}: {len(value)} 字符")
    else:
        print(f"截断后长度: {len(truncated_dict)} 字符")

    # 场景3: 推荐的解决方案 - 均匀截断
    print("\n" + "=" * 60)
    print("场景3: 推荐方案 - 均匀截断每个输入")
    print("=" * 60)

    max_total = 8000
    num_inputs = 3
    max_per_input = max_total // num_inputs

    print(f"总限制: {max_total} 字符")
    print(f"每个输入限制: {max_per_input} 字符")

    truncated_inputs = {
        "context1": input1[:max_per_input] + "...[截断]",
        "context2": input2[:max_per_input] + "...[截断]",
        "context3": input3[:max_per_input] + "...[截断]",
    }

    result_size = len(json.dumps(truncated_inputs, ensure_ascii=False))
    print(f"结果大小: {result_size} 字符")
    print(f"所有输入都被保留: [SUCCESS]")

    for key, value in truncated_inputs.items():
        print(f"  {key}: {len(value)} 字符")

if __name__ == "__main__":
    test_multiple_inputs_truncation()
