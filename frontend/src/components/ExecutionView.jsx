import React from 'react'
import { Activity, Clock, CheckCircle, XCircle, Loader } from 'lucide-react'
import './ExecutionView.css'

function ExecutionView({ data }) {
  if (!data || data.length === 0) {
    return (
      <div className="empty-state">
        <Activity size={48} className="empty-icon" />
        <p>等待工作流执行...</p>
      </div>
    )
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'running':
        return <Loader className="status-icon running" size={16} />
      case 'success':
        return <CheckCircle className="status-icon success" size={16} />
      case 'failed':
        return <XCircle className="status-icon failed" size={16} />
      default:
        return <Clock className="status-icon pending" size={16} />
    }
  }

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return ''
    const date = new Date(timestamp)
    return date.toLocaleTimeString('zh-CN', { hour12: false })
  }

  const formatDuration = (ms) => {
    if (ms < 1000) return `${Math.round(ms)}ms`
    return `${(ms / 1000).toFixed(2)}s`
  }

  return (
    <div className="execution-view">
      <div className="execution-list">
        {data.map((exec, index) => (
          <div key={index} className={`execution-item ${exec.status}`}>
            <div className="execution-header">
              <div className="execution-left">
                {getStatusIcon(exec.status)}
                <span className="execution-node">{exec.node_id}</span>
                <span className="execution-name">{exec.node_name}</span>
              </div>
              <div className="execution-right">
                {exec.duration_ms && (
                  <span className="execution-duration">
                    <Clock size={12} />
                    {formatDuration(exec.duration_ms)}
                  </span>
                )}
              </div>
            </div>

            <div className="execution-meta">
              <span className={`execution-type ${exec.node_type}`}>
                {exec.node_type === 'llm' ? 'LLM' : 'TOOL'}
              </span>
              {exec.model && (
                <span className="execution-model">{exec.model}</span>
              )}
              {exec.tool_name && (
                <span className="execution-tool">{exec.tool_name}</span>
              )}
              <span className="execution-time">
                {formatTimestamp(exec.start_time)}
              </span>
            </div>

            {exec.input && (
              <div className="execution-section">
                <div className="section-label">输入</div>
                <pre className="section-content input">
                  {typeof exec.input === 'string'
                    ? exec.input
                    : JSON.stringify(exec.input, null, 2)}
                </pre>
              </div>
            )}

            {exec.output && (
              <div className="execution-section">
                <div className="section-label">输出</div>
                <pre className="section-content output">
                  {typeof exec.output === 'string'
                    ? exec.output
                    : JSON.stringify(exec.output, null, 2)}
                </pre>
              </div>
            )}

            {exec.error && (
              <div className="execution-section">
                <div className="section-label error">错误</div>
                <pre className="section-content error">{exec.error}</pre>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default ExecutionView
