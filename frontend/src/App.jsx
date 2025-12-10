import React, { useEffect, useMemo, useRef, useState } from 'react'
import StatusBar from './components/StatusBar'
import WorkflowTabs from './components/WorkflowTabs'
import ExecutionSteps from './components/ExecutionSteps'
import ResultView from './components/ResultView'
import { Play, Zap, Square, RotateCcw, Bug } from 'lucide-react'
import './App.css'

function App() {
  const [task, setTask] = useState('')
  const [currentStage, setCurrentStage] = useState('idle')
  const [planningData, setPlanningData] = useState(null)
  const [dagData, setDagData] = useState(null)
  const [executionData, setExecutionData] = useState([])
  const [finalResult, setFinalResult] = useState(null)
  const [debugMode, setDebugMode] = useState(true)
  const [stopRequested, setStopRequested] = useState(false)
  const wsRef = useRef(null)

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws')
    wsRef.current = ws

    ws.onopen = () => {
      console.log('WebSocket 连接已建立')
      setStopRequested(false)
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      console.log('收到消息:', data)

      switch (data.type) {
        case 'stage':
          setCurrentStage(data.stage)
          break
        case 'planning':
          setPlanningData(data.data)
          if (data.data?.workflow_ir) {
            setDagData(data.data.workflow_ir)
          }
          break
        case 'dag':
          setDagData(data.data)
          break
        case 'execution':
          setExecutionData(prev => [...prev, data.data])
          break
        case 'result':
          setFinalResult(data.data)
          setCurrentStage('completed')
          break
        case 'error':
          setCurrentStage('completed')
          setFinalResult(prev => ({
            outputs: prev?.outputs || {},
            error: data.message || '执行失败，请检查后端日志。'
          }))
          break
        default:
          break
      }
    }

    ws.onerror = (error) => {
      console.error('WebSocket 错误:', error)
    }

    ws.onclose = () => {
      console.log('WebSocket 连接已关闭')
    }

    return () => {
      ws.close()
    }
  }, [])

  useEffect(() => {
    if (!dagData && planningData?.workflow_ir) {
      setDagData(planningData.workflow_ir)
    }
  }, [dagData, planningData])

  const workflowStats = useMemo(() => {
    const totalNodes =
      dagData?.nodes?.length ||
      finalResult?.total_nodes ||
      executionData.length

    const successNodes = executionData.filter(step => step.status === 'success').length
    const failedNodes = executionData.filter(step => step.status === 'failed').length
    const runningNodes = executionData.filter(step => step.status === 'running').length
    const completedNodes = successNodes + failedNodes

    const firstStart = executionData.find(step => step.start_time)?.start_time
    const lastEnd = [...executionData].reverse().find(step => step.end_time)?.end_time

    let durationText = '--'
    if (firstStart && lastEnd) {
      const startTs = new Date(firstStart).getTime()
      const endTs = new Date(lastEnd).getTime()
      const diff = Math.max(endTs - startTs, 0)
      if (!Number.isNaN(diff)) {
        durationText = diff < 1000 ? `${diff} ms` : `${(diff / 1000).toFixed(1)} s`
      }
    }

    return {
      totalNodes,
      successNodes,
      failedNodes,
      runningNodes,
      completedNodes,
      durationText
    }
  }, [dagData, executionData, finalResult])

  const stageNameMap = {
    idle: '待机',
    planning: '规划中',
    dag: '生成 DAG',
    executing: '执行中',
    completed: finalResult?.error ? '执行失败' : '已完成'
  }

  const stageToneMap = {
    idle: 'idle',
    planning: 'running',
    dag: 'running',
    executing: 'running',
    completed: finalResult?.error ? 'error' : 'success'
  }

  const statusTone = stageToneMap[currentStage] || 'idle'
  const statusLabel = stageNameMap[currentStage] || '准备中'

  const sendMessage = (payload) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload))
    }
  }

  const resetWorkflowState = () => {
    setPlanningData(null)
    setDagData(null)
    setExecutionData([])
    setFinalResult(null)
  }

  const handleStart = () => {
    if (!task.trim()) return
    resetWorkflowState()
    setCurrentStage('idle')
    sendMessage({
      type: 'start',
      task,
      debug: debugMode
    })
  }

  const handleStop = () => {
    setStopRequested(true)
    sendMessage({ type: 'stop' })
  }

  const handleClear = () => {
    resetWorkflowState()
    setCurrentStage('idle')
    setStopRequested(false)
  }

  const progressText = workflowStats.totalNodes
    ? `${workflowStats.completedNodes}/${workflowStats.totalNodes}`
    : '--'

  const graphData = dagData || planningData?.workflow_ir || null

  return (
    <div className="app">
      <div className="top-shell">
        <header className="header">
          <div className="header-left">
            <div className="logo-chip">
              <Zap className="logo-icon" size={22} />
            </div>
            <div>
              <h1>Task2Workflow 监控舱</h1>
              <p>流程拆解 · 节点运行 · 结果验收一站掌握</p>
            </div>
          </div>
          <div className="header-right">
            <input
              type="text"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="输入任务描述，⌘/Ctrl + Enter 即可启动"
              className="task-input"
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                  handleStart()
                }
              }}
            />
            <button onClick={handleStart} className="primary-button" disabled={!task.trim()}>
              <Play size={16} />
              开始执行
            </button>
          </div>
        </header>

        <section className="control-bar">
          <div className={`status-chip ${statusTone}`}>
            <span className="status-dose" />
            <div>
              <span className="status-label">任务状态</span>
              <div className="status-value">
                {statusLabel}
                {stopRequested && <span className="status-tag">已请求停止</span>}
                {finalResult?.error && <span className="status-tag danger">发现异常</span>}
              </div>
            </div>
          </div>

          <div className="metrics-block">
            <div className="metric-card">
              <span className="metric-label">总耗时</span>
              <span className="metric-value">{workflowStats.durationText}</span>
            </div>
            <div className="metric-card">
              <span className="metric-label">节点进度</span>
              <span className="metric-value">{progressText}</span>
            </div>
            <div className={`metric-card ${workflowStats.failedNodes ? 'danger' : ''}`}>
              <span className="metric-label">错误节点</span>
              <span className="metric-value">{workflowStats.failedNodes}</span>
            </div>
          </div>

          <div className="control-actions">
            <button className="ghost-button" onClick={handleStop}>
              <Square size={14} />
              停止
            </button>
            <button className="ghost-button" onClick={handleClear}>
              <RotateCcw size={14} />
              清屏
            </button>
            <button
              className={`ghost-button toggle ${debugMode ? 'active' : ''}`}
              onClick={() => setDebugMode(prev => !prev)}
            >
              <Bug size={14} />
              调试模式：{debugMode ? '开' : '关'}
            </button>
          </div>
        </section>

        <div className="status-bar-wrapper">
          <StatusBar 
            currentStage={currentStage}
            executionData={executionData}
            finalResult={finalResult}
          />
        </div>
      </div>

      <main className="workspace">
        <section className="panel structure-panel">
          <div className="panel-title">
            <div>
              <h2>流程结构与配置</h2>
              <p>在 DAG、JSON 与 WorkflowIR 之间自由切换</p>
            </div>
          </div>
          <div className="panel-body">
            <WorkflowTabs 
              dagData={graphData}
              planningData={planningData}
              executionData={executionData}
            />
          </div>
        </section>

        <section className="bottom-section">
          <div className="panel steps-panel">
            <div className="panel-title">
              <div>
                <h2>执行流水线</h2>
                <p>像流水线调试器一样逐步展开</p>
              </div>
              <span className="panel-subtitle">
                成功 {workflowStats.successNodes} · 运行中 {workflowStats.runningNodes} · 失败 {workflowStats.failedNodes}
              </span>
            </div>
            <div className="panel-body">
              <ExecutionSteps data={executionData} />
            </div>
          </div>

          <div className="panel result-panel">
            <div className="panel-title">
              <div>
                <h2>最终输出</h2>
                <p>更适合验证与分享的展示面板</p>
              </div>
            </div>
            <div className="panel-body">
              <ResultView data={finalResult} />
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
