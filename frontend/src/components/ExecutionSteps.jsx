import React, { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, CheckCircle, XCircle, Loader, Clock } from 'lucide-react'
import './ExecutionSteps.css'

function ExecutionSteps({ data, dagData }) {
  const [expandedSteps, setExpandedSteps] = useState(new Set())
  const timelineRef = useRef(null)

  // 拓扑排序函数
  const topologicalSort = (nodes, edges) => {
    const adjacency = new Map()
    const inDegree = new Map()

    // 初始化
    nodes.forEach(node => {
      adjacency.set(node.id, [])
      inDegree.set(node.id, 0)
    })

    // 构建邻接表和入度
    edges.forEach(edge => {
      if (!adjacency.has(edge.source)) {
        adjacency.set(edge.source, [])
      }
      adjacency.get(edge.source).push(edge.target)
      inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1)
    })

    // BFS 拓扑排序
    const queue = []
    const sorted = []

    inDegree.forEach((degree, nodeId) => {
      if (degree === 0) {
        queue.push(nodeId)
      }
    })

    while (queue.length > 0) {
      const current = queue.shift()
      sorted.push(current)
      const neighbours = adjacency.get(current) || []

      neighbours.forEach(target => {
        const nextDegree = (inDegree.get(target) || 0) - 1
        inDegree.set(target, nextDegree)
        if (nextDegree === 0) {
          queue.push(target)
        }
      })
    }

    return sorted
  }

  // 合并 DAG 节点和执行数据
  const allSteps = React.useMemo(() => {
    if (!dagData?.nodes || dagData.nodes.length === 0) {
      // 如果没有 DAG 数据，只显示已执行的节点
      return data || []
    }

    // 构建边列表
    const nodeSource = Array.isArray(dagData.nodes) ? dagData.nodes : []
    const explicitEdges = Array.isArray(dagData.edges) ? dagData.edges : []

    let edgeSource = []
    if (!explicitEdges.length) {
      // 从节点的 source/target 构建边
      edgeSource = nodeSource.flatMap(node => {
        const edges = []
        if (node.source && node.source !== 'null') {
          edges.push({ source: node.source, target: node.id })
        }
        if (node.target && node.target !== 'null') {
          edges.push({ source: node.id, target: node.target })
        }
        return edges
      })
    } else {
      edgeSource = explicitEdges
    }

    // 去重边
    const uniqueEdgeMap = new Map()
    edgeSource.forEach(edge => {
      const key = `${edge.source}-${edge.target}`
      uniqueEdgeMap.set(key, edge)
    })
    const cleanEdges = Array.from(uniqueEdgeMap.values())

    // 拓扑排序
    const sortedNodeIds = topologicalSort(nodeSource, cleanEdges)

    // 创建执行数据的映射，以便快速查找
    const executionMap = new Map()
    if (data) {
      data.forEach(exec => {
        executionMap.set(exec.node_id, exec)
      })
    }

    // 创建节点ID到节点的映射
    const nodeMap = new Map()
    nodeSource.forEach(node => {
      nodeMap.set(node.id, node)
    })

    // 按拓扑排序的顺序合并节点和执行数据
    return sortedNodeIds.map(nodeId => {
      const node = nodeMap.get(nodeId)
      const execData = executionMap.get(nodeId)

      if (execData) {
        // 如果有执行数据，使用执行数据
        return execData
      } else if (node) {
        // 如果没有执行数据，创建一个 pending 状态的节点
        return {
          node_id: node.id,
          node_name: node.data?.name || node.name || node.id,
          node_type: node.data?.executor || node.executor || 'unknown',
          status: 'pending',
          duration_ms: null,
          input: null,
          output: null,
          error: null,
          model: node.data?.model || node.model,
          tool_name: node.data?.tool_name || node.tool_name
        }
      }
      return null
    }).filter(Boolean)
  }, [dagData, data])

  useEffect(() => {
    if (!data || data.length === 0) return
    const lastStep = data[data.length - 1]
    if (lastStep.status === 'failed') {
      setExpandedSteps(prev => {
        if (prev.has(lastStep.node_id)) return prev
        const next = new Set(prev)
        next.add(lastStep.node_id)
        return next
      })
    }
    requestAnimationFrame(() => {
      const target = timelineRef.current?.lastElementChild
      target?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    })
  }, [data])

  if (!allSteps || allSteps.length === 0) {
    return (
      <div className="empty-state">
        <Clock size={48} className="empty-icon" />
        <p>{'等待工作流规划...'}</p>
      </div>
    )
  }

  const toggleStep = (nodeId) => {
    setExpandedSteps(prev => {
      const next = new Set(prev)
      if (next.has(nodeId)) {
        next.delete(nodeId)
      } else {
        next.add(nodeId)
      }
      return next
    })
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'running':
        return <Loader className="step-status-icon running" size={18} />
      case 'success':
        return <CheckCircle className="step-status-icon success" size={18} />
      case 'failed':
        return <XCircle className="step-status-icon failed" size={18} />
      default:
        return <Clock className="step-status-icon pending" size={18} />
    }
  }

  const formatDuration = (ms) => {
    if (!ms) return '--'
    if (ms < 1000) return `${Math.round(ms)} ms`
    return `${(ms / 1000).toFixed(2)} s`
  }

  return (
    <div className="execution-steps">
      <div className="steps-timeline" ref={timelineRef}>
        {allSteps.map((step, index) => {
          const isExpanded = expandedSteps.has(step.node_id)
          const isLast = index === allSteps.length - 1

          return (
            <div key={step.node_id} className={`step-item ${step.status}`}>
              <div className="step-line-container">
                <div className="step-line-dot">
                  {getStatusIcon(step.status)}
                </div>
                {!isLast && <div className="step-line-vertical" />}
              </div>

              <div className="step-content">
                <div 
                  className="step-header"
                  onClick={() => toggleStep(step.node_id)}
                >
                  <div className="step-header-left">
                    <span className="step-number">
                      {'步骤'} {index + 1}
                    </span>
                    <span className="step-id">{step.node_id}</span>
                    <span className="step-name">{step.node_name}</span>
                    <span className={`step-type ${step.node_type}`}>
                      {step.node_type === 'llm' ? 'LLM' : 'TOOL'}
                    </span>
                  </div>
                  <div className="step-header-right">
                    <span className="step-duration">
                      {'耗时'} {formatDuration(step.duration_ms)}
                    </span>
                    {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </div>
                </div>

                {isExpanded && (
                  <div className="step-details">
                    {step.status === 'pending' ? (
                      <div className="step-detail-item">
                        <span className="step-detail-value" style={{ color: '#7d8590', fontStyle: 'italic' }}>
                          该节点尚未执行
                        </span>
                      </div>
                    ) : (
                      <>
                        {step.model && (
                          <div className="step-detail-item">
                            <span className="step-detail-label">{'模型'}:</span>
                            <span className="step-detail-value">{step.model}</span>
                          </div>
                        )}
                        {step.tool_name && (
                          <div className="step-detail-item">
                            <span className="step-detail-label">{'工具'}:</span>
                            <span className="step-detail-value">{step.tool_name}</span>
                          </div>
                        )}

                        {step.input && (
                          <div className="step-detail-section">
                            <div className="step-detail-label">{'输入'}</div>
                            <pre className="step-detail-code">
                              {typeof step.input === 'string'
                                ? step.input
                                : JSON.stringify(step.input, null, 2)}
                            </pre>
                          </div>
                        )}

                        {step.output && (
                          <div className="step-detail-section">
                            <div className="step-detail-label">{'输出'}</div>
                            <pre className="step-detail-code">
                              {typeof step.output === 'string'
                                ? step.output
                                : JSON.stringify(step.output, null, 2)}
                            </pre>
                          </div>
                        )}

                        {step.error && (
                          <div className="step-detail-section error">
                            <div className="step-detail-label">{'错误'}</div>
                            <pre className="step-detail-code">{step.error}</pre>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default ExecutionSteps
