import React from 'react'
import { CheckCircle, Loader, XCircle, Clock } from 'lucide-react'
import './StatusBar.css'

function StatusBar({ currentStage, hasStarted, executionData, finalResult }) {
  const stages = [
    { key: 'idle', label: '待机', icon: Clock },
    { key: 'planning', label: '规划中', icon: Loader },
    { key: 'dag', label: '生成 DAG', icon: Loader },
    { key: 'executing', label: '执行中', icon: Loader },
    { key: 'completed', label: '已完成', icon: CheckCircle }
  ]

  const getStageIndex = (stage) => {
    const index = stages.findIndex(s => s.key === stage)
    return index === -1 ? 0 : index
  }

  const currentIndex = getStageIndex(currentStage)

  const getStageStatus = (index, stageKey) => {
    if (stageKey === 'completed') {
      if (currentStage === 'completed' && !finalResult?.error) {
        return 'completed'
      }
      if (finalResult?.error) {
        return 'error'
      }
    }

    // 特殊处理：如果已点击开始，idle阶段显示为completed
    if (stageKey === 'idle' && hasStarted) {
      return 'completed'
    }

    if (index < currentIndex) {
      return 'completed'
    }
    if (index === currentIndex) {
      return finalResult?.error ? 'error' : 'active'
    }
    return 'pending'
  }

  const getProgress = () => {
    if (currentStage === 'idle' && !hasStarted) return 0
    if (currentStage === 'idle' && hasStarted) {
      // 已点击开始但还没到planning，显示idle完成的进度
      return (1 / stages.length) * 100
    }
    return ((currentIndex + 1) / stages.length) * 100
  }

  const failureCount = executionData.filter(e => e.status === 'failed').length

  return (
    <div className={`status-bar ${finalResult?.error ? 'error' : ''}`}>
      <div className="status-progress">
        <div 
          className="status-progress-fill" 
          style={{ width: `${getProgress()}%` }}
        />
      </div>
      
      <div className="status-stages">
        {stages.map((stage, index) => {
          const status = getStageStatus(index, stage.key)
          const Icon = stage.icon
          
          return (
            <div key={stage.key} className={`status-stage ${status}`}>
              <div className="status-stage-icon">
                {status === 'completed' && !finalResult?.error ? (
                  <CheckCircle size={20} />
                ) : status === 'active' ? (
                  <Loader size={20} className="spinning" />
                ) : status === 'error' ? (
                  <XCircle size={20} />
                ) : (
                  <Icon size={20} />
                )}
              </div>
              <span className="status-stage-label">{stage.label}</span>
            </div>
          )
        })}
      </div>

      {executionData.length > 0 && (
        <div className="status-summary">
          <span className="status-summary-item">
            {'节点'} {executionData.length}
          </span>
          <span className="status-summary-item success">
            {'成功'} {executionData.filter(e => e.status === 'success').length}
          </span>
          {failureCount > 0 && (
            <span className="status-summary-item failed">
              {'失败'} {failureCount}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

export default StatusBar
