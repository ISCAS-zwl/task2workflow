"""测试固定工具功能"""
import os
import logging
from src.config import Config, set_config
from src.tool_retriever import ToolRetriever
import json

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s - %(message)s",
)

def load_tools():
    """加载工具定义"""
    tools_path = "tools/generated_tools.json"
    with open(tools_path, "r", encoding="utf-8") as f:
        return json.load(f)

def test_pinned_tools():
    """测试固定工具功能"""
    print("=" * 60)
    print("测试固定工具功能")
    print("=" * 60)

    # 设置环境变量
    os.environ["PINNED_TOOLS"] = "tavily-search"

    # 重新加载配置
    config = Config()
    set_config(config)

    print(f"\n配置的固定工具: {config.pinned_tools}")

    # 加载工具
    tools = load_tools()
    print(f"总工具数: {len(tools)}")

    # 创建检索器
    retriever = ToolRetriever(tools)

    # 测试1: 查询一个不太相关的任务，看 tavily-search 是否被包含
    print("\n" + "=" * 60)
    print("测试1: 查询 '计算两个数的和'")
    print("=" * 60)
    task1 = "计算两个数的和"
    result1 = retriever.retrieve_subset(task1, top_k=5)

    if result1:
        print(f"检索到 {len(result1)} 个工具:")
        for tool_name in result1.keys():
            print(f"  - {tool_name}")

        if "tavily-search" in result1:
            print("\n[SUCCESS] tavily-search 已被固定包含（即使查询不相关）")
        else:
            print("\n[FAILED] tavily-search 未被包含（可能是bug）")

    # 测试2: 查询一个相关的任务
    print("\n" + "=" * 60)
    print("测试2: 查询 '搜索最新的AI新闻'")
    print("=" * 60)
    task2 = "搜索最新的AI新闻"
    result2 = retriever.retrieve_subset(task2, top_k=5)

    if result2:
        print(f"检索到 {len(result2)} 个工具:")
        for tool_name in result2.keys():
            print(f"  - {tool_name}")

        if "tavily-search" in result2:
            print("\n[SUCCESS] tavily-search 已被包含")
        else:
            print("\n[FAILED] tavily-search 未被包含")

    # 测试3: 测试多个固定工具
    print("\n" + "=" * 60)
    print("测试3: 配置多个固定工具")
    print("=" * 60)
    os.environ["PINNED_TOOLS"] = "tavily-search,get_weather"
    config = Config()
    set_config(config)
    print(f"配置的固定工具: {config.pinned_tools}")

    retriever = ToolRetriever(tools)
    task3 = "计算圆的面积"
    result3 = retriever.retrieve_subset(task3, top_k=5)

    if result3:
        print(f"检索到 {len(result3)} 个工具:")
        for tool_name in result3.keys():
            print(f"  - {tool_name}")

        pinned_count = sum(1 for t in config.pinned_tools if t in result3)
        print(f"\n固定工具包含数: {pinned_count}/{len(config.pinned_tools)}")

if __name__ == "__main__":
    test_pinned_tools()
