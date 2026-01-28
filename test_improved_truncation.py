"""测试改进后的多输入截断逻辑"""
import json
from node.utils import truncate_node_output

def test_improved_truncation():
    """测试改进后的截断逻辑是否能保留所有输入"""
    print("=" * 60)
    print("测试改进后的多输入截断逻辑")
    print("=" * 60)

    # 测试1: 3个大小相等的输入
    print("\n测试1: 3个大小相等的输入（每个5000字符）")
    print("-" * 60)

    multi_input = {
        "context1": "A" * 5000,
        "context2": "B" * 5000,
        "context3": "C" * 5000,
    }

    original_size = len(json.dumps(multi_input, ensure_ascii=False))
    print(f"原始大小: {original_size} 字符")

    truncated = truncate_node_output(multi_input, max_length=8000)

    if isinstance(truncated, dict):
        truncated_size = len(json.dumps(truncated, ensure_ascii=False))
        print(f"截断后大小: {truncated_size} 字符")
        print(f"保留的字段: {list(truncated.keys())}")

        # 检查每个字段
        all_preserved = True
        for key in ["context1", "context2", "context3"]:
            if key in truncated:
                value = truncated[key]
                if isinstance(value, str):
                    print(f"  {key}: {len(value)} 字符")
                    # 检查是否包含原始内容的一部分
                    if key == "context1" and "A" * 100 not in value:
                        all_preserved = False
                    elif key == "context2" and "B" * 100 not in value:
                        all_preserved = False
                    elif key == "context3" and "C" * 100 not in value:
                        all_preserved = False
            else:
                print(f"  {key}: [MISSING]")
                all_preserved = False

        if all_preserved:
            print("\n[SUCCESS] 所有输入都被保留！")
        else:
            print("\n[FAILED] 某些输入丢失或损坏")
    else:
        print(f"截断后类型: {type(truncated)}")
        print("[FAILED] 返回的不是字典类型")

    # 测试2: 不同大小的输入
    print("\n" + "=" * 60)
    print("测试2: 不同大小的输入")
    print("-" * 60)

    multi_input2 = {
        "short_context": "这是一个短文本",
        "medium_context": "M" * 2000,
        "long_context": "L" * 8000,
    }

    original_size2 = len(json.dumps(multi_input2, ensure_ascii=False))
    print(f"原始大小: {original_size2} 字符")

    truncated2 = truncate_node_output(multi_input2, max_length=8000)

    if isinstance(truncated2, dict):
        truncated_size2 = len(json.dumps(truncated2, ensure_ascii=False))
        print(f"截断后大小: {truncated_size2} 字符")
        print(f"保留的字段: {list(truncated2.keys())}")

        for key, value in truncated2.items():
            if isinstance(value, str):
                print(f"  {key}: {len(value)} 字符")

        if len(truncated2) == 3:
            print("\n[SUCCESS] 所有字段都被保留！")
        else:
            print(f"\n[FAILED] 只保留了 {len(truncated2)}/3 个字段")
    else:
        print(f"截断后类型: {type(truncated2)}")

    # 测试3: 大量小字段
    print("\n" + "=" * 60)
    print("测试3: 大量小字段（10个字段）")
    print("-" * 60)

    multi_input3 = {f"field_{i}": f"Content_{i}_" * 200 for i in range(10)}

    original_size3 = len(json.dumps(multi_input3, ensure_ascii=False))
    print(f"原始大小: {original_size3} 字符")

    truncated3 = truncate_node_output(multi_input3, max_length=8000)

    if isinstance(truncated3, dict):
        truncated_size3 = len(json.dumps(truncated3, ensure_ascii=False))
        print(f"截断后大小: {truncated_size3} 字符")
        print(f"保留的字段数: {len(truncated3)}/10")

        if len(truncated3) == 10:
            print("\n[SUCCESS] 所有10个字段都被保留！")
        else:
            print(f"\n[WARNING] 只保留了 {len(truncated3)}/10 个字段")
    else:
        print(f"截断后类型: {type(truncated3)}")

    # 测试4: 嵌套结构
    print("\n" + "=" * 60)
    print("测试4: 嵌套结构（字典和列表）")
    print("-" * 60)

    multi_input4 = {
        "text": "T" * 3000,
        "data": {"nested": "N" * 3000},
        "list": ["L" * 1000 for _ in range(3)],
    }

    original_size4 = len(json.dumps(multi_input4, ensure_ascii=False))
    print(f"原始大小: {original_size4} 字符")

    truncated4 = truncate_node_output(multi_input4, max_length=8000)

    if isinstance(truncated4, dict):
        truncated_size4 = len(json.dumps(truncated4, ensure_ascii=False))
        print(f"截断后大小: {truncated_size4} 字符")
        print(f"保留的字段: {list(truncated4.keys())}")

        if len(truncated4) == 3:
            print("\n[SUCCESS] 所有字段都被保留！")
        else:
            print(f"\n[FAILED] 只保留了 {len(truncated4)}/3 个字段")
    else:
        print(f"截断后类型: {type(truncated4)}")

if __name__ == "__main__":
    test_improved_truncation()
