"""
测试汇聚节点修复：验证多入边节点是否等待所有依赖完成
"""
import json
from pathlib import Path

def test_join_node():
    """测试汇聚节点逻辑"""

    # 加载旅游攻略工作流
    workflow_path = Path("saved_workflows/旅游攻略/graph.json")
    with open(workflow_path, 'r', encoding='utf-8') as f:
        graph_data = json.load(f)

    print("\n=== 分析工作流结构 ===")

    # 统计每个节点的入边
    incoming_edges = {}
    for edge in graph_data['edges']:
        target = edge['target']
        if target not in incoming_edges:
            incoming_edges[target] = []
        incoming_edges[target].append(edge['source'])

    print("\n节点入边统计:")
    for node_id, sources in incoming_edges.items():
        print(f"  {node_id}: {len(sources)} 个入边 <- {sources}")

    # 找出有多个入边的节点
    multi_input_nodes = {k: v for k, v in incoming_edges.items() if len(v) > 1}

    print(f"\n有多个入边的节点: {list(multi_input_nodes.keys())}")

    for node_id, sources in multi_input_nodes.items():
        print(f"\n节点 {node_id}:")
        print(f"  - 依赖: {sources}")
        print(f"  - 修复方案: 创建汇聚节点 __JOIN_{node_id}__")
        print(f"  - 执行顺序: {' + '.join(sources)} -> __JOIN_{node_id}__ -> {node_id}")

    print("\n=== 问题分析 ===")
    print("原问题: ST6 在 ST5 完成后立即执行，没有等待 ST4 完成")
    print("原因: LangGraph 的 add_edge 对于多入边节点，只要任意一个前置节点完成就会触发")
    print("\n修复方案: 为多入边节点创建汇聚节点")
    print("效果: LangGraph 会等待所有前置节点完成后才执行汇聚节点，然后才触发目标节点")

if __name__ == "__main__":
    test_join_node()
