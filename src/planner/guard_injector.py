import copy
import json
import logging
import re
from typing import Any, Dict, List, Optional

from src.planner.models import Subtask, WorkflowIR

logger = logging.getLogger(__name__)


class GuardInjector:
    
    def __init__(self, tools_definition: Optional[Dict[str, Any]] = None):
        self.tools_definition = tools_definition or {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def inject(self, workflow_ir: WorkflowIR) -> WorkflowIR:
        node_data_map: Dict[str, Dict[str, Any]] = {
            node.id: node.model_dump() for node in workflow_ir.nodes
        }
        edges_data: List[Dict[str, str]] = [edge.model_dump() for edge in workflow_ir.edges]

        original_inputs: Dict[str, Dict[str, Any]] = {
            node_id: copy.deepcopy(node_data.get("input") or {})
            for node_id, node_data in node_data_map.items()
        }

        next_guard_idx = max(
            (self._extract_guard_idx(nid) for nid in node_data_map.keys()), default=0
        ) + 1

        target_guards_map = self._collect_guard_edges(node_data_map, edges_data)
        
        new_edges: List[Dict[str, str]] = []
        for edge in edges_data:
            if edge["target"] not in target_guards_map:
                new_edges.append(edge)

        inserted_count = 0

        for target_id, guard_infos in target_guards_map.items():
            target_node = node_data_map[target_id]
            target_tool = target_node.get("tool_name")
            target_schema = (self.tools_definition.get(target_tool) or {}).get("input_schema") or {}
            target_input_template = copy.deepcopy(original_inputs.get(target_id, {}))
            
            source_ids = [info["source_id"] for info in guard_infos]
            
            guard_id = f"GUARD{next_guard_idx}"
            next_guard_idx += 1
            inserted_count += 1
            
            guard_node = self._create_guard_node(
                guard_id, target_id, target_tool, source_ids, target_input_template, target_schema
            )
            
            node_data_map[guard_id] = guard_node.model_dump()
            
            for source_id in source_ids:
                current_target = node_data_map[source_id].get("target")
                updated_target = self._replace_id(current_target, target_id, guard_id)
                node_data_map[source_id]["target"] = updated_target
            
            for source_id in source_ids:
                new_edges.append({"source": source_id, "target": guard_id})
            new_edges.append({"source": guard_id, "target": target_id})
            
            node_data_map[target_id]["input"] = {"__from_guard__": guard_id}
            node_data_map[target_id]["source"] = [guard_id]

        if inserted_count:
            self.logger.info("已自动插入 %s 个参数整形节点", inserted_count)

        sorted_nodes = sorted(node_data_map.values(), key=self._sort_key)
        return WorkflowIR(
            nodes=[Subtask(**n) for n in sorted_nodes],
            edges=new_edges,
        )

    def _collect_guard_edges(
        self, node_data_map: Dict[str, Dict[str, Any]], edges_data: List[Dict[str, str]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        target_guards_map: Dict[str, List[Dict[str, Any]]] = {}
        
        for edge in edges_data:
            source_id = edge["source"]
            target_id = edge["target"]

            source_node = node_data_map.get(source_id)
            target_node = node_data_map.get(target_id)

            if source_node and target_node and self._needs_param_guard(target_node):
                if target_id not in target_guards_map:
                    target_guards_map[target_id] = []
                target_guards_map[target_id].append({
                    "source_id": source_id,
                    "edge": edge
                })

        return target_guards_map

    def _needs_param_guard(self, target_node_data: Dict[str, Any]) -> bool:
        if target_node_data.get("executor") != "tool":
            return False
        
        target_input = target_node_data.get("input") or {}
        input_str = json.dumps(target_input, ensure_ascii=False)
        return bool(re.search(r"\{ST\d+\.output\}", input_str))

    def _create_guard_node(
        self,
        guard_id: str,
        target_id: str,
        target_tool: Optional[str],
        source_ids: List[str],
        target_input_template: Dict[str, Any],
        target_schema: Dict[str, Any],
    ) -> Subtask:
        return Subtask(
            id=guard_id,
            name=f"参数整形: {target_tool or target_id}",
            description=f"校验并整形下游工具 {target_tool or target_id} 的入参",
            executor="param_guard",
            tool_name=target_tool,
            source=source_ids or None,
            target=[target_id],
            output="整形后的下游工具入参",
            input={
                "source_nodes": source_ids,
                "target_node": target_id,
                "target_tool": target_tool,
                "target_input_template": target_input_template,
                "schema": target_schema,
            },
        )

    @staticmethod
    def _as_id_list(value: Any) -> List[str]:
        if value is None or value == "null":
            return []
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
        if isinstance(value, str):
            return [value]
        return []

    @staticmethod
    def _replace_id(value: Any, old_id: str, new_id: str) -> Any:
        items = GuardInjector._as_id_list(value)
        if not items:
            return value
        return [new_id if item == old_id else item for item in items]

    @staticmethod
    def _extract_idx(node_id: str) -> int:
        match = re.match(r"ST(\d+)", node_id)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _extract_guard_idx(node_id: str) -> int:
        match = re.match(r"GUARD(\d+)", node_id)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _sort_key(n: Dict[str, Any]):
        node_id = n.get("id", "")
        if node_id.startswith("GUARD"):
            return (1, GuardInjector._extract_guard_idx(node_id))
        else:
            return (0, GuardInjector._extract_idx(node_id))
