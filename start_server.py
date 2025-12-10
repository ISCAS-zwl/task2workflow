#!/usr/bin/env python
"""
Task2Workflow 服务启动脚本
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 导入并启动服务器
from server.websocket_server import app
import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Task2Workflow 服务启动中...")
    print("=" * 60)
    print("📍 后端服务: http://localhost:8000")
    print("📍 WebSocket: ws://localhost:8000/ws")
    print("📍 前端地址: http://localhost:3000 (需要单独启动)")
    print("=" * 60)
    print("按 Ctrl+C 停止服务\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
