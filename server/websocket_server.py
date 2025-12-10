import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Set

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from src.subtask_planner import SubtaskPlanner
from src.graph2workflow import Graph2Workflow
from tools.extract_mcp_tools import refresh_tool_metadata, ToolExtractionError
from tools.mcp_manager import MCPToolManager, MCPManagerError
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def _refresh_mcp_tools_background() -> None:
    try:
        data = await asyncio.to_thread(refresh_tool_metadata)
        logger.info("MCP 工具列表已更新，共 %s 个工具", len(data))
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

TRACK_DIR = Path(__file__).parent / "track"

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

async def execute_workflow(task: str):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tools = {}
    mcp_manager = None
    try:
        mcp_manager = MCPToolManager()
        logger.info("MCP 工具管理器已启用")
    except MCPManagerError as exc:
        logger.warning("MCP 工具不可用: %s", exc)
    
    try:
        await manager.broadcast({
            "type": "stage",
            "stage": "planning"
        })
        
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
        
        workflow_ir = planner.plan(task)
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
        g2w = Graph2Workflow(workflow_ir, tools, mcp_manager=mcp_manager)
        
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
        
        result = g2w.execute()
        
        execution_trace = g2w.get_execution_trace()
        failed_details = [
            {
                "node_id": trace["node_id"],
                "error": trace.get("error") or trace.get("output"),
            }
            for trace in execution_trace
            if trace.get("status") == "failed"
        ]

        for trace in execution_trace:
            await manager.broadcast({
                "type": "execution",
                "data": trace
            })
            await asyncio.sleep(0.1)
        
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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            logger.info(f"收到消息: {data}")
            
            if data["type"] == "start":
                task = data.get("task", "")
                asyncio.create_task(execute_workflow(task))
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")
        manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
