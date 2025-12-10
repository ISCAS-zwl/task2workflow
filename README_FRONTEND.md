# Task2Workflow 前端可视化系统

基于 task2workflow 项目的实时可视化监控前端，可以观测工作流规划、DAG 图生成和执行的全过程。

## 功能特性

### 1. 工作流规划可视化
- **三阶段展示**: 原始 JSON 生成 → JSON 修复 → WorkflowIR 生成
- **实时状态跟踪**: 显示每个规划阶段的进度和状态
- **数据预览**: 查看每个阶段生成的中间数据

### 2. DAG 图可视化
- **交互式图形**: 使用 ReactFlow 渲染工作流 DAG 图
- **节点类型区分**: LLM 节点和 Tool 节点使用不同颜色标识
- **实时状态更新**: 节点随执行状态动态变化(待执行/执行中/成功/失败)
- **性能指标**: 显示每个节点的执行时长

### 3. 执行过程监控
- **时间线视图**: 按执行顺序展示所有节点
- **详细信息**: 每个节点显示输入、输出、执行时长等
- **错误追踪**: 失败节点高亮显示错误信息
- **节点类型**: 清晰标注 LLM 模型或工具名称

### 4. 最终结果展示
- **统计概览**: 成功/失败节点数量统计
- **节点输出**: 汇总展示所有节点的输出结果
- **错误报告**: 如有错误，显示详细错误信息

## 技术栈

### 前端
- **React 18**: 前端框架
- **Vite**: 构建工具
- **ReactFlow**: DAG 图可视化库
- **Lucide React**: 图标库
- **WebSocket**: 实时通信

### 后端
- **FastAPI**: Web 框架
- **WebSocket**: 实时推送
- **LangGraph**: 工作流执行引擎
- **Pydantic**: 数据验证

## 安装和运行

### 1. 安装后端依赖

```bash
pip install -r requirements_web.txt
```

### 2. 配置环境变量

确保项目根目录有 `.env` 文件,包含以下配置:

```env
PLANNER_KEY=your_api_key
PLANNER_URL=your_api_url
PLANNER_MODEL=gpt-4o
```

### 3. 启动后端服务

```bash
python websocket_server.py
```

后端服务将在 `http://localhost:8000` 启动。

### 4. 安装前端依赖

```bash
cd frontend
npm install
```

### 5. 启动前端开发服务器

```bash
npm run dev
```

前端应用将在 `http://localhost:3000` 启动。

### 6. 使用界面

1. 打开浏览器访问 `http://localhost:3000`
2. 在输入框中输入任务描述
3. 点击"开始执行"按钮
4. 观察四个面板中的实时更新:
   - 左上: 工作流规划过程
   - 右上: DAG 图结构
   - 左下: 执行过程详情
   - 右下: 最终结果

## 项目结构

```
task2workflow/
├── frontend/                    # 前端项目
│   ├── src/
│   │   ├── components/         # React 组件
│   │   │   ├── PlanningView.jsx       # 规划视图
│   │   │   ├── DAGView.jsx            # DAG 图视图
│   │   │   ├── ExecutionView.jsx      # 执行监控视图
│   │   │   └── ResultView.jsx         # 结果展示视图
│   │   ├── App.jsx             # 主应用组件
│   │   ├── App.css             # 全局样式
│   │   └── main.jsx            # 入口文件
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── websocket_server.py         # WebSocket 后端服务
├── subtask_planner.py          # 任务规划器
├── graph2workflow.py           # DAG 转工作流
└── requirements_web.txt        # Python 依赖
```

## WebSocket 消息协议

### 客户端 → 服务端

```json
{
  "type": "start",
  "task": "任务描述"
}
```

### 服务端 → 客户端

#### 阶段更新
```json
{
  "type": "stage",
  "stage": "planning" | "dag" | "executing" | "completed"
}
```

#### 规划数据
```json
{
  "type": "planning",
  "data": {
    "current_stage": "raw_json" | "fixed_json" | "workflow_ir",
    "raw_json": "...",
    "fixed_json": {...},
    "workflow_ir": {...}
  }
}
```

#### DAG 图
```json
{
  "type": "dag",
  "data": {
    "nodes": [...],
    "edges": [...]
  }
}
```

#### 执行更新
```json
{
  "type": "execution",
  "data": {
    "node_id": "ST1",
    "node_name": "...",
    "node_type": "llm" | "tool",
    "status": "running" | "success" | "failed",
    "input": {...},
    "output": "...",
    "duration_ms": 1234,
    "start_time": "2025-11-25T...",
    "end_time": "2025-11-25T..."
  }
}
```

#### 最终结果
```json
{
  "type": "result",
  "data": {
    "outputs": {...},
    "error": null,
    "total_nodes": 3,
    "successful_nodes": 3,
    "failed_nodes": 0
  }
}
```

## 界面预览

### 四象限布局
- **左上象限**: 工作流规划 - 展示 JSON 生成和修复过程
- **右上象限**: DAG 图 - 交互式图形化展示工作流结构
- **左下象限**: 执行过程 - 时间线展示每个节点的执行详情
- **右下象限**: 最终结果 - 汇总统计和输出结果

### 状态指示器
顶部显示整体进度:
- **规划中** (蓝色) - 正在生成工作流
- **生成DAG** (蓝色) - 正在构建 DAG 图
- **执行中** (蓝色脉冲) - 工作流执行中
- **已完成** (绿色) - 执行完成

## 数据持久化

执行结果自动保存到 `track/` 目录:

```
track/
└── 20251125_135603/
    ├── graph.json       # DAG 图结构
    ├── workflow.json    # 执行过程记录
    └── result.json      # 最终结果
```

## 开发和调试

### 前端开发
```bash
cd frontend
npm run dev
```

前端支持热重载,修改代码后自动刷新。

### 后端开发
后端使用 FastAPI,支持自动重载:
```bash
uvicorn websocket_server:app --reload --host 0.0.0.0 --port 8000
```

### 查看日志
后端日志会输出到控制台,包含详细的执行信息。

## 浏览器兼容性

推荐使用现代浏览器:
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## 许可证

与 task2workflow 主项目保持一致。
