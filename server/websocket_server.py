import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Set

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
import shutil

from src.subtask_planner import SubtaskPlanner
from src.graph2workflow import Graph2Workflow
from tools.extract_mcp_tools import refresh_tool_metadata_incremental, refresh_tool_metadata, ToolExtractionError
from tools.mcp_manager import MCPToolManager, MCPManagerError

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def apply_param_overrides(workflow_ir, param_overrides):
    """
    应用参数覆盖到 WorkflowIR
    
    Args:
        workflow_ir: WorkflowIR 对象
        param_overrides: dict, 格式 {"ST1": {"city": "上海"}, "ST2": {...}}
    
    Returns:
        修改后的 WorkflowIR 对象
    """
    from src.subtask_planner import WorkflowIR, Subtask
    
    if not param_overrides:
        return workflow_ir
    
    modified_nodes = []
    for node in workflow_ir.nodes:
        if node.id in param_overrides:
            override_params = param_overrides[node.id]
            logger.info(f"节点 {node.id} 应用参数覆盖: {override_params}")
            
            # 复制节点数据
            node_dict = node.model_dump()
            
            # 合并参数覆盖
            if node_dict.get("input") is None:
                node_dict["input"] = {}
            
            # 根据节点类型处理参数
            if node.executor == "tool":
                # 工具节点：直接覆盖 input 中的参数
                if isinstance(node_dict["input"], dict):
                    if "__from_guard__" in node_dict["input"]:
                        # 如果有 guard 节点，记录覆盖意图（在执行时处理）
                        node_dict["input"]["_param_overrides"] = override_params
                    else:
                        # 直接合并参数
                        node_dict["input"].update(override_params)
            elif node.executor == "llm":
                # LLM 节点：覆盖 input 中的字段
                if isinstance(node_dict["input"], dict):
                    node_dict["input"].update(override_params)
                else:
                    # 如果 input 是字符串（旧格式），转为字典
                    node_dict["input"] = {"prompt": node_dict["input"], **override_params}
            elif node.executor == "param_guard":
                # param_guard 节点：覆盖 target_input_template
                if "input" in node_dict and isinstance(node_dict["input"], dict):
                    if "target_input_template" in node_dict["input"]:
                        node_dict["input"]["target_input_template"].update(override_params)
            
            modified_nodes.append(Subtask(**node_dict))
        else:
            modified_nodes.append(node)
    
    return WorkflowIR(nodes=modified_nodes, edges=workflow_ir.edges)


# 配置文件路径
MCP_CONFIG_PATH = Path(__file__).parent.parent / "tools" / "mcp_config.json"
GENERATED_TOOLS_PATH = Path(__file__).parent.parent / "tools" / "generated_tools.json"


def _config_changed() -> bool:
    """检测 mcp_config.json 是否比 generated_tools.json 更新"""
    if not GENERATED_TOOLS_PATH.exists():
        return True
    if not MCP_CONFIG_PATH.exists():
        return False
    return MCP_CONFIG_PATH.stat().st_mtime > GENERATED_TOOLS_PATH.stat().st_mtime


def _get_config_servers() -> set:
    """获取 mcp_config.json 中的服务器列表"""
    if not MCP_CONFIG_PATH.exists():
        return set()
    try:
        with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        return set(config.get("mcpServers", {}).keys())
    except Exception:
        return set()


def _get_generated_servers() -> set:
    """获取 generated_tools.json 中的服务器列表"""
    if not GENERATED_TOOLS_PATH.exists():
        return set()
    try:
        with open(GENERATED_TOOLS_PATH, "r", encoding="utf-8") as f:
            tools = json.load(f)
        return {meta.get("mcp_server") for meta in tools.values() if isinstance(meta, dict) and meta.get("mcp_server")}
    except Exception:
        return set()


async def _refresh_mcp_tools_background() -> None:
    try:
        config_servers = _get_config_servers()
        generated_servers = _get_generated_servers()

        # 检测是否需要完整刷新：配置文件更新、服务器被删除、或服务器列表不一致
        need_full_refresh = (
            _config_changed() or
            not generated_servers.issubset(config_servers) or
            generated_servers != config_servers
        )

        if need_full_refresh:
            logger.info("检测到 mcp_config.json 变化，执行完整刷新...")
            data = await asyncio.to_thread(refresh_tool_metadata)
            logger.info("MCP 工具列表已完整刷新，共 %s 个工具", len(data))
        else:
            # 增量更新（只添加新服务器）
            data, added = await asyncio.to_thread(refresh_tool_metadata_incremental)
            if added:
                logger.info("MCP 工具列表已增量更新，新增 %s 个工具，共 %s 个工具", added, len(data))
            else:
                logger.info("MCP 工具列表未变化，跳过刷新")
    except ToolExtractionError as exc:
        logger.warning("自动刷新 MCP 工具列表失败：%s", exc)
    except Exception as exc:
        logger.error("刷新 MCP 工具列表发生异常：%s", exc)


app = FastAPI()


@app.on_event("startup")
async def _schedule_tool_refresh() -> None:
    asyncio.create_task(_refresh_mcp_tools_background())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"客户端已连接，当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"客户端已断开，当前连接数: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in self.active_connections.copy():
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                self.active_connections.discard(connection)

manager = ConnectionManager()

TRACK_DIR = Path(__file__).parent.parent / "track"
SAVED_WORKFLOWS_DIR = Path(__file__).parent.parent / "saved_workflows"

# 确保目录存在
SAVED_WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)

# 请求模型
class SaveWorkflowRequest(BaseModel):
    run_id: str
    name: str
    description: str = ""
    param_overrides: dict = None

class LoadWorkflowResponse(BaseModel):
    id: str
    saved_as: str
    task: str
    saved_at: str
    description: str
    graph: dict
    result: dict

async def save_graph(workflow_ir, timestamp):
    session_dir = TRACK_DIR / timestamp
    session_dir.mkdir(parents=True, exist_ok=True)
    graph_file = session_dir / "graph.json"
    
    graph_data = workflow_ir.model_dump()
    with open(graph_file, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, indent=2, ensure_ascii=False)
    logger.info(f"已保存 DAG 图结构到: {graph_file}")

async def save_workflow_trace(execution_trace, timestamp):
    session_dir = TRACK_DIR / timestamp
    session_dir.mkdir(parents=True, exist_ok=True)
    workflow_file = session_dir / "workflow.json"
    
    workflow_data = {
        "execution_trace": execution_trace,
        "total_nodes": len(execution_trace),
        "successful_nodes": sum(1 for t in execution_trace if t["status"] == "success"),
        "failed_nodes": sum(1 for t in execution_trace if t["status"] == "failed"),
    }
    with open(workflow_file, "w", encoding="utf-8") as f:
        json.dump(workflow_data, f, indent=2, ensure_ascii=False)
    logger.info(f"已保存工作流执行过程到: {workflow_file}")

async def save_result(final_result, timestamp):
    session_dir = TRACK_DIR / timestamp
    session_dir.mkdir(parents=True, exist_ok=True)
    result_file = session_dir / "result.json"
    
    result_data = {
        "outputs": final_result["outputs"],
        "error": final_result.get("error"),
        "timestamp": timestamp
    }
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)
    logger.info(f"已保存最终结果到: {result_file}")

async def execute_workflow(task: str, param_overrides: dict = None, workflow_graph: dict = None):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 创建会话目录并保存元数据
    session_dir = TRACK_DIR / timestamp
    session_dir.mkdir(parents=True, exist_ok=True)

    meta_data = {
        "task": task,
        "param_overrides": param_overrides or {},
        "created_at": timestamp,
        "reuse_workflow": workflow_graph is not None
    }
    with open(session_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta_data, f, indent=2, ensure_ascii=False)

    # 广播 run_id 给前端
    await manager.broadcast({
        "type": "run_id",
        "run_id": timestamp
    })

    tools = {}
    mcp_manager = None
    try:
        mcp_manager = MCPToolManager()
        logger.info("MCP 工具管理器已启用")
    except MCPManagerError as exc:
        logger.warning("MCP 工具不可用: %s", exc)

    # 记录参数覆盖信息
    if param_overrides:
        logger.info(f"应用参数覆盖: {param_overrides}")

    try:
        await manager.broadcast({
            "type": "stage",
            "stage": "planning"
        })

        # 如果提供了工作流图，直接使用，跳过规划阶段
        if workflow_graph:
            logger.info("使用已有的工作流图，跳过规划阶段")
            from src.subtask_planner import WorkflowIR
            workflow_ir = WorkflowIR(**workflow_graph)

            # 保存一个简化的规划数据
            await manager.broadcast({
                "type": "planning",
                "data": {
                    "current_stage": "workflow_ir",
                    "raw_json": None,
                    "fixed_json": None,
                    "workflow_ir": workflow_ir.model_dump(),
                    "reused": True
                }
            })
        else:
            # 正常规划流程
            logger.info(f"开始规划任务: {task}")
            planner = SubtaskPlanner()

            await manager.broadcast({
                "type": "planning",
                "data": {
                    "current_stage": "raw_json",
                    "raw_json": None,
                    "fixed_json": None,
                    "workflow_ir": None
                }
            })

            # 使用线程池执行同步的 plan 操作，避免阻塞事件循环
            workflow_ir = await asyncio.to_thread(planner.plan, task)
            last_run = planner.get_last_run()

            await manager.broadcast({
                "type": "planning",
                "data": {
                    "current_stage": "workflow_ir",
                    "raw_json": last_run.get("raw_json"),
                    "fixed_json": last_run.get("fixed_json"),
                    "workflow_ir": workflow_ir.model_dump()
                }
            })

        # 应用参数覆盖
        if param_overrides:
            workflow_ir = apply_param_overrides(workflow_ir, param_overrides)
            logger.info("参数覆盖已应用")

        await manager.broadcast({
            "type": "stage",
            "stage": "dag"
        })

        await manager.broadcast({
            "type": "dag",
            "data": workflow_ir.model_dump()
        })

        await save_graph(workflow_ir, timestamp)

        await asyncio.sleep(0.5)

        await manager.broadcast({
            "type": "stage",
            "stage": "executing"
        })
        
        logger.info("开始执行工作流")
        
        # 创建同步广播回调（将在同步节点中调用）
        broadcast_queue = []
        def sync_broadcast_callback(trace_entry):
            broadcast_queue.append(trace_entry)
        
        g2w = Graph2Workflow(workflow_ir, tools, mcp_manager=mcp_manager)
        
        # 传递广播回调给 context
        if hasattr(g2w, 'context') and g2w.context:
            g2w.context.broadcast_callback = sync_broadcast_callback
        
        # 创建后台任务定期推送
        async def broadcast_worker():
            while True:
                if broadcast_queue:
                    trace_entry = broadcast_queue.pop(0)
                    await manager.broadcast({
                        "type": "execution",
                        "data": trace_entry
                    })
                await asyncio.sleep(0.05)
        
        broadcast_task = asyncio.create_task(broadcast_worker())
        
        class StreamingGraph2Workflow(Graph2Workflow):
            async def _create_tool_node_async(self, subtask):
                async def tool_node(state):
                    start_time = datetime.now()
                    self.logger.info(f"执行工具节点: {subtask.id} - {subtask.name}")
                    
                    trace_entry = {
                        "node_id": subtask.id,
                        "node_name": subtask.name,
                        "node_type": "tool",
                        "tool_name": subtask.tool_name,
                        "start_time": start_time.isoformat(),
                        "status": "running"
                    }
                    
                    await manager.broadcast({
                        "type": "execution",
                        "data": trace_entry
                    })
                    
                    try:
                        tool_func = self.tools.get(subtask.tool_name)
                        if not tool_func:
                            raise ValueError(f"工具 {subtask.tool_name} 未找到")

                        pre_output = subtask.input.get("pre_output")
                        parameter = subtask.input.get("parameter")
                        
                        if pre_output and pre_output != "null":
                            source_id = pre_output.split(".")[0]
                            tool_input = {**parameter, "context": state["outputs"].get(source_id, "")}
                        else:
                            tool_input = parameter

                        trace_entry["input"] = tool_input
                        result = tool_func(**tool_input)
                        
                        state["outputs"][subtask.id] = result
                        end_time = datetime.now()
                        trace_entry["output"] = result
                        trace_entry["status"] = "success"
                        trace_entry["end_time"] = end_time.isoformat()
                        trace_entry["duration_ms"] = (end_time - start_time).total_seconds() * 1000
                        self.logger.info(f"工具节点 {subtask.id} 执行成功: {result}")
                        
                    except Exception as e:
                        end_time = datetime.now()
                        self.logger.error(f"工具节点 {subtask.id} 执行失败: {e}")
                        state["error"] = str(e)
                        trace_entry["status"] = "failed"
                        trace_entry["error"] = str(e)
                        trace_entry["end_time"] = end_time.isoformat()
                        trace_entry["duration_ms"] = (end_time - start_time).total_seconds() * 1000
                    
                    self.execution_trace.append(trace_entry)
                    await manager.broadcast({
                        "type": "execution",
                        "data": trace_entry
                    })
                    
                    return state
                return tool_node

            async def _create_llm_node_async(self, subtask):
                from langchain_core.messages import HumanMessage
                import os
                from langchain_openai import ChatOpenAI
                
                if subtask.llm_config:
                    node_llm = ChatOpenAI(
                        api_key=subtask.llm_config.api_key or os.getenv("PLANNER_KEY"),
                        base_url=subtask.llm_config.base_url or os.getenv("PLANNER_URL"),
                        model=subtask.llm_config.model or os.getenv("PLANNER_MODEL", "gpt-4o"),
                    )
                    model_info = subtask.llm_config.model or os.getenv("PLANNER_MODEL", "gpt-4o")
                else:
                    node_llm = self.llm
                    model_info = os.getenv("PLANNER_MODEL", "gpt-4o")
                
                async def llm_node(state):
                    start_time = datetime.now()
                    self.logger.info(f"执行LLM节点: {subtask.id} - {subtask.name} (模型: {model_info})")
                    
                    trace_entry = {
                        "node_id": subtask.id,
                        "node_name": subtask.name,
                        "node_type": "llm",
                        "model": model_info,
                        "start_time": start_time.isoformat(),
                        "status": "running"
                    }
                    
                    await manager.broadcast({
                        "type": "execution",
                        "data": trace_entry
                    })
                    
                    try:
                        pre_output = subtask.input.get("pre_output")
                        parameter = subtask.input.get("parameter")
                        
                        if pre_output and pre_output != "null":
                            source_id = pre_output.split(".")[0]
                            context = state["outputs"].get(source_id, "")
                            prompt = parameter.replace(f"{{{pre_output}}}", str(context))
                        else:
                            prompt = parameter

                        trace_entry["input"] = {"prompt": prompt}
                        messages = [HumanMessage(content=prompt)]
                        response = node_llm.invoke(messages)
                        result = response.content
                        
                        state["outputs"][subtask.id] = result
                        end_time = datetime.now()
                        trace_entry["output"] = result
                        trace_entry["status"] = "success"
                        trace_entry["end_time"] = end_time.isoformat()
                        trace_entry["duration_ms"] = (end_time - start_time).total_seconds() * 1000
                        self.logger.info(f"LLM节点 {subtask.id} 执行成功")
                        
                    except Exception as e:
                        end_time = datetime.now()
                        self.logger.error(f"LLM节点 {subtask.id} 执行失败: {e}")
                        state["error"] = str(e)
                        trace_entry["status"] = "failed"
                        trace_entry["error"] = str(e)
                        trace_entry["end_time"] = end_time.isoformat()
                        trace_entry["duration_ms"] = (end_time - start_time).total_seconds() * 1000
                    
                    self.execution_trace.append(trace_entry)
                    await manager.broadcast({
                        "type": "execution",
                        "data": trace_entry
                    })
                    
                    return state
                return llm_node

        # 使用线程池执行同步的 execute 操作，避免阻塞事件循环
        result = await asyncio.to_thread(g2w.execute)

        # 停止广播任务
        broadcast_task.cancel()
        try:
            await broadcast_task
        except asyncio.CancelledError:
            pass
        
        # 推送队列中剩余的 trace
        while broadcast_queue:
            trace_entry = broadcast_queue.pop(0)
            await manager.broadcast({
                "type": "execution",
                "data": trace_entry
            })
        
        execution_trace = g2w.get_execution_trace()
        failed_details = [
            {
                "node_id": trace["node_id"],
                "error": trace.get("error") or trace.get("output"),
            }
            for trace in execution_trace
            if trace.get("status") == "failed"
        ]

        # 不再重复推送（已通过 broadcast_worker 实时推送）
        # for trace in execution_trace:
        #     await manager.broadcast({"type": "execution", "data": trace})
        #     await asyncio.sleep(0.1)
        
        await save_workflow_trace(execution_trace, timestamp)
        await save_result(result, timestamp)
        
        await manager.broadcast({
            "type": "stage",
            "stage": "completed"
        })
        
        await manager.broadcast({
            "type": "result",
            "data": {
                "outputs": result["outputs"],
                "error": result.get("error"),
                "total_nodes": len(execution_trace),
                "successful_nodes": sum(1 for t in execution_trace if t["status"] == "success"),
                "failed_nodes": sum(1 for t in execution_trace if t["status"] == "failed"),
                "failed_details": failed_details,
            }
        })
        
        logger.info("工作流执行完成")
        
    except Exception as e:
        logger.error(f"工作流执行失败: {e}", exc_info=True)
        
        # 保存失败时的中间数据
        session_dir = TRACK_DIR / timestamp
        session_dir.mkdir(parents=True, exist_ok=True)
        error_file = session_dir / "error.json"
        
        error_data = {
            "error": str(e),
            "task": task,
            "timestamp": timestamp
        }
        
        # 尝试保存规划器的中间数据
        if 'planner' in locals():
            last_run = planner.get_last_run()
            planning_data = {
                "plan_text": last_run.get("plan_text"),
                "raw_json": last_run.get("raw_json"),
                "fixed_json": last_run.get("fixed_json"),
                "workflow_json_str": last_run.get("workflow_json_str"),
                "error": last_run.get("error"),
                "error_stage": last_run.get("error_stage"),
                "fix_attempts": last_run.get("fix_attempts", []),
                "llm_response_metadata": last_run.get("llm_response_metadata"),
            }
            workflow_ir_obj = last_run.get("workflow_ir")
            if workflow_ir_obj is not None:
                try:
                    planning_data["workflow_ir"] = workflow_ir_obj.model_dump()
                except Exception:
                    planning_data["workflow_ir"] = str(workflow_ir_obj)
            error_data["planning_data"] = planning_data
            
            # 如果有 fixed_json，额外保存为独立的 graph.json（即使是空字典也保存）
            if last_run.get("fixed_json") is not None:
                try:
                    graph_file = session_dir / "graph.json"
                    with open(graph_file, "w", encoding="utf-8") as f:
                        json.dump(last_run.get("fixed_json"), f, indent=2, ensure_ascii=False)
                    logger.info(f"已保存失败时的 graph 数据到: {graph_file}")
                except Exception as save_err:
                    logger.warning(f"保存 graph.json 失败: {save_err}")
        
        with open(error_file, "w", encoding="utf-8") as f:
            json.dump(error_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"已保存错误信息和中间数据到: {error_file}")
        
        await manager.broadcast({
            "type": "error",
            "message": str(e)
        })
    finally:
        if mcp_manager:
            mcp_manager.shutdown()

# REST API 端点

TOOLS_FILE = Path(__file__).parent.parent / "tools" / "generated_tools.json"

@app.get("/tools")
async def list_tools():
    """获取所有可用工具列表"""
    try:
        if not TOOLS_FILE.exists():
            return JSONResponse(content=[])

        with open(TOOLS_FILE, "r", encoding="utf-8") as f:
            tools_data = json.load(f)

        # 转换为列表格式，便于前端使用
        tools_list = []
        for tool_name, tool_info in tools_data.items():
            tools_list.append({
                "name": tool_name,
                "description": tool_info.get("description", ""),
                "input_schema": tool_info.get("input_schema", {}),
                "executor": tool_info.get("executor", "tool"),
                "mcp_server": tool_info.get("mcp_server"),
                "mcp_tool": tool_info.get("mcp_tool")
            })

        return JSONResponse(content=tools_list)

    except Exception as e:
        logger.error(f"获取工具列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workflows")
async def list_workflows():
    """获取所有保存的工作流列表"""
    workflows = []
    try:
        for workflow_dir in SAVED_WORKFLOWS_DIR.iterdir():
            if workflow_dir.is_dir():
                summary_file = workflow_dir / "summary.json"
                if summary_file.exists():
                    try:
                        with open(summary_file, "r", encoding="utf-8") as f:
                            summary = json.load(f)
                            workflows.append({
                                "id": workflow_dir.name,  # 使用目录名作为 id，这样前端可以直接用来加载
                                "run_id": summary.get("run_id", ""),
                                "saved_as": summary.get("saved_as", workflow_dir.name),
                                "task": summary.get("task", ""),
                                "saved_at": summary.get("saved_at", ""),
                                "description": summary.get("description", "")
                            })
                    except Exception as e:
                        logger.error(f"读取工作流 {workflow_dir.name} 失败: {e}")

        # 按保存时间倒序排列
        workflows.sort(key=lambda x: x.get("saved_at", ""), reverse=True)
        return JSONResponse(content=workflows)

    except Exception as e:
        logger.error(f"获取工作流列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/workflows")
async def save_workflow(request: SaveWorkflowRequest):
    """保存工作流"""
    try:
        # 验证名称格式
        if not request.name or len(request.name) < 1 or len(request.name) > 50:
            raise HTTPException(status_code=400, detail="工作流名称长度必须在1-50个字符之间")

        # 不允许的特殊字符（文件系统不支持的字符）
        import re
        if re.search(r'[<>:"/\\|?*]', request.name):
            raise HTTPException(status_code=400, detail="工作流名称不能包含以下字符: < > : \" / \\ | ? *")

        # 检查源工作流是否存在
        source_dir = TRACK_DIR / request.run_id
        if not source_dir.exists():
            raise HTTPException(status_code=404, detail=f"工作流执行记录 {request.run_id} 不存在")

        # 检查是否已存在同名工作流
        target_dir = SAVED_WORKFLOWS_DIR / request.name
        if target_dir.exists():
            raise HTTPException(status_code=409, detail=f"工作流 {request.name} 已存在")

        # 复制工作流文件
        target_dir.mkdir(parents=True, exist_ok=True)

        # 复制核心文件
        files_to_copy = ["graph.json", "workflow.json", "result.json"]
        for file_name in files_to_copy:
            source_file = source_dir / file_name
            if source_file.exists():
                shutil.copy2(source_file, target_dir / file_name)

        # 读取任务信息
        task = ""
        meta_file = source_dir / "meta.json"
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
                task = meta.get("task", "")

        # 读取结果信息
        result_data = {}
        result_file = target_dir / "result.json"
        if result_file.exists():
            with open(result_file, "r", encoding="utf-8") as f:
                result_data = json.load(f)

        # 创建 summary.json
        summary = {
            "run_id": request.run_id,
            "saved_as": request.name,
            "saved_at": datetime.now().isoformat() + "Z",
            "task": task,
            "description": request.description,
            "outputs": result_data.get("outputs", {}),
            "param_overrides": request.param_overrides or {}
        }

        with open(target_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        logger.info(f"工作流已保存: {request.name}")

        return JSONResponse(content={
            "success": True,
            "message": f"工作流 '{request.name}' 保存成功",
            "workflow": {
                "id": request.run_id,
                "saved_as": request.name,
                "task": task,
                "saved_at": summary["saved_at"],
                "description": request.description
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存工作流失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/workflows/{workflow_name}")
async def get_workflow(workflow_name: str):
    """获取特定工作流的详细信息"""
    try:
        workflow_dir = SAVED_WORKFLOWS_DIR / workflow_name
        if not workflow_dir.exists():
            raise HTTPException(status_code=404, detail=f"工作流 {workflow_name} 不存在")

        # 读取各个文件
        summary_file = workflow_dir / "summary.json"
        graph_file = workflow_dir / "graph.json"
        result_file = workflow_dir / "result.json"

        if not summary_file.exists():
            raise HTTPException(status_code=404, detail="工作流摘要文件不存在")

        with open(summary_file, "r", encoding="utf-8") as f:
            summary = json.load(f)

        graph_data = {}
        if graph_file.exists():
            with open(graph_file, "r", encoding="utf-8") as f:
                graph_data = json.load(f)

        result_data = {}
        if result_file.exists():
            with open(result_file, "r", encoding="utf-8") as f:
                result_data = json.load(f)

        return JSONResponse(content={
            "id": workflow_name,  # 工作流名称（目录名）
            "run_id": summary.get("run_id", ""),  # 原始执行记录的 run_id
            "saved_as": summary.get("saved_as", workflow_name),
            "task": summary.get("task", ""),
            "saved_at": summary.get("saved_at", ""),
            "description": summary.get("description", ""),
            "graph": graph_data,
            "result": result_data,
            "param_overrides": summary.get("param_overrides", {})
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取工作流 {workflow_name} 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/workflows/{workflow_name}")
async def delete_workflow(workflow_name: str):
    """删除工作流"""
    try:
        workflow_dir = SAVED_WORKFLOWS_DIR / workflow_name
        if not workflow_dir.exists():
            raise HTTPException(status_code=404, detail=f"工作流 {workflow_name} 不存在")

        shutil.rmtree(workflow_dir)
        logger.info(f"工作流已删除: {workflow_name}")

        return JSONResponse(content={
            "success": True,
            "message": f"工作流 '{workflow_name}' 已删除"
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除工作流 {workflow_name} 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            logger.info(f"收到消息: {data}")

            if data["type"] == "start":
                task = data.get("task", "")
                param_overrides = data.get("param_overrides", None)
                workflow_graph = data.get("workflow_graph", None)  # 新增：接收工作流图
                asyncio.create_task(execute_workflow(task, param_overrides, workflow_graph))
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")
        manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
