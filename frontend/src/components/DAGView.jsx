import React, { useMemo } from 'react'
import ReactFlow, { Background, Controls, MarkerType } from 'reactflow'
import 'reactflow/dist/style.css'
import { Network } from 'lucide-react'
import './DAGView.css'

function CustomNode({ data }) {
  const statusClass = data.status || 'pending'
  const isLLM = data.executor === 'llm'

  return (
    <div className={`custom-node ${statusClass}`}>
      <div className="node-header">
        <span className={`node-type ${isLLM ? 'llm' : 'tool'}`}>
          {isLLM ? 'LLM' : 'TOOL'}
        </span>
        <span className="node-id">{data.id}</span>
      </div>
      <div className="node-body">
        <div className="node-name">{data.name}</div>
        {data.tool_name && (
          <div className="node-tool">{data.tool_name}</div>
        )}
        <div className="node-desc">{data.description}</div>
      </div>
      {data.duration && (
        <div className="node-footer">
          <span className="node-duration">{data.duration}ms</span>
        </div>
      )}
    </div>
  )
}

const nodeTypes = {
  custom: CustomNode
}

const HORIZONTAL_SPACING = 320
const VERTICAL_SPACING = 220

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
      bucket.forEach((nodeId, index) => {
        positions[nodeId] = {
          x: level * HORIZONTAL_SPACING,
          y: index * VERTICAL_SPACING
        }
      })
    })

  return positions
}

function DAGView({ data, executionData }) {
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
      return {
        id: String(node.id),
        type: 'custom',
        position: positions[node.id] || { x: index * 320 + 50, y: 100 },
        data: {
          ...node,
          status: exec?.status || 'pending',
          duration: exec?.duration_ms ? Math.round(exec.duration_ms) : null
        }
      }
    })

    // ---------------------------------------
    // 构造可视化边
    // ---------------------------------------
    const edgeList = cleanEdgeSource.map(edge => ({
      id: `${edge.source}-${edge.target}`,
      source: edge.source,
      target: edge.target,
      type: 'smoothstep',
      animated: true,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: '#58a6ff'
      },
      style: {
        stroke: '#58a6ff',
        strokeWidth: 2
      }
    }))

    return { nodes: nodeList, edges: edgeList }
  }, [data, executionData])

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
        attributionPosition="bottom-right"
        style={{ width: '100%', height: '100%' }}
      >
        <Background color="#30363d" gap={16} />
        <Controls />
      </ReactFlow>
    </div>
  )
}

export default DAGView
