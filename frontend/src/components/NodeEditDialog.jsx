import React, { useState, useEffect } from 'react'
import { X, Save, AlertCircle } from 'lucide-react'
import './NodeEditDialog.css'

function NodeEditDialog({ node, onSave, onClose }) {
  const [formData, setFormData] = useState({})
  const [jsonError, setJsonError] = useState(null)
  const [jsonMode, setJsonMode] = useState(false)
  const [jsonText, setJsonText] = useState('')

  useEffect(() => {
    if (!node) return
    
    // 提取当前节点的参数
    let currentParams = {}
    
    if (node.executor === 'tool') {
      // 工具节点：从 input 中提取（排除特殊字段）
      const input = node.input || {}
      currentParams = { ...input }
      delete currentParams.__from_guard__
      delete currentParams.__from_guards__
      delete currentParams._param_overrides
    } else if (node.executor === 'llm') {
      // LLM 节点：从 input 中提取
      const input = node.input || {}
      if (typeof input === 'object') {
        currentParams = { ...input }
      } else {
        currentParams = { prompt: input }
      }
    } else if (node.executor === 'param_guard') {
      // param_guard 节点：从 target_input_template 提取
      currentParams = node.input?.target_input_template || {}
    }
    
    setFormData(currentParams)
    setJsonText(JSON.stringify(currentParams, null, 2))
  }, [node])

  const handleFieldChange = (key, value) => {
    setFormData(prev => ({ ...prev, [key]: value }))
  }

  const handleAddField = () => {
    const key = prompt('请输入新参数的名称:')
    if (key && key.trim()) {
      handleFieldChange(key.trim(), '')
    }
  }

  const handleRemoveField = (key) => {
    setFormData(prev => {
      const newData = { ...prev }
      delete newData[key]
      return newData
    })
  }

  const handleJsonChange = (text) => {
    setJsonText(text)
    try {
      const parsed = JSON.parse(text)
      setFormData(parsed)
      setJsonError(null)
    } catch (e) {
      setJsonError(e.message)
    }
  }

  const handleSave = () => {
    if (jsonMode && jsonError) {
      alert('JSON 格式错误，请修正后保存')
      return
    }
    onSave(formData)
  }

  const toggleJsonMode = () => {
    if (!jsonMode) {
      // 切换到 JSON 模式
      setJsonText(JSON.stringify(formData, null, 2))
      setJsonError(null)
    } else {
      // 切换回表单模式
      if (jsonError) {
        alert('JSON 格式错误，无法切换到表单模式')
        return
      }
    }
    setJsonMode(!jsonMode)
  }

  if (!node) return null

  return (
    <div className="node-edit-overlay" onClick={onClose}>
      <div className="node-edit-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <h3>编辑节点参数</h3>
            <p className="dialog-subtitle">
              {node.id} · {node.executor === 'llm' ? 'LLM' : node.executor === 'tool' ? 'TOOL' : 'GUARD'} · {node.name}
            </p>
          </div>
          <button className="close-button" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="dialog-body">
          <div className="mode-toggle">
            <button
              className={`toggle-btn ${!jsonMode ? 'active' : ''}`}
              onClick={() => jsonMode && toggleJsonMode()}
            >
              表单模式
            </button>
            <button
              className={`toggle-btn ${jsonMode ? 'active' : ''}`}
              onClick={() => !jsonMode && toggleJsonMode()}
            >
              JSON 模式
            </button>
          </div>

          {!jsonMode ? (
            <div className="form-mode">
              {Object.keys(formData).length === 0 ? (
                <div className="empty-hint">
                  <AlertCircle size={24} />
                  <p>当前节点没有可编辑的参数</p>
                  <button className="add-field-btn" onClick={handleAddField}>
                    添加参数
                  </button>
                </div>
              ) : (
                <div className="fields-list">
                  {Object.entries(formData).map(([key, value]) => (
                    <div key={key} className="field-row">
                      <label className="field-label">{key}</label>
                      <div className="field-input-group">
                        <input
                          type="text"
                          className="field-input"
                          value={typeof value === 'object' ? JSON.stringify(value) : value}
                          onChange={(e) => {
                            let newValue = e.target.value
                            // 尝试解析 JSON
                            try {
                              if (newValue.startsWith('{') || newValue.startsWith('[')) {
                                newValue = JSON.parse(newValue)
                              }
                            } catch {}
                            handleFieldChange(key, newValue)
                          }}
                          placeholder={`请输入 ${key} 的值`}
                        />
                        <button
                          className="remove-field-btn"
                          onClick={() => handleRemoveField(key)}
                          title="删除此参数"
                        >
                          <X size={16} />
                        </button>
                      </div>
                    </div>
                  ))}
                  <button className="add-field-btn" onClick={handleAddField}>
                    + 添加参数
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="json-mode">
              <textarea
                className={`json-textarea ${jsonError ? 'error' : ''}`}
                value={jsonText}
                onChange={(e) => handleJsonChange(e.target.value)}
                placeholder="请输入 JSON 格式的参数"
                spellCheck={false}
              />
              {jsonError && (
                <div className="json-error">
                  <AlertCircle size={16} />
                  <span>{jsonError}</span>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="dialog-footer">
          <button className="cancel-btn" onClick={onClose}>
            取消
          </button>
          <button className="save-btn" onClick={handleSave} disabled={jsonMode && jsonError}>
            <Save size={16} />
            保存修改
          </button>
        </div>
      </div>
    </div>
  )
}

export default NodeEditDialog
