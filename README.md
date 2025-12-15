# Task2Workflow

一个基于 LLM 的自动化工作流规划与执行系统，能够将自然语言任务描述自动转换为可执行的工作流，并通过可视化界面实时监控执行过程。

## 项目简介

Task2Workflow 是一个智能任务编排系统，它能够：

1. **自动规划**：使用大语言模型（LLM）将自然语言任务拆解为结构化的子任务
2. **智能整形**：通过参数守卫（ParamGuard）自动处理节点间的数据适配和类型转换
3. **DAG 构建**：自动构建有向无环图（DAG）表示任务依赖关系
4. **工作流执行**：基于 LangGraph 执行工作流，支持 LLM 节点和工具节点
5. **实时可视化**：通过 WebSocket 实时推送执行状态到前端，支持四象限监控视图
6. **参数覆盖**：支持在不重新规划的情况下修改节点参数并重新执行（Phase 1 特性）

## 核心特性

### 🤖 智能工作流规划

- **三阶段规划器**：
  1. 生成原始 JSON 工作流
  2. 自动修复和验证 JSON 格式
  3. 转换为 WorkflowIR（中间表示）
  
- **自动参数整形**：通过 `param_guard` 节点自动处理复杂的数据转换需求，无需手动编写字段映射

- **工具集成**：支持 MCP (Model Context Protocol) 工具，可以动态加载和调用外部工具

### 📊 实时可视化监控

- **四象限布局**：
  - 左上：工作流规划过程（JSON 生成 → 修复 → WorkflowIR）
  - 右上：交互式 DAG 图（使用 ReactFlow）
  - 左下：执行过程时间线
  - 右下：最终结果和统计
  
- **节点状态追踪**：实时显示每个节点的执行状态（待执行/执行中/成功/失败）

- **性能指标**：显示每个节点的执行时长和输入输出

### ✏️ 参数覆盖功能（Phase 1）

- **无需重新规划**：修改参数后直接执行，节省 LLM 调用成本
- **双模式编辑**：支持表单模式和 JSON 模式编辑节点参数
- **批量修改**：可以修改多个节点后一次性应用
- **可视化标识**：已编辑的节点显示黄色边框和 ✓ 标记

详见：[参数覆盖功能使用指南](PARAM_OVERRIDE_GUIDE.md)

### 🔧 工具生态系统

通过 MCP 协议集成多种工具：
- 搜索工具（Bing 搜索、趋势查询）
- 交通工具（12306 火车票查询）
- 网络工具（HTTP 请求）
- 更多...（见 `tools/mcp_config.json`）

## 技术架构

### 后端技术栈

- **Python 3.8+**
- **FastAPI**：Web 框架，提供 WebSocket 支持
- **LangGraph**：工作流执行引擎
- **LangChain**：LLM 应用开发框架
- **OpenAI**：LLM API 客户端
- **Pydantic**：数据验证和序列化
- **MCP (Model Context Protocol)**：工具集成协议

### 前端技术栈

- **React 18**：UI 框架
- **Vite**：构建工具
- **ReactFlow**：DAG 图可视化
- **Lucide React**：图标库
- **WebSocket**：实时通信

### 核心组件

```
task2workflow/
├── src/                        # 核心业务逻辑
│   ├── subtask_planner.py      # 任务规划器（三阶段）
│   ├── graph2workflow.py       # DAG 转工作流执行器
│   ├── graph_validator.py      # 工作流验证器
│   ├── param_guard.py          # 参数整形守卫
│   └── prompt.txt              # LLM 规划提示词
├── server/                     # Web 服务
│   └── websocket_server.py     # WebSocket 服务器
├── tools/                      # 工具管理
│   ├── mcp_manager.py          # MCP 工具管理器
│   ├── mcp_config.json         # MCP 服务器配置
│   └── generated_tools.json    # 工具元数据缓存
├── frontend/                   # React 前端
│   └── src/
│       ├── App.jsx             # 主应用
│       └── components/         # UI 组件
└── data/                       # 数据目录
```

## 快速开始

### 环境要求

- Python 3.8 或更高版本
- Node.js 16 或更高版本
- npm 或 yarn

### 1. 克隆项目

```bash
git clone https://github.com/ISCAS-zwl/task2workflow.git
cd task2workflow
```

### 2. 配置环境变量

在项目根目录创建 `.env` 文件：

```env
# 规划器 LLM 配置
PLANNER_KEY=your_api_key
PLANNER_URL=your_api_base_url
PLANNER_MODEL=gpt-4o

# 参数守卫 LLM 配置（可选，默认使用规划器配置）
GUARD_KEY=your_api_key
GUARD_URL=your_api_base_url
GUARD_MODEL=gpt-4o-mini

# 测试配置（可选）
TEST_KEY=your_test_api_key
TEST_URL=your_test_api_url
TEST_MODEL=your_test_model
```

### 3. 安装后端依赖

```bash
# 安装核心依赖
pip install -r requirements.txt

# 如果需要 Web 服务器功能
pip install -r requirements_web.txt
```

### 4. 启动后端服务

```bash
# 方式 1：使用启动脚本
python start_server.py

# 方式 2：直接启动 uvicorn
cd server
uvicorn websocket_server:app --host 0.0.0.0 --port 8000 --reload
```

后端服务将在 `http://localhost:8000` 启动。

### 5. 安装前端依赖并启动

```bash
cd frontend
npm install
npm run dev
```

前端应用将在 `http://localhost:3000` 启动（默认端口可能是 5173）。

### 6. 使用界面

1. 打开浏览器访问前端地址
2. 在输入框中输入任务描述，例如："查询北京今天的天气并生成一句话总结"
3. 点击 **"开始执行"** 按钮
4. 观察四个面板的实时更新：
   - **左上**：工作流规划过程
   - **右上**：DAG 图结构
   - **左下**：执行过程详情
   - **右下**：最终结果

## 使用示例

### 基础任务

```
输入：查询北京的天气

系统自动生成：
1. 节点 ST1：调用天气查询工具，输入 location="Beijing"
2. 执行并返回天气数据
```

### 复杂任务

```
输入：查询从北京到上海的火车票，并总结一下最快的车次

系统自动生成：
1. 节点 ST1：调用火车票查询工具
2. 节点 ST2：LLM 分析火车票数据，找出最快的车次
3. 节点 ST3：LLM 生成总结
```

### 参数覆盖场景

```
1. 执行任务："查询北京的天气"
2. 工作流规划完成后，点击"编辑工作流"
3. 点击节点，将 location 参数从 "Beijing" 改为 "Shanghai"
4. 点击"应用修改"，系统使用新参数重新执行，无需重新规划
```

## 工作流程详解

### 1. 任务规划阶段

```
用户输入 → SubtaskPlanner
  ↓
阶段1: 生成原始 JSON（调用 LLM）
  ↓
阶段2: 自动修复 JSON 格式
  ↓
阶段3: 转换为 WorkflowIR
  ↓
GraphValidator: 验证 DAG 结构
```

### 2. 工作流执行阶段

```
WorkflowIR → Graph2Workflow
  ↓
构建 LangGraph StateGraph
  ↓
并行/串行执行节点：
  - LLM 节点：调用 LLM API
  - Tool 节点：调用 MCP 工具
  - ParamGuard 节点：自动参数整形
  ↓
收集输出并推送到前端
```

### 3. 参数整形机制

当工具需要的参数格式与上游输出不匹配时，系统自动插入 `param_guard` 节点：

```
节点 A (输出: JSON 数组) 
  ↓
param_guard 节点 (自动提取和转换字段)
  ↓
节点 B (输入: 特定字段)
```

## 开发指南

### 运行测试

```bash
# 测试 LLM 连接
python test.py
```

### 添加新的 MCP 工具

1. 编辑 `tools/mcp_config.json`，添加新的 MCP 服务器配置：

```json
{
  "mcpServers": {
    "your-tool": {
      "command": "npx",
      "args": ["-y", "your-mcp-package"]
    }
  }
}
```

2. 重启后端服务，工具会自动加载

### 修改规划提示词

编辑 `src/prompt.txt` 文件，调整 LLM 规划行为。

### 调试模式

前端提供调试模式开关，可以查看详细的执行日志和中间数据。

### 输出长度控制

在 `src/graph2workflow.py` 中配置 `MAX_OUTPUT_LENGTH` 参数：

```python
# 设置输出截断长度（字符数）
MAX_OUTPUT_LENGTH = 1000  # 1KB
```

## 配置说明

### 环境变量

| 变量名 | 说明 | 必需 |
|--------|------|------|
| `PLANNER_KEY` | 规划器 LLM API Key | ✅ |
| `PLANNER_URL` | 规划器 LLM Base URL | ✅ |
| `PLANNER_MODEL` | 规划器模型名称 | ✅ |
| `GUARD_KEY` | 参数守卫 LLM API Key | ❌ |
| `GUARD_URL` | 参数守卫 LLM Base URL | ❌ |
| `GUARD_MODEL` | 参数守卫模型名称 | ❌ |

如果未配置 `GUARD_*` 变量，将使用 `PLANNER_*` 配置。

### MCP 工具配置

编辑 `tools/mcp_config.json`：

```json
{
  "mcpServers": {
    "server-name": {
      "command": "command-to-run",
      "args": ["arg1", "arg2"]
    }
  }
}
```

## 数据持久化

执行结果自动保存到 `track/` 目录：

```
track/
└── YYYYMMDD_HHMMSS/
    ├── graph.json       # DAG 图结构
    ├── workflow.json    # 执行过程记录
    └── result.json      # 最终结果
```

## 常见问题

### Q: 为什么任务规划失败？

A: 检查以下几点：
1. 确认 `.env` 文件中的 LLM API 配置正确
2. 检查网络连接
3. 查看后端日志获取详细错误信息
4. 确保 API 账户有足够的额度

### Q: 工具调用失败怎么办？

A: 
1. 检查 `tools/mcp_config.json` 配置是否正确
2. 确保已安装对应的 MCP 工具包（如 `npx` 命令可用）
3. 查看 `tools/generated_tools.json` 确认工具已加载

### Q: 前端无法连接后端？

A: 
1. 确认后端服务已启动在 `http://localhost:8000`
2. 检查防火墙设置
3. 查看浏览器控制台的 WebSocket 连接错误

### Q: 如何修改参数而不重新规划？

A: 使用参数覆盖功能，详见 [参数覆盖功能使用指南](PARAM_OVERRIDE_GUIDE.md)

## 项目路线图

- [x] **Phase 0**：基础工作流规划和执行
- [x] **Phase 1**：节点参数覆盖功能
- [ ] **Phase 2**：完整工作流编辑器
  - 添加/删除节点
  - 修改连接关系
  - 工作流模板保存/加载
  - 版本管理

## 相关文档

- [前端可视化系统文档](README_FRONTEND.md)
- [参数覆盖功能使用指南](PARAM_OVERRIDE_GUIDE.md)

## 浏览器兼容性

推荐使用现代浏览器：
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## 贡献指南

欢迎提交 Issue 和 Pull Request！

## 开源协议

本项目采用 MIT 协议开源。

## 致谢

感谢以下开源项目：
- [LangChain](https://github.com/langchain-ai/langchain)
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [ReactFlow](https://github.com/wbkd/react-flow)
- [FastAPI](https://github.com/tiangolo/fastapi)
- [Model Context Protocol](https://modelcontextprotocol.io/)

---

**如有问题或建议，请提交 Issue 或联系项目维护者。**
