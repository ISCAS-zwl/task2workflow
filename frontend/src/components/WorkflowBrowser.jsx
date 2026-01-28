import React, { useState, useEffect } from 'react'
import { X, Search, FolderOpen, Layers, Calendar, AlertCircle, Loader } from 'lucide-react'
import './WorkflowBrowser.css'

function WorkflowBrowser({ onLoadWorkflow, onClose }) {
  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [loadingWorkflowId, setLoadingWorkflowId] = useState(null)

  useEffect(() => {
    fetchWorkflows()
  }, [])

  const fetchWorkflows = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch('http://localhost:8000/workflows')
      if (!response.ok) {
        throw new Error('获取工作流列表失败')
      }
      const data = await response.json()
      setWorkflows(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleLoadWorkflow = async (workflowId) => {
    setLoadingWorkflowId(workflowId)
    setError(null)
    try {
      await onLoadWorkflow(workflowId)
      // onLoadWorkflow 成功后会关闭对话框
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoadingWorkflowId(null)
    }
  }

  const filteredWorkflows = workflows.filter((workflow) => {
    if (!searchQuery.trim()) return true
    const query = searchQuery.toLowerCase()
    return (
      workflow.id.toLowerCase().includes(query) ||
      (workflow.task && workflow.task.toLowerCase().includes(query)) ||
      (workflow.saved_as && workflow.saved_as.toLowerCase().includes(query))
    )
  })

  const formatDate = (dateStr) => {
    if (!dateStr) return '未知时间'
    try {
      const date = new Date(dateStr)
      return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return dateStr
    }
  }

  return (
    <div className="workflow-browser-overlay" onClick={onClose}>
      <div className="workflow-browser-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <h3>工作流库</h3>
            <p className="dialog-subtitle">
              选择一个已保存的工作流进行加载和执行
            </p>
          </div>
          <button className="close-button" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="dialog-body">
          <div className="search-bar">
            <Search size={16} />
            <input
              type="text"
              className="search-input"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索工作流名称或任务..."
              autoFocus
            />
            {searchQuery && (
              <button className="clear-search" onClick={() => setSearchQuery('')}>
                <X size={16} />
              </button>
            )}
          </div>

          {error && (
            <div className="error-message">
              <AlertCircle size={16} />
              <span>{error}</span>
              <button className="retry-btn" onClick={fetchWorkflows}>
                重试
              </button>
            </div>
          )}

          <div className="workflow-list">
            {loading ? (
              <div className="loading-state">
                <Loader className="spinner" size={32} />
                <p>加载工作流中...</p>
              </div>
            ) : filteredWorkflows.length === 0 ? (
              <div className="empty-state">
                <FolderOpen size={48} />
                <h4>{searchQuery ? '未找到匹配的工作流' : '暂无保存的工作流'}</h4>
                <p>
                  {searchQuery
                    ? '尝试使用其他关键词搜索'
                    : '执行成功的工作流后可以保存为模板'}
                </p>
              </div>
            ) : (
              filteredWorkflows.map((workflow) => (
                <div key={workflow.id} className="workflow-card">
                  <div className="workflow-header">
                    <div className="workflow-icon">
                      <Layers size={20} />
                    </div>
                    <div className="workflow-info">
                      <h4 className="workflow-name" title={workflow.saved_as || workflow.id}>
                        {workflow.saved_as || workflow.id}
                      </h4>
                      <p className="workflow-task" title={workflow.task}>
                        {workflow.task || '无任务描述'}
                      </p>
                    </div>
                  </div>

                  <div className="workflow-meta">
                    <div className="meta-item">
                      <Calendar size={14} />
                      <span>{formatDate(workflow.saved_at)}</span>
                    </div>
                  </div>

                  <div className="workflow-actions">
                    <button
                      className="load-btn"
                      onClick={() => handleLoadWorkflow(workflow.id)}
                      disabled={loadingWorkflowId === workflow.id}
                    >
                      {loadingWorkflowId === workflow.id ? (
                        <>
                          <Loader className="spinner" size={16} />
                          加载中...
                        </>
                      ) : (
                        <>
                          <FolderOpen size={16} />
                          加载工作流
                        </>
                      )}
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="dialog-footer">
          <p className="footer-hint">
            共 {filteredWorkflows.length} 个工作流
            {searchQuery && ` (已过滤 ${workflows.length - filteredWorkflows.length} 个)`}
          </p>
          <button className="close-footer-btn" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}

export default WorkflowBrowser
