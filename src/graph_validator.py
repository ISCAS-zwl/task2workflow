import json
import logging
import re
from typing import Dict, List, Set, Tuple, Any, Optional
from pydantic import ValidationError

# 假设这些类在 src.subtask_planner
# from src.subtask_planner import WorkflowIR, Subtask, Edge

logger = logging.getLogger(__name__)

class ValidationResult:
    def __init__(self):
        self.is_valid: bool = True
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def add_error(self, error: str):
        self.is_valid = False
        self.errors.append(error)
    
    def add_warning(self, warning: str):
        self.warnings.append(warning)
    
    def __bool__(self):
        return self.is_valid
    
    def __str__(self):
        result = []
        if self.errors:
            result.append(f"错误 ({len(self.errors)}):")
            for i, error in enumerate(self.errors, 1):
                result.append(f"  {i}. {error}")
        if self.warnings:
            result.append(f"警告 ({len(self.warnings)}):")
            for i, warning in enumerate(self.warnings, 1):
                result.append(f"  {i}. {warning}")
        if self.is_valid and not self.warnings:
            result.append("验证通过")
        return "\n".join(result)


class GraphValidator:
    def __init__(self, available_tools: Optional[Set[str]] = None):
        self.available_tools = available_tools or set()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @staticmethod
    def _as_id_list(value: Any) -> List[str]:
        if value is None or value == "null":
            return []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
        if isinstance(value, str):
            return [value]
        return []
    
    def validate(self, workflow_ir) -> ValidationResult: # workflow_ir type hint removed for standalone run
        result = ValidationResult()
        
        self._validate_node_ids(workflow_ir.nodes, result)
        self._validate_edges_reference(workflow_ir.nodes, workflow_ir.edges, result)
        self._validate_dag(workflow_ir.nodes, workflow_ir.edges, result)
        self._validate_tools(workflow_ir.nodes, result)
        self._validate_connectivity(workflow_ir.nodes, workflow_ir.edges, result)
        
        # 重点修改了这里，传入 edges 以便校验数据依赖和图结构的一致性
        self._validate_input_output(workflow_ir.nodes, workflow_ir.edges, result)
        
        return result
    
    def _validate_node_ids(self, nodes, result: ValidationResult):
        if not nodes:
            result.add_error("nodes 列表为空")
            return
        
        node_ids = [node.id for node in nodes]
        
        # 检查重复 ID
        id_counts = {}
        for node_id in node_ids:
            id_counts[node_id] = id_counts.get(node_id, 0) + 1
        
        for node_id, count in id_counts.items():
            if count > 1:
                result.add_error(f"节点 ID '{node_id}' 重复出现 {count} 次")
        
        # 分别验证 ST 节点和 GUARD 节点
        st_pattern = re.compile(r'^ST(\d+)$')
        guard_pattern = re.compile(r'^GUARD(\d+)$')
        
        st_nodes = []
        guard_nodes = []
        invalid_nodes = []
        
        for node in nodes:
            if st_pattern.match(node.id):
                st_nodes.append(node)
            elif guard_pattern.match(node.id):
                guard_nodes.append(node)
            else:
                invalid_nodes.append(node.id)
        
        # 报告格式错误的节点
        for node_id in invalid_nodes:
            result.add_error(f"节点 ID '{node_id}' 不符合 'ST{{数字}}' 或 'GUARD{{数字}}' 格式")
        
        # 验证 ST 节点编号连续性
        if st_nodes:
            expected_nums = set(range(1, len(st_nodes) + 1))
            actual_nums = set()
            
            for node in st_nodes:
                match = st_pattern.match(node.id)
                if match:
                    num = int(match.group(1))
                    actual_nums.add(num)
            
            if expected_nums != actual_nums:
                missing = expected_nums - actual_nums
                extra = actual_nums - expected_nums
                if missing:
                    result.add_error(f"ST 节点编号不连续，缺少: {sorted(missing)}")
                if extra:
                    result.add_error(f"ST 节点编号超出范围: {sorted(extra)}")
        
        # 验证 GUARD 节点编号连续性
        if guard_nodes:
            expected_guard_nums = set(range(1, len(guard_nodes) + 1))
            actual_guard_nums = set()
            
            for node in guard_nodes:
                match = guard_pattern.match(node.id)
                if match:
                    num = int(match.group(1))
                    actual_guard_nums.add(num)
            
            if expected_guard_nums != actual_guard_nums:
                missing = expected_guard_nums - actual_guard_nums
                extra = actual_guard_nums - expected_guard_nums
                if missing:
                    result.add_error(f"GUARD 节点编号不连续，缺少: {sorted(missing)}")
                if extra:
                    result.add_error(f"GUARD 节点编号超出范围: {sorted(extra)}")
    
    def _validate_edges_reference(self, nodes, edges, result: ValidationResult):
        node_ids = {node.id for node in nodes}
        
        for edge in edges:
            if edge.source not in node_ids:
                result.add_error(f"边引用了不存在的 source 节点: {edge.source}")
            if edge.target not in node_ids:
                result.add_error(f"边引用了不存在的 target 节点: {edge.target}")
        
        edge_set = {(edge.source, edge.target) for edge in edges}
        for node in nodes:
            for source_id in self._as_id_list(node.source):
                if source_id not in node_ids:
                    result.add_error(f"节点 {node.id} 的 source '{source_id}' 不存在")
                elif (source_id, node.id) not in edge_set:
                    result.add_warning(f"节点 {node.id} 声明 source '{source_id}'，但 edges 中缺少对应边")
            
            for target_id in self._as_id_list(node.target):
                if target_id not in node_ids:
                    result.add_error(f"节点 {node.id} 的 target '{target_id}' 不存在")
                elif (node.id, target_id) not in edge_set:
                    result.add_warning(f"节点 {node.id} 声明 target '{target_id}'，但 edges 中缺少对应边")
    
    def _validate_dag(self, nodes, edges, result: ValidationResult):
        graph = {}
        for node in nodes:
            graph[node.id] = []
        
        for edge in edges:
            if edge.source in graph:
                graph[edge.source].append(edge.target)
        
        visited = set()
        rec_stack = set()
        
        def has_cycle(node_id: str, path: List[str]) -> Optional[List[str]]:
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)
            
            for neighbor in graph.get(node_id, []):
                if neighbor not in visited:
                    cycle_path = has_cycle(neighbor, path.copy())
                    if cycle_path:
                        return cycle_path
                elif neighbor in rec_stack:
                    try:
                        cycle_start = path.index(neighbor)
                        return path[cycle_start:] + [neighbor]
                    except ValueError:
                        return path + [neighbor]
            
            rec_stack.remove(node_id)
            return None
        
        for node_id in graph:
            if node_id not in visited:
                cycle_path = has_cycle(node_id, [])
                if cycle_path:
                    cycle_str = " -> ".join(cycle_path)
                    result.add_error(f"检测到循环依赖: {cycle_str}")
                    break
    
    def _validate_tools(self, nodes, result: ValidationResult):
        for node in nodes:
            if node.executor == "tool":
                if not node.tool_name:
                    result.add_error(f"节点 {node.id} 的 executor 为 'tool'，但 tool_name 为空")
                elif self.available_tools and node.tool_name not in self.available_tools:
                    result.add_error(f"节点 {node.id} 使用的工具 '{node.tool_name}' 不在可用工具列表中")
            elif node.executor == "llm":
                if node.tool_name is not None and node.tool_name != "null": # 宽容处理 "null" 字符串
                    # result.add_warning(f"节点 {node.id} 的 executor 为 'llm'，但 tool_name 不为 null ({node.tool_name})")
                    pass 
    
    def _validate_connectivity(self, nodes, edges, result: ValidationResult):
        if len(nodes) <= 1:
            return
        
        graph = {}
        for node in nodes:
            graph[node.id] = []
        
        for edge in edges:
            if edge.source in graph:
                graph[edge.source].append(edge.target)
        
        start_nodes = [n.id for n in nodes if not self._as_id_list(n.source)]
        end_nodes = [n.id for n in nodes if not self._as_id_list(n.target)]
        
        if not start_nodes:
            result.add_error("没有找到起始节点（source 为 null 的节点）")
        if not end_nodes:
            result.add_error("没有找到结束节点（target 为 null 的节点）")
        
        if start_nodes:
            reachable = set()
            stack = start_nodes.copy()
            while stack:
                node_id = stack.pop()
                if node_id in reachable:
                    continue
                reachable.add(node_id)
                stack.extend(graph.get(node_id, []))
            
            unreachable = set(n.id for n in nodes) - reachable
            if unreachable:
                result.add_error(f"存在从起始节点无法到达的节点: {sorted(unreachable)}")
    
    # -------------------------------------------------------------
    # 重大修改部分：适应新的 Input Schema
    # -------------------------------------------------------------
    def _validate_input_output(self, nodes, edges, result: ValidationResult):
        node_ids = {node.id for node in nodes}
        
        # 构建边集合，用于检查数据引用是否符合图的拓扑结构
        # 格式: {(source, target)}
        existing_edges = set((e.source, e.target) for e in edges)

        # 匹配 {STx.output} 的正则
        variable_pattern = re.compile(r"\{([a-zA-Z0-9_]+)\.output\}")

        for node in nodes:
            # 1. 检查 input 字段是否存在 (允许为空字典，但不能是 None)
            if node.input is None:
                result.add_error(f"节点 {node.id} 缺少 input 字段 (应为字典)")
                continue
            
            # 旧代码检查 'parameter'，现在删除该检查
            # 旧代码检查 'pre_output'，现在删除该检查

            # 2. 遍历所有 input 的值，查找变量引用
            for key, value in node.input.items():
                if isinstance(value, str):
                    matches = variable_pattern.findall(value)
                    for ref_node_id in matches:
                        # 检查 A: 引用的节点是否存在
                        if ref_node_id not in node_ids:
                            result.add_error(f"节点 {node.id} 的参数 '{key}' 引用了不存在的节点: {ref_node_id}")
                            continue
                        
                        # 检查 B: 不能引用自己 (死循环)
                        if ref_node_id == node.id:
                            result.add_error(f"节点 {node.id} 在参数 '{key}' 中引用了自身输出")
                            continue

                        # 检查 C: 数据流必须符合控制流 (Warning 级别)
                        # 如果 Node B 用了 Node A 的数据，理论上应该有 A -> B 的边，或者是 A -> ... -> B
                        # 这里做一个简单的直接边检查，或者至少发出警告
                        # (注：LangGraph中如果数据依赖而没有边，执行顺序可能无法保证)
                        if (ref_node_id, node.id) not in existing_edges:
                            # 进一步：如果不是直接连接，可以检查是否是祖先节点。
                            # 为了简化，这里只报 Warning，提示用户检查连线
                            result.add_warning(
                                f"节点 {node.id} 引用了 {ref_node_id} 的数据，但在 edges 中没有直接连接 ({ref_node_id}->{node.id})。"
                                f"请确保执行顺序正确。"
                            )

            # 3. 检查 output
            if not node.output:
                result.add_warning(f"节点 {node.id} 缺少 output 字段 (描述性字段，建议填写)")


def validate_workflow_ir(workflow_ir, available_tools: Optional[Set[str]] = None) -> ValidationResult:
    validator = GraphValidator(available_tools)
    return validator.validate(workflow_ir)
