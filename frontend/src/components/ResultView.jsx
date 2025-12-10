import React, { useMemo, useState } from 'react'
import { Award, FileText, Copy, Check, AlertTriangle } from 'lucide-react'
import './ResultView.css'

function ResultView({ data }) {
  const [viewMode, setViewMode] = useState('text')
  const [copied, setCopied] = useState(false)

  const lastNode = useMemo(() => {
    if (!data?.outputs || Object.keys(data.outputs).length === 0) return null
    const nodeIds = Object.keys(data.outputs).sort()
    const lastNodeId = nodeIds[nodeIds.length - 1]
    return { id: lastNodeId, output: data.outputs[lastNodeId] }
  }, [data])

  const parsedOutput = useMemo(() => {
    if (!lastNode) return { raw: '', json: null }
    if (typeof lastNode.output === 'string') {
      try {
        const json = JSON.parse(lastNode.output)
        return { raw: lastNode.output, json }
      } catch {
        return { raw: lastNode.output, json: null }
      }
    }
    return { raw: JSON.stringify(lastNode.output, null, 2), json: lastNode.output }
  }, [lastNode])

  const displayContent = viewMode === 'json' && parsedOutput.json
    ? JSON.stringify(parsedOutput.json, null, 2)
    : parsedOutput.raw

  const copyContent = displayContent || ''

  const handleCopy = async () => {
    if (!copyContent) return
    try {
      await navigator.clipboard.writeText(copyContent)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch (err) {
      console.error('copy failed', err)
    }
  }

  if (!data) {
    return (
      <div className="empty-state">
        <Award size={48} className="empty-icon" />
        <p>{'等待工作流完成...'}</p>
      </div>
    )
  }

  if (data.error) {
    return (
      <div className="result-view">
        <div className="error-message-box">
          <div className="error-icon-wrapper">
            <AlertTriangle size={20} />
          </div>
          <div className="error-text">
            <div className="error-title">{'执行失败'}</div>
            <pre className="error-detail">{data.error}</pre>
          </div>
        </div>
      </div>
    )
  }

  if (!lastNode) {
    return (
      <div className="empty-state">
        <FileText size={48} className="empty-icon" />
        <p>{'暂无输出结果'}</p>
      </div>
    )
  }

  return (
    <div className="result-view">
      <div className="result-toolbar">
        <div>
          <span className="result-label">ID</span>
          <span className="result-value">{lastNode.id}</span>
        </div>
        <div className="result-actions">
          <div className="view-toggle">
            <button
              className={viewMode === 'text' ? 'active' : ''}
              onClick={() => setViewMode('text')}
            >
              {'纯文本'}
            </button>
            <button
              className={viewMode === 'json' ? 'active' : ''}
              onClick={() => setViewMode('json')}
              disabled={!parsedOutput.json}
            >
              JSON
            </button>
          </div>
          <button className="copy-button" onClick={handleCopy} disabled={!copyContent}>
            {copied ? <Check size={16} /> : <Copy size={16} />}
            {copied ? '已复制' : '复制'}
          </button>
        </div>
      </div>

      <div className="result-output">
        <pre className="result-content">{displayContent}</pre>
      </div>
    </div>
  )
}

export default ResultView
