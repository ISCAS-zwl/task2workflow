import React, { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, CheckCircle, XCircle, Loader, Clock } from 'lucide-react'
import './ExecutionSteps.css'

function ExecutionSteps({ data }) {
  const [expandedSteps, setExpandedSteps] = useState(new Set())
  const timelineRef = useRef(null)

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

  if (!data || data.length === 0) {
    return (
      <div className="empty-state">
        <Clock size={48} className="empty-icon" />
        <p>{'等待工作流执行...'}</p>
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
        {data.map((step, index) => {
          const isExpanded = expandedSteps.has(step.node_id)
          const isLast = index === data.length - 1

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
