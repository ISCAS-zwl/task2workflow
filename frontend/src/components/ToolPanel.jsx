import React, { useState, useEffect } from 'react'
import { ChevronDown, ChevronRight, Search, Cpu, Wrench, Shield, GripVertical } from 'lucide-react'
import './ToolPanel.css'

function ToolPanel({ onNodeCreate, editMode }) {
  const [tools, setTools] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [expandedSections, setExpandedSections] = useState({
    llm: true,
    tool: true,
    guard: false
  })

  useEffect(() => {
    fetchTools()
  }, [])

  const fetchTools = async () => {
    try {
      const response = await fetch('http://localhost:8000/tools')
      if (response.ok) {
        const data = await response.json()
        setTools(data)
      }
    } catch (error) {
      console.error('获取工具列表失败:', error)
    } finally {
      setLoading(false)
    }
  }

  const toggleSection = (section) => {
    setExpandedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }))
  }

  const handleDragStart = (event, nodeType, toolData = null) => {
    if (!editMode) {
      event.preventDefault()
      return
    }

    const nodeData = {
      type: nodeType,
      tool: toolData
    }

    event.dataTransfer.setData('application/reactflow', nodeType)
    event.dataTransfer.setData('nodeData', JSON.stringify(nodeData))
    event.dataTransfer.effectAllowed = 'move'
  }

  const filteredTools = tools.filter(tool =>
    tool.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    tool.description.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const truncateDescription = (desc, maxLen = 60) => {
    if (!desc) return ''
    // 提取第一行或第一句
    const firstLine = desc.split('\n')[0].split('。')[0]
    if (firstLine.length <= maxLen) return firstLine
    return firstLine.slice(0, maxLen) + '...'
  }

  if (!editMode) {
    return (
      <div className="tool-panel disabled">
        <div className="tool-panel-header">
          <h3>节点面板</h3>
        </div>
        <div className="tool-panel-hint">
          <p>请先进入编辑模式</p>
        </div>
      </div>
    )
  }

  return (
    <div className="tool-panel">
      <div className="tool-panel-header">
        <h3>节点面板</h3>
        <p>拖拽节点到画布</p>
      </div>

      <div className="tool-panel-search">
        <Search size={14} />
        <input
          type="text"
          placeholder="搜索工具..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      </div>

      <div className="tool-panel-content">
        {/* LLM 节点 */}
        <div className="tool-section">
          <div className="section-header" onClick={() => toggleSection('llm')}>
            {expandedSections.llm ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <Cpu size={14} />
            <span>LLM 节点</span>
          </div>
          {expandedSections.llm && (
            <div className="section-content">
              <div
                className="draggable-item llm"
                draggable
                onDragStart={(e) => handleDragStart(e, 'llm')}
              >
                <GripVertical size={12} className="drag-handle" />
                <div className="item-info">
                  <span className="item-name">LLM 节点</span>
                  <span className="item-desc">使用大语言模型处理任务</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Tool 节点 */}
        <div className="tool-section">
          <div className="section-header" onClick={() => toggleSection('tool')}>
            {expandedSections.tool ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <Wrench size={14} />
            <span>工具节点</span>
            <span className="section-count">{filteredTools.length}</span>
          </div>
          {expandedSections.tool && (
            <div className="section-content">
              {loading ? (
                <div className="loading-hint">加载中...</div>
              ) : filteredTools.length === 0 ? (
                <div className="empty-hint">
                  {searchTerm ? '未找到匹配的工具' : '暂无可用工具'}
                </div>
              ) : (
                filteredTools.map(tool => (
                  <div
                    key={tool.name}
                    className="draggable-item tool"
                    draggable
                    onDragStart={(e) => handleDragStart(e, 'tool', tool)}
                    title={tool.description}
                  >
                    <GripVertical size={12} className="drag-handle" />
                    <div className="item-info">
                      <span className="item-name">{tool.name}</span>
                      <span className="item-desc">{truncateDescription(tool.description)}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Guard 节点 */}
        <div className="tool-section">
          <div className="section-header" onClick={() => toggleSection('guard')}>
            {expandedSections.guard ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <Shield size={14} />
            <span>Guard 节点</span>
          </div>
          {expandedSections.guard && (
            <div className="section-content">
              <div
                className="draggable-item guard"
                draggable
                onDragStart={(e) => handleDragStart(e, 'param_guard')}
              >
                <GripVertical size={12} className="drag-handle" />
                <div className="item-info">
                  <span className="item-name">参数验证节点</span>
                  <span className="item-desc">验证和转换参数</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default ToolPanel
