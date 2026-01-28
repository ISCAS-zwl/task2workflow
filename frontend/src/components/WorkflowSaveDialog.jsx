import React, { useState } from 'react'
import { X, Save, AlertCircle } from 'lucide-react'
import './WorkflowSaveDialog.css'

function WorkflowSaveDialog({ currentRunId, loadedWorkflowName, onSave, onClose }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  // 验证工作流名称
  const validateName = (name) => {
    if (!name || name.trim().length < 1) {
      return '名称至少需要1个字符'
    }
    if (name.length > 50) {
      return '名称不能超过50个字符'
    }
    // 检查是否包含文件系统不支持的字符
    if (/[<>:"/\\|?*]/.test(name)) {
      return '名称不能包含以下字符: < > : " / \\ | ? *'
    }
    return null
  }

  const handleSave = async () => {
    const validationError = validateName(name)
    if (validationError) {
      setError(validationError)
      return
    }

    if (description.length > 500) {
      setError('描述不能超过500个字符')
      return
    }

    setSaving(true)
    setError(null)

    try {
      await onSave(name.trim(), description.trim())
      // onSave 成功后会关闭对话框
    } catch (err) {
      setError(err.message || '保存失败')
      setSaving(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSave()
    }
  }

  const isNameValid = validateName(name) === null

  return (
    <div className="workflow-save-overlay" onClick={onClose}>
      <div className="workflow-save-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <h3>{loadedWorkflowName ? '另存为新工作流' : '保存工作流'}</h3>
            <p className="dialog-subtitle">
              {loadedWorkflowName
                ? `基于 "${loadedWorkflowName}" 创建新工作流`
                : '保存当前工作流以便日后复用'
              }
            </p>
          </div>
          <button className="close-button" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="dialog-body">
          <div className="form-field">
            <label className="field-label">
              工作流名称 <span className="required">*</span>
            </label>
            <input
              type="text"
              className={`field-input ${error && !isNameValid ? 'error' : ''}`}
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                setError(null)
              }}
              onKeyDown={handleKeyDown}
              placeholder="例如: 天气查询、火车订票、Weather Query"
              autoFocus
              disabled={saving}
            />
            <p className="field-hint">
              1-50个字符，支持中文、字母、数字等，不能包含 &lt; &gt; : " / \ | ? *
            </p>
          </div>

          <div className="form-field">
            <label className="field-label">描述（可选）</label>
            <textarea
              className="field-textarea"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="描述这个工作流的用途和特点..."
              rows={4}
              disabled={saving}
              maxLength={500}
            />
            <p className="field-hint">
              {description.length}/500 字符
            </p>
          </div>

          {error && (
            <div className="error-message">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}
        </div>

        <div className="dialog-footer">
          <button className="cancel-btn" onClick={onClose} disabled={saving}>
            取消
          </button>
          <button
            className="save-btn"
            onClick={handleSave}
            disabled={!isNameValid || saving}
          >
            <Save size={16} />
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default WorkflowSaveDialog
