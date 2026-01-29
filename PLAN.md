# 前端节点创建、拖动和删除功能实现计划

## 功能概述

为 Task2Workflow 前端添加以下功能：
1. **工具面板拖拽创建节点** - 在 DAG 视图旁添加工具面板，用户可拖拽创建节点
2. **节点连接** - 支持拖拽连线和对话框编辑两种方式
3. **删除功能** - 支持删除节点和边
4. **实时同步** - 修改实时同步到后端

---

## 一、前端修改

### 1. 新建 ToolPanel 组件

**文件**: `frontend/src/components/ToolPanel.jsx`

功能：
- 显示可用的节点类型（LLM、Tool、Guard）
- 从 `/api/tools` 获取可用工具列表
- 支持拖拽节点到画布
- 搜索/过滤工具

```jsx
// 主要结构
- 节点类型分组
  - LLM 节点（可直接拖拽）
  - Tool 节点（展开显示工具列表）
  - Guard 节点（可直接拖拽）
- 每个可拖拽项使用 draggable="true" 和 onDragStart 设置拖拽数据
```

### 2. 修改 DAGView 组件

**文件**: `frontend/src/components/DAGView.jsx`

修改内容：

#### 2.1 启用连接功能
```jsx
// 修改 ReactFlow 配置
nodesConnectable={editMode}  // 编辑模式下可连接
edgesUpdatable={editMode}    // 编辑模式下可更新边
```

#### 2.2 添加拖放处理
```jsx
// 添加 onDrop 和 onDragOver 处理
const onDrop = useCallback((event) => {
  event.preventDefault()
  const type = event.dataTransfer.getData('application/reactflow')
  const nodeData = JSON.parse(event.dataTransfer.getData('nodeData'))

  // 计算放置位置
  const position = reactFlowInstance.screenToFlowPosition({
    x: event.clientX,
    y: event.clientY,
  })

  // 创建新节点
  const newNode = {
    id: generateNodeId(),
    type: 'custom',
    position,
    data: nodeData
  }

  // 通知父组件
  onNodeCreate(newNode)
}, [reactFlowInstance])
```

#### 2.3 添加连接处理
```jsx
// 添加 onConnect 回调
const onConnect = useCallback((params) => {
  const newEdge = {
    source: params.source,
    target: params.target
  }
  onEdgeCreate(newEdge)
}, [])
```

#### 2.4 添加删除处理
```jsx
// 添加键盘事件处理
const onKeyDown = useCallback((event) => {
  if (event.key === 'Delete' || event.key === 'Backspace') {
    // 删除选中的节点和边
    onNodesDelete(selectedNodes)
    onEdgesDelete(selectedEdges)
  }
}, [selectedNodes, selectedEdges])

// 添加右键菜单
const onNodeContextMenu = useCallback((event, node) => {
  event.preventDefault()
  setContextMenu({ x: event.clientX, y: event.clientY, node })
}, [])
```

#### 2.5 添加节点编辑对话框中的连接编辑
在 `NodeEditDialog.jsx` 中添加：
- 前置节点选择器（多选下拉）
- 后置节点选择器（多选下拉）

### 3. 修改 App.jsx

**文件**: `frontend/src/App.jsx`

添加：
- `dagModified` 状态跟踪图是否被修改
- `handleNodeCreate` - 创建节点并同步
- `handleNodeDelete` - 删除节点并同步
- `handleEdgeCreate` - 创建边并同步
- `handleEdgeDelete` - 删除边并同步
- `handleGraphSync` - 实时同步图结构到后端

### 4. 新建 ContextMenu 组件

**文件**: `frontend/src/components/ContextMenu.jsx`

功能：
- 右键菜单显示删除选项
- 节点右键：编辑、删除
- 边右键：删除
- 画布右键：添加节点

### 5. 新建 NodeCreateDialog 组件

**文件**: `frontend/src/components/NodeCreateDialog.jsx`

功能：
- 创建新节点的完整表单
- 选择节点类型（LLM/Tool/Guard）
- 配置节点参数
- 选择工具（Tool 类型时）

---

## 二、后端修改

### 1. 添加图同步 API

**文件**: `server/websocket_server.py`

添加 REST API 端点：

```python
# 更新工作流图
@app.put("/workflows/{workflow_id}/graph")
async def update_workflow_graph(workflow_id: str, graph: WorkflowGraphUpdate):
    """实时更新工作流图结构"""
    pass

# 添加节点
@app.post("/workflows/{workflow_id}/nodes")
async def add_node(workflow_id: str, node: NodeCreate):
    """添加新节点"""
    pass

# 删除节点
@app.delete("/workflows/{workflow_id}/nodes/{node_id}")
async def delete_node(workflow_id: str, node_id: str):
    """删除节点"""
    pass

# 添加边
@app.post("/workflows/{workflow_id}/edges")
async def add_edge(workflow_id: str, edge: EdgeCreate):
    """添加新边"""
    pass

# 删除边
@app.delete("/workflows/{workflow_id}/edges/{edge_id}")
async def delete_edge(workflow_id: str, edge_id: str):
    """删除边"""
    pass

# 获取可用工具列表
@app.get("/tools")
async def list_tools():
    """获取所有可用工具"""
    pass
```

### 2. 添加 WebSocket 消息类型

```python
# 新增消息类型
- graph_update: 图结构更新
- node_add: 添加节点
- node_delete: 删除节点
- edge_add: 添加边
- edge_delete: 删除边
```

---

## 三、新增文件清单

| 文件路径 | 说明 |
|---------|------|
| `frontend/src/components/ToolPanel.jsx` | 工具面板组件 |
| `frontend/src/components/ToolPanel.css` | 工具面板样式 |
| `frontend/src/components/ContextMenu.jsx` | 右键菜单组件 |
| `frontend/src/components/ContextMenu.css` | 右键菜单样式 |
| `frontend/src/components/NodeCreateDialog.jsx` | 节点创建对话框 |
| `frontend/src/components/NodeCreateDialog.css` | 节点创建对话框样式 |

---

## 四、修改文件清单

| 文件路径 | 修改内容 |
|---------|---------|
| `frontend/src/components/DAGView.jsx` | 添加拖放、连接、删除、右键菜单功能 |
| `frontend/src/components/DAGView.css` | 添加新样式（连接线、选中状态等） |
| `frontend/src/components/NodeEditDialog.jsx` | 添加前置/后置节点选择器 |
| `frontend/src/components/NodeEditDialog.css` | 添加新样式 |
| `frontend/src/components/WorkflowTabs.jsx` | 传递新的回调函数 |
| `frontend/src/App.jsx` | 添加图编辑状态管理和同步逻辑 |
| `frontend/src/App.css` | 添加工具面板布局样式 |
| `server/websocket_server.py` | 添加图同步 API 和工具列表 API |

---

## 五、实现步骤

### 阶段 1：基础设施
1. 后端添加 `/tools` API 返回工具列表
2. 后端添加图同步相关 API

### 阶段 2：工具面板
3. 创建 ToolPanel 组件
4. 实现工具列表获取和显示
5. 实现拖拽功能

### 阶段 3：DAG 编辑
6. 修改 DAGView 支持拖放创建节点
7. 启用 ReactFlow 连接功能
8. 实现节点/边的选择和删除

### 阶段 4：右键菜单
9. 创建 ContextMenu 组件
10. 集成到 DAGView

### 阶段 5：节点编辑增强
11. 修改 NodeEditDialog 添加连接编辑
12. 创建 NodeCreateDialog 完整表单

### 阶段 6：状态同步
13. 修改 App.jsx 添加图编辑状态管理
14. 实现实时同步逻辑

### 阶段 7：样式和优化
15. 完善所有组件样式
16. 添加动画和交互反馈
17. 测试和修复

---

## 六、数据流设计

```
用户操作
    ↓
DAGView 捕获事件
    ↓
调用 App.jsx 回调 (onNodeCreate/onEdgeCreate/onNodeDelete/onEdgeDelete)
    ↓
App.jsx 更新本地 dagData 状态
    ↓
调用后端 API 同步 (PUT /workflows/{id}/graph)
    ↓
后端更新存储
    ↓
后端广播更新消息给所有客户端（可选）
```

---

## 七、节点 ID 生成规则

新创建的节点 ID 格式：`ST{n}`，其中 n 为当前最大节点编号 + 1

```javascript
const generateNodeId = (existingNodes) => {
  const maxNum = existingNodes.reduce((max, node) => {
    const match = node.id.match(/^ST(\d+)$/)
    return match ? Math.max(max, parseInt(match[1])) : max
  }, 0)
  return `ST${maxNum + 1}`
}
```

---

## 八、注意事项

1. **图验证**：删除节点时需要同时删除相关的边
2. **循环检测**：创建边时需要检测是否会形成循环
3. **孤立节点**：允许创建没有连接的节点
4. **撤销功能**：暂不实现，后续可考虑添加
5. **并发编辑**：当前设计为单用户编辑，不考虑多用户冲突
