import React, { useMemo, useState, useCallback, useRef } from 'react'
import ReactFlow, {
  Background,
  Controls,
  MarkerType,
  Handle,
  Position,
  useReactFlow,
  ReactFlowProvider,
  addEdge,
  useNodesState,
  useEdgesState
} from 'reactflow'
import 'reactflow/dist/style.css'
import { Network } from 'lucide-react'
import NodeEditDialog from './NodeEditDialog'
import ContextMenu from './ContextMenu'
import './DAGView.css'

function CustomNode({ data, selected }) {
  const statusClass = data.status || 'pending'
  const isLLM = data.executor === 'llm'
  const isEdited = data.isEdited || false
  const hasActualInput = data.actualInput !== undefined

  const getDisplayParams = () => {
    if (!data.input) return null

    if (isLLM) {
      const prompt = data.input.prompt
      if (!prompt) return null

      return {
        prompt: typeof prompt === 'string'
          ? prompt
          : JSON.stringify(prompt)
      }
    }

    const filtered = { ...data.input }
    delete filtered.__from_guard__
    delete filtered._param_overrides

    if (Object.keys(filtered).length === 0) return null

    return filtered
  }

  const displayParams = getDisplayParams()

  return (
    <div className={`custom-node ${statusClass} ${isEdited ? 'edited' : ''} ${selected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-header">
        <span className={`node-type ${isLLM ? 'llm' : 'tool'}`}>
          {isLLM ? 'LLM' : data.executor === 'param_guard' ? 'GUARD' : 'TOOL'}
        </span>
        <span className="node-id">
          {data.id}
          {isEdited && <span className="edited-badge">✓</span>}
          {hasActualInput && <span className="actual-badge" title="显示实际执行参数">▶</span>}
        </span>
      </div>
      <div className="node-body">
        <div className="node-name">{data.name}</div>
        {data.tool_name && (
          <div className="node-tool">{data.tool_name}</div>
        )}
        <div className="node-desc">{data.description}</div>
        {displayParams && (
          <div className="node-params">
            {Object.entries(displayParams).map(([key, value]) => (
              <div key={key} className="param-item">
                <span className="param-key">{key}:</span>
                <span className="param-value">{String(value).slice(0, 50)}{String(value).length > 50 ? '...' : ''}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {data.duration && (
        <div className="node-footer">
          <span className="node-duration">{data.duration}ms</span>
        </div>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const nodeTypes = {
  custom: CustomNode
}

const HORIZONTAL_SPACING = 450
const VERTICAL_SPACING = 200

function buildLayout(nodes, edges) {
  const adjacency = new Map()
  const inDegree = new Map()

  nodes.forEach(node => {
    adjacency.set(node.id, [])
    inDegree.set(node.id, 0)
  })

  edges.forEach(edge => {
    if (!adjacency.has(edge.source)) {
      adjacency.set(edge.source, [])
    }
    adjacency.get(edge.source).push(edge.target)
    inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1)
  })

  const levelMap = new Map()
  const queue = []

  inDegree.forEach((degree, nodeId) => {
    if (degree === 0) {
      queue.push(nodeId)
      levelMap.set(nodeId, 0)
    }
  })

  while (queue.length > 0) {
    const current = queue.shift()
    const currentLevel = levelMap.get(current) || 0
    const neighbours = adjacency.get(current) || []

    neighbours.forEach(target => {
      const nextLevel = Math.max((levelMap.get(target) || 0), currentLevel + 1)
      levelMap.set(target, nextLevel)

      const nextDegree = (inDegree.get(target) || 0) - 1
      inDegree.set(target, nextDegree)
      if (nextDegree === 0) {
        queue.push(target)
      }
    })
  }

  const levelBuckets = new Map()
  nodes.forEach(node => {
    const level = levelMap.get(node.id) ?? 0
    if (!levelBuckets.has(level)) {
      levelBuckets.set(level, [])
    }
    levelBuckets.get(level).push(node.id)
  })

  const positions = {}

  Array.from(levelBuckets.keys())
    .sort((a, b) => a - b)
    .forEach(level => {
      const bucket = levelBuckets.get(level) || []
      const totalHeight = (bucket.length - 1) * VERTICAL_SPACING
      const offsetY = totalHeight / 2

      bucket.forEach((nodeId, index) => {
        positions[nodeId] = {
          x: level * HORIZONTAL_SPACING + 80,
          y: index * VERTICAL_SPACING - offsetY + 250
        }
      })
    })

  return positions
}

// 生成新节点 ID
function generateNodeId(existingNodes) {
  const maxNum = existingNodes.reduce((max, node) => {
    const match = node.id?.match(/^ST(\d+)$/)
    return match ? Math.max(max, parseInt(match[1])) : max
  }, 0)
  return `ST${maxNum + 1}`
}

// 检测是否会形成循环
function wouldCreateCycle(edges, newSource, newTarget) {
  const adjacency = new Map()
  edges.forEach(edge => {
    if (!adjacency.has(edge.source)) {
      adjacency.set(edge.source, [])
    }
    adjacency.get(edge.source).push(edge.target)
  })

  // 添加新边后检测从 newTarget 是否能到达 newSource
  if (!adjacency.has(newSource)) {
    adjacency.set(newSource, [])
  }
  adjacency.get(newSource).push(newTarget)

  const visited = new Set()
  const stack = [newTarget]

  while (stack.length > 0) {
    const current = stack.pop()
    if (current === newSource) {
      return true // 发现循环
    }
    if (visited.has(current)) continue
    visited.add(current)

    const neighbors = adjacency.get(current) || []
    stack.push(...neighbors)
  }

  return false
}

function DAGViewInner({
  data,
  executionData,
  editMode,
  onParamOverridesChange,
  paramOverrides,
  onNodeCreate,
  onNodeDelete,
  onEdgeCreate,
  onEdgeDelete,
  onNodesChange: onNodesChangeExternal
}) {
  const [editingNode, setEditingNode] = useState(null)
  const [contextMenu, setContextMenu] = useState(null)
  const reactFlowWrapper = useRef(null)
  const { screenToFlowPosition } = useReactFlow()

  const { initialNodes, initialEdges, nodeSource, cleanEdgeSource } = useMemo(() => {
    const effectiveData = data || { nodes: [], edges: [] }

    const nodeSource = Array.isArray(effectiveData.nodes) ? effectiveData.nodes : []
    const explicitEdges = Array.isArray(effectiveData.edges) ? effectiveData.edges : []

    let derivedEdges = []

    if (!explicitEdges.length) {
      derivedEdges = nodeSource.flatMap(node => {
        const edges = []

        if (node.source && node.source !== 'null') {
          edges.push({
            source: node.source,
            target: node.id
          })
        }

        if (node.target && node.target !== 'null') {
          edges.push({
            source: node.id,
            target: node.target
          })
        }

        return edges
      })
    }

    const edgeSource = explicitEdges.length ? explicitEdges : derivedEdges

    const uniqueEdgeMap = new Map()
    edgeSource.forEach(edge => {
      const key = `${edge.source}-${edge.target}`
      uniqueEdgeMap.set(key, edge)
    })
    const cleanEdgeSource = Array.from(uniqueEdgeMap.values())

    const executionMap = new Map()
    executionData?.forEach(exec => {
      executionMap.set(exec.node_id, exec)
    })

    const positions = buildLayout(nodeSource, cleanEdgeSource)

    const nodeList = nodeSource.map((node, index) => {
      const exec = executionMap.get(node.id)
      const isEdited = paramOverrides && paramOverrides[node.id]

      let displayData = { ...node }
      let hasActualInput = false

      if (exec && exec.status !== 'running') {
        if (exec.input) {
          displayData.input = exec.input
          hasActualInput = true
        }
        if (exec.output) {
          displayData.output = exec.output
        }
      }

      return {
        id: String(node.id),
        type: 'custom',
        position: positions[node.id] || { x: index * 320 + 50, y: 100 },
        data: {
          ...displayData,
          status: exec?.status || 'pending',
          duration: exec?.duration_ms ? Math.round(exec.duration_ms) : null,
          isEdited,
          actualInput: hasActualInput ? exec.input : undefined
        }
      }
    })

    const edgeList = cleanEdgeSource.map(edge => ({
      id: `${edge.source}-${edge.target}`,
      source: String(edge.source),
      target: String(edge.target),
      type: 'default',
      animated: false,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: '#58a6ff',
        width: 24,
        height: 24
      },
      style: {
        stroke: '#58a6ff',
        strokeWidth: 2.5,
        strokeOpacity: 0.7,
        strokeLinecap: 'round'
      }
    }))

    return { initialNodes: nodeList, initialEdges: edgeList, nodeSource, cleanEdgeSource }
  }, [data, executionData, paramOverrides])

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  // 记录上一次的 data 和 executionData，用于判断是否需要重置布局
  const prevDataRef = useRef(data)
  const prevExecutionDataRef = useRef(executionData)

  // 同步外部数据变化
  React.useEffect(() => {
    const dataChanged = prevDataRef.current !== data
    const executionDataChanged = prevExecutionDataRef.current !== executionData

    if (dataChanged) {
      // data 变化时，完全重置节点和边
      setNodes(initialNodes)
      setEdges(initialEdges)
    } else if (executionDataChanged) {
      // executionData 变化时，只更新节点的 data 属性，保留位置
      setNodes(currentNodes => {
        const nodeMap = new Map(initialNodes.map(n => [n.id, n]))
        return currentNodes.map(node => {
          const newNode = nodeMap.get(node.id)
          if (newNode) {
            return { ...node, data: newNode.data }
          }
          return node
        })
      })
    } else {
      // 只有 paramOverrides 变化时，只更新节点的 data.isEdited 属性，保留位置
      setNodes(currentNodes => {
        const nodeMap = new Map(initialNodes.map(n => [n.id, n]))
        return currentNodes.map(node => {
          const newNode = nodeMap.get(node.id)
          if (newNode) {
            return { ...node, data: { ...node.data, isEdited: newNode.data.isEdited } }
          }
          return node
        })
      })
    }

    prevDataRef.current = data
    prevExecutionDataRef.current = executionData
  }, [initialNodes, initialEdges, setNodes, setEdges, data, executionData])

  const handleNodeClick = useCallback((event, node) => {
    if (editMode) {
      const originalNode = data?.nodes?.find(n => n.id === node.id)
      if (originalNode) {
        const exec = executionData?.find(e => e.node_id === node.id)
        const nodeToEdit = { ...originalNode }

        if (exec && exec.status !== 'running' && exec.input) {
          nodeToEdit.input = exec.input
        }

        setEditingNode(nodeToEdit)
      }
    }
  }, [editMode, data, executionData])

  const handleSaveNodeEdit = useCallback((nodeId, newParams) => {
    const updatedOverrides = { ...paramOverrides, [nodeId]: newParams }
    onParamOverridesChange(updatedOverrides)
    setEditingNode(null)
  }, [paramOverrides, onParamOverridesChange])

  // 处理连接
  const onConnect = useCallback((params) => {
    if (!editMode) return

    // 检测循环
    if (wouldCreateCycle(cleanEdgeSource, params.source, params.target)) {
      alert('无法创建连接：会形成循环依赖')
      return
    }

    const newEdge = {
      source: params.source,
      target: params.target
    }

    if (onEdgeCreate) {
      onEdgeCreate(newEdge)
    }

    setEdges((eds) => addEdge({
      ...params,
      type: 'default',
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: '#58a6ff',
        width: 24,
        height: 24
      },
      style: {
        stroke: '#58a6ff',
        strokeWidth: 2.5,
        strokeOpacity: 0.7,
        strokeLinecap: 'round'
      }
    }, eds))
  }, [editMode, cleanEdgeSource, onEdgeCreate, setEdges])

  // 处理拖放
  const onDragOver = useCallback((event) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback((event) => {
    event.preventDefault()

    if (!editMode) return

    const type = event.dataTransfer.getData('application/reactflow')
    const nodeDataStr = event.dataTransfer.getData('nodeData')

    if (!type || !nodeDataStr) return

    const nodeData = JSON.parse(nodeDataStr)
    const position = screenToFlowPosition({
      x: event.clientX,
      y: event.clientY,
    })

    const newNodeId = generateNodeId(nodeSource)

    let newNode = {
      id: newNodeId,
      name: '',
      description: '',
      executor: nodeData.type,
      input: {}
    }

    if (nodeData.type === 'llm') {
      newNode.name = '新 LLM 节点'
      newNode.description = '使用大语言模型处理任务'
      newNode.input = { prompt: '' }
    } else if (nodeData.type === 'tool' && nodeData.tool) {
      newNode.name = nodeData.tool.name
      newNode.description = nodeData.tool.description?.split('\n')[0]?.slice(0, 100) || ''
      newNode.tool_name = nodeData.tool.name
      newNode.input = {}
      // 从 schema 中提取默认参数
      const schema = nodeData.tool.input_schema
      if (schema?.properties) {
        Object.keys(schema.properties).forEach(key => {
          const prop = schema.properties[key]
          newNode.input[key] = prop.default !== undefined ? prop.default : ''
        })
      }
    } else if (nodeData.type === 'param_guard') {
      newNode.name = '参数验证'
      newNode.description = '验证和转换参数'
      newNode.input = { target_input_template: {} }
    }

    if (onNodeCreate) {
      onNodeCreate(newNode, position)
    }

    const flowNode = {
      id: newNodeId,
      type: 'custom',
      position,
      data: {
        ...newNode,
        status: 'pending'
      }
    }

    setNodes((nds) => nds.concat(flowNode))
  }, [editMode, screenToFlowPosition, nodeSource, onNodeCreate, setNodes])

  // 右键菜单
  const onNodeContextMenu = useCallback((event, node) => {
    if (!editMode) return
    event.preventDefault()
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      type: 'node',
      target: node
    })
  }, [editMode])

  const onEdgeContextMenu = useCallback((event, edge) => {
    if (!editMode) return
    event.preventDefault()
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      type: 'edge',
      target: edge
    })
  }, [editMode])

  const onPaneContextMenu = useCallback((event) => {
    if (!editMode) return
    event.preventDefault()
    const position = screenToFlowPosition({
      x: event.clientX,
      y: event.clientY,
    })
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      type: 'pane',
      position
    })
  }, [editMode, screenToFlowPosition])

  const closeContextMenu = useCallback(() => {
    setContextMenu(null)
  }, [])

  const handleContextMenuAction = useCallback((action) => {
    if (!contextMenu) return

    if (action === 'delete') {
      if (contextMenu.type === 'node') {
        const nodeId = contextMenu.target.id
        setNodes((nds) => nds.filter((n) => n.id !== nodeId))
        setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId))
        if (onNodeDelete) {
          onNodeDelete(nodeId)
        }
      } else if (contextMenu.type === 'edge') {
        const edgeId = contextMenu.target.id
        setEdges((eds) => eds.filter((e) => e.id !== edgeId))
        if (onEdgeDelete) {
          onEdgeDelete(contextMenu.target.source, contextMenu.target.target)
        }
      }
    } else if (action === 'edit' && contextMenu.type === 'node') {
      const originalNode = data?.nodes?.find(n => n.id === contextMenu.target.id)
      if (originalNode) {
        setEditingNode(originalNode)
      }
    } else if (action === 'add-llm' || action === 'add-tool' || action === 'add-guard') {
      const nodeType = action.replace('add-', '')
      const newNodeId = generateNodeId(nodeSource)

      let newNode = {
        id: newNodeId,
        name: nodeType === 'llm' ? '新 LLM 节点' : nodeType === 'param_guard' ? '参数验证' : '新工具节点',
        description: '',
        executor: nodeType === 'guard' ? 'param_guard' : nodeType,
        input: nodeType === 'llm' ? { prompt: '' } : {}
      }

      if (onNodeCreate) {
        onNodeCreate(newNode, contextMenu.position)
      }

      const flowNode = {
        id: newNodeId,
        type: 'custom',
        position: contextMenu.position,
        data: {
          ...newNode,
          status: 'pending'
        }
      }

      setNodes((nds) => nds.concat(flowNode))
    }

    closeContextMenu()
  }, [contextMenu, data, nodeSource, onNodeCreate, onNodeDelete, onEdgeDelete, setNodes, setEdges, closeContextMenu])

  // 节点位置变化时通知外部
  const handleNodesChange = useCallback((changes) => {
    onNodesChange(changes)
    if (onNodesChangeExternal && editMode) {
      const positionChanges = changes.filter(c => c.type === 'position' && c.dragging === false)
      if (positionChanges.length > 0) {
        onNodesChangeExternal(positionChanges)
      }
    }
  }, [onNodesChange, onNodesChangeExternal, editMode])

  if (!data && !editMode) {
    return (
      <div className="empty-state">
        <Network size={48} className="empty-icon" />
        <p>{'等待 DAG 图生成...'}</p>
      </div>
    )
  }

  return (
    <div className={`dag-view ${editMode ? 'edit-mode' : ''}`} ref={reactFlowWrapper}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3, minZoom: 0.4, maxZoom: 1.5 }}
        attributionPosition="bottom-right"
        style={{ width: '100%', height: '100%' }}
        onNodeClick={handleNodeClick}
        onNodeContextMenu={onNodeContextMenu}
        onEdgeContextMenu={onEdgeContextMenu}
        onPaneContextMenu={onPaneContextMenu}
        onPaneClick={closeContextMenu}
        onDrop={onDrop}
        onDragOver={onDragOver}
        nodesDraggable={true}
        nodesConnectable={editMode}
        edgesUpdatable={editMode}
        elementsSelectable={editMode}
        selectNodesOnDrag={editMode}
        defaultEdgeOptions={{
          type: 'default',
          animated: false
        }}
        connectionLineStyle={{
          stroke: '#58a6ff',
          strokeWidth: 2.5
        }}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#30363d" gap={24} size={1.2} variant="dots" />
        <Controls showInteractive={false} />
      </ReactFlow>

      {editingNode && (
        <NodeEditDialog
          node={editingNode}
          onSave={(newParams) => handleSaveNodeEdit(editingNode.id, newParams)}
          onClose={() => setEditingNode(null)}
        />
      )}

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          type={contextMenu.type}
          onAction={handleContextMenuAction}
          onClose={closeContextMenu}
        />
      )}
    </div>
  )
}

function DAGView(props) {
  return (
    <ReactFlowProvider>
      <DAGViewInner {...props} />
    </ReactFlowProvider>
  )
}

export default DAGView
