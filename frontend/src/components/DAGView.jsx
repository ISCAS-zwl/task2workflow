import React, { useMemo, useState } from 'react'
import ReactFlow, { Background, Controls, MarkerType, Handle, Position } from 'reactflow'
import 'reactflow/dist/style.css'
import { Network } from 'lucide-react'
import NodeEditDialog from './NodeEditDialog'
import './DAGView.css'

function CustomNode({ data }) {
  const statusClass = data.status || 'pending'
  const isLLM = data.executor === 'llm'
  const isEdited = data.isEdited || false
  const hasActualInput = data.actualInput !== undefined

  // 提取要显示的参数
  const getDisplayParams = () => {
    if (!data.input) return null
    
    // LLM 节点：显示 prompt
    if (isLLM) {
      const prompt = data.input.prompt
      if (!prompt) return null
      
      return {
        prompt: typeof prompt === 'string' 
          ? prompt 
          : JSON.stringify(prompt)
      }
    }
    
    // 工具节点：过滤掉内部字段
    const filtered = { ...data.input }
    delete filtered.__from_guard__
    delete filtered._param_overrides
    
    // 如果没有参数，不显示
    if (Object.keys(filtered).length === 0) return null
    
    return filtered
  }
  
  const displayParams = getDisplayParams()

  return (
    <div className={`custom-node ${statusClass} ${isEdited ? 'edited' : ''}`}>
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
  const maxLevel = Math.max(...Array.from(levelBuckets.keys()))
  
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

function DAGView({ data, executionData, editMode, onParamOverridesChange, paramOverrides }) {
  const [editingNode, setEditingNode] = useState(null)
  const { nodes, edges } = useMemo(() => {
    if (!data) {
      return { nodes: [], edges: [] }
    }

    const nodeSource = Array.isArray(data.nodes) ? data.nodes : []
    const explicitEdges = Array.isArray(data.edges) ? data.edges : []

    // ---------------------------------------
    // 修复方案 D：优先用 edges，缺失时从节点内部 source/target 构建
    // ---------------------------------------
    let derivedEdges = []

    if (!explicitEdges.length) {
      derivedEdges = nodeSource.flatMap(node => {
        const edges = []

        // 支持 node.source
        if (node.source && node.source !== 'null') {
          edges.push({
            source: node.source,
            target: node.id
          })
        }

        // 支持 node.target
        if (node.target && node.target !== 'null') {
          edges.push({
            source: node.id,
            target: node.target
          })
        }

        return edges
      })
    }

    // 选择 explicitEdges 或 derivedEdges
    const edgeSource = explicitEdges.length ? explicitEdges : derivedEdges

    // 去重，避免重复边
    const uniqueEdgeMap = new Map()
    edgeSource.forEach(edge => {
      const key = `${edge.source}-${edge.target}`
      uniqueEdgeMap.set(key, edge)
    })
    const cleanEdgeSource = Array.from(uniqueEdgeMap.values())

    console.log('[DAGView] Edge construction:', {
      explicitEdges: explicitEdges.length,
      derivedEdges: derivedEdges.length,
      cleanEdges: cleanEdgeSource.length,
      edges: cleanEdgeSource
    })

    // ---------------------------------------
    // Execution 状态映射
    // ---------------------------------------
    const executionMap = new Map()
    executionData?.forEach(exec => {
      executionMap.set(exec.node_id, exec)
    })

    // ---------------------------------------
    // 布局
    // ---------------------------------------
    const positions = buildLayout(nodeSource, cleanEdgeSource)

    // ---------------------------------------
    // 构造可视化节点
    // ---------------------------------------
    const nodeList = nodeSource.map((node, index) => {
      const exec = executionMap.get(node.id)
      const isEdited = paramOverrides && paramOverrides[node.id]
      
      // 显示策略调整：
      // 1. 如果节点已执行：始终显示实际参数（编辑时也基于实际参数）
      // 2. 如果节点未执行：显示规划参数
      let displayData = { ...node }
      let hasActualInput = false
      
      // 调试信息
      if (exec && node.id === nodeSource[0]?.id) {
        console.log('[DAGView] Node:', node.id)
        console.log('[DAGView] exec.status:', exec?.status)
        console.log('[DAGView] editMode:', editMode)
        console.log('[DAGView] exec.input:', exec?.input)
        console.log('[DAGView] node.input (original):', node.input)
      }
      
      // 只要节点执行完成（成功或失败），就使用实际参数
      if (exec && exec.status !== 'running') {
        if (exec.input) {
          displayData.input = exec.input
          hasActualInput = true
          
          // 调试：确认覆盖生效
          if (node.id === nodeSource[0]?.id) {
            console.log('[DAGView] Using actual params. displayData.input:', displayData.input)
          }
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

    // ---------------------------------------
    // 构造可视化边
    // ---------------------------------------
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
      },
      labelStyle: {
        fill: '#7d8590',
        fontSize: 12
      }
    }))

    return { nodes: nodeList, edges: edgeList }
  }, [data, executionData, paramOverrides, editMode])
  
  const handleNodeClick = (event, node) => {
    if (editMode) {
      // 找到原始节点数据
      const originalNode = data?.nodes?.find(n => n.id === node.id)
      if (originalNode) {
        // 如果节点已执行，使用实际参数；否则使用规划参数
        const exec = executionData?.find(e => e.node_id === node.id)
        const nodeToEdit = { ...originalNode }
        
        if (exec && exec.status !== 'running' && exec.input) {
          // 用实际执行的参数覆盖规划参数
          nodeToEdit.input = exec.input
          console.log('[DAGView] Editing with actual params:', exec.input)
        } else {
          console.log('[DAGView] Editing with planned params:', originalNode.input)
        }
        
        setEditingNode(nodeToEdit)
      }
    }
  }
  
  const handleSaveNodeEdit = (nodeId, newParams) => {
    const updatedOverrides = { ...paramOverrides, [nodeId]: newParams }
    onParamOverridesChange(updatedOverrides)
    setEditingNode(null)
  }

  if (!data) {
    return (
      <div className="empty-state">
        <Network size={48} className="empty-icon" />
        <p>{'等待 DAG 图生成...'}</p>
      </div>
    )
  }

  return (
    <div className="dag-view">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3, minZoom: 0.4, maxZoom: 1.5 }}
        attributionPosition="bottom-right"
        style={{ width: '100%', height: '100%' }}
        onNodeClick={handleNodeClick}
        nodesDraggable={true}
        nodesConnectable={false}
        elementsSelectable={editMode}
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
    </div>
  )
}

export default DAGView
