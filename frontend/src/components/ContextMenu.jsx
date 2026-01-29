import React, { useEffect, useRef } from 'react'
import { Trash2, Edit3, Plus, Cpu, Wrench, Shield } from 'lucide-react'
import './ContextMenu.css'

function ContextMenu({ x, y, type, onAction, onClose }) {
  const menuRef = useRef(null)

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        onClose()
      }
    }

    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [onClose])

  // 调整菜单位置，确保不超出视口
  const adjustedPosition = {
    left: Math.min(x, window.innerWidth - 180),
    top: Math.min(y, window.innerHeight - 200)
  }

  return (
    <div
      ref={menuRef}
      className="context-menu"
      style={adjustedPosition}
    >
      {type === 'node' && (
        <>
          <div className="context-menu-item" onClick={() => onAction('edit')}>
            <Edit3 size={14} />
            <span>编辑节点</span>
          </div>
          <div className="context-menu-divider" />
          <div className="context-menu-item danger" onClick={() => onAction('delete')}>
            <Trash2 size={14} />
            <span>删除节点</span>
          </div>
        </>
      )}

      {type === 'edge' && (
        <div className="context-menu-item danger" onClick={() => onAction('delete')}>
          <Trash2 size={14} />
          <span>删除连接</span>
        </div>
      )}

      {type === 'pane' && (
        <>
          <div className="context-menu-header">添加节点</div>
          <div className="context-menu-item" onClick={() => onAction('add-llm')}>
            <Cpu size={14} />
            <span>LLM 节点</span>
          </div>
          <div className="context-menu-item" onClick={() => onAction('add-tool')}>
            <Wrench size={14} />
            <span>工具节点</span>
          </div>
          <div className="context-menu-item" onClick={() => onAction('add-guard')}>
            <Shield size={14} />
            <span>Guard 节点</span>
          </div>
        </>
      )}
    </div>
  )
}

export default ContextMenu
