#!/usr/bin/env python
"""
Task2Workflow 服务启动脚本
"""
from dotenv import load_dotenv

load_dotenv()

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 导入并启动服务器
from server.websocket_server import app
import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print("Task2Workflow starting...")
    print("=" * 60)
    print("Backend: http://localhost:8000")
    print("WebSocket: ws://localhost:8000/ws")
    print("Frontend: http://localhost:3000 (start separately)")
    print("=" * 60)
    print("Press Ctrl+C to stop\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
