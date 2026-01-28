import React, { useEffect, useMemo, useRef, useState } from 'react'
import StatusBar from './components/StatusBar'
import WorkflowTabs from './components/WorkflowTabs'
import ExecutionSteps from './components/ExecutionSteps'
import ResultView from './components/ResultView'
import WorkflowSaveDialog from './components/WorkflowSaveDialog'
import WorkflowBrowser from './components/WorkflowBrowser'
import { Play, Zap, Square, RotateCcw, Bug, Edit3, Check, Save, FolderOpen } from 'lucide-react'
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
  const [editMode, setEditMode] = useState(false)
  const [paramOverrides, setParamOverrides] = useState({})
  const [lastExecutedTask, setLastExecutedTask] = useState('')

  // 工作流保存和加载相关状态
  const [currentRunId, setCurrentRunId] = useState(null)
  const [loadedWorkflowName, setLoadedWorkflowName] = useState(null)
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [showBrowser, setShowBrowser] = useState(false)

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
        case 'run_id':
          setCurrentRunId(data.run_id)
          break
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
    setEditMode(false)
    setParamOverrides({})
    setCurrentRunId(null)
    setLoadedWorkflowName(null)
  }

  const handleStart = () => {
    if (!task.trim()) return

    // 检查是否是新任务
    const isNewTask = task !== lastExecutedTask

    // 如果有参数覆盖且任务变化，提示用户
    if (isNewTask && Object.keys(paramOverrides).length > 0) {
      const confirmed = confirm(
        `检测到任务输入已变化，将丢弃 ${Object.keys(paramOverrides).length} 个参数修改。\n\n` +
        `如需应用参数修改，请使用"应用修改"按钮。\n\n` +
        `是否继续执行新任务？`
      )
      if (!confirmed) return
    }

    // 准备消息
    const message = {
      type: 'start',
      task,
      debug: debugMode,
    }

    // 如果有加载的工作流图且任务没变，直接使用工作流图执行（跳过规划）
    if (dagData && !isNewTask && loadedWorkflowName) {
      message.workflow_graph = dagData
      console.log('使用已加载的工作流图执行，跳过规划阶段')
    }

    // 清空执行状态但保留 DAG 数据
    setPlanningData(null)
    setExecutionData([])
    setFinalResult(null)
    setEditMode(false)
    setParamOverrides({})

    // 如果是新任务，清空之前的工作流信息
    if (isNewTask) {
      setDagData(null)
      setLoadedWorkflowName(null)
      setCurrentRunId(null)
    }

    setLastExecutedTask(task)
    setCurrentStage('idle')

    // run_id 将由后端生成并通过 WebSocket 返回
    sendMessage(message)
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
  
  const toggleEditMode = () => {
    if (currentStage === 'executing' || currentStage === 'planning') {
      alert('工作流正在执行中，无法编辑')
      return
    }
    setEditMode(prev => !prev)
  }
  
  const handleApplyEdits = () => {
    const editCount = Object.keys(paramOverrides).length
    if (editCount === 0) {
      alert('没有参数修改需要应用')
      return
    }

    if (!lastExecutedTask) {
      alert('没有可重新执行的工作流')
      return
    }

    if (confirm(`确认应用 ${editCount} 个节点的参数修改并重新执行工作流？`)) {
      setEditMode(false)
      setCurrentStage('idle')

      // 清空之前的执行数据
      setExecutionData([])
      setFinalResult(null)

      // 使用上次的任务 + 参数覆盖
      sendMessage({
        type: 'start',
        task: lastExecutedTask,
        debug: debugMode,
        param_overrides: paramOverrides
      })
    }
  }

  // 保存工作流
  const handleSaveWorkflow = async (name, description) => {
    if (!currentRunId) {
      throw new Error('没有可保存的工作流执行记录')
    }

    try {
      const response = await fetch('http://localhost:8000/workflows', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          run_id: currentRunId,
          name,
          description,
        }),
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || '保存失败')
      }

      const result = await response.json()
      setShowSaveDialog(false)
      setLoadedWorkflowName(name)
      alert(`工作流 "${name}" 保存成功！`)
    } catch (error) {
      throw error
    }
  }

  // 加载工作流
  const handleLoadWorkflow = async (workflowId) => {
    try {
      const response = await fetch(`http://localhost:8000/workflows/${workflowId}`)

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || '加载失败')
      }

      const workflow = await response.json()

      // 重置当前状态
      resetWorkflowState()

      // 设置加载的工作流数据
      setTask(workflow.task)
      setLastExecutedTask(workflow.task)
      setDagData(workflow.graph)
      setCurrentStage('dag')
      setLoadedWorkflowName(workflow.saved_as)
      setCurrentRunId(workflow.run_id || workflow.id)  // 使用 run_id，如果没有则使用 id

      // 如果有执行结果，也显示出来
      if (workflow.result?.outputs) {
        setFinalResult({
          outputs: workflow.result.outputs,
          error: workflow.result.error,
        })
        setCurrentStage('completed')
      }

      setShowBrowser(false)
      alert(`工作流 "${workflow.saved_as}" 加载成功！\n\n✓ 点击"开始执行"将直接使用已保存的工作流图执行（跳过规划）\n✓ 你可以使用"编辑工作流"修改参数\n✓ 如果修改了任务描述，将重新规划工作流`)
    } catch (error) {
      throw error
    }
  }

  const progressText = useMemo(() => {
    // 在规划和 DAG 阶段显示不同的进度信息
    if (currentStage === 'planning') {
      if (planningData?.current_stage === 'raw_json') {
        return '生成规划'
      } else if (planningData?.current_stage === 'workflow_ir') {
        return '规划完成'
      } else {
        return '规划中...'
      }
    }

    if (currentStage === 'dag') {
      return '生成 DAG'
    }

    // 执行阶段显示节点进度
    if (workflowStats.totalNodes) {
      return `${workflowStats.completedNodes}/${workflowStats.totalNodes}`
    }

    return '--'
  }, [currentStage, planningData, workflowStats])

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
              className="ghost-button"
              onClick={() => setShowBrowser(true)}
            >
              <FolderOpen size={14} />
              打开工作流
            </button>
            <button
              className="ghost-button"
              onClick={() => setShowSaveDialog(true)}
              disabled={!currentRunId || currentStage === 'executing' || currentStage === 'planning'}
              title={!currentRunId ? '请先执行一个工作流' : '保存当前工作流'}
            >
              <Save size={14} />
              保存工作流
            </button>
            <button
              className={`ghost-button toggle ${editMode ? 'active' : ''}`}
              onClick={toggleEditMode}
              disabled={!dagData || currentStage === 'executing' || currentStage === 'planning'}
            >
              <Edit3 size={14} />
              {editMode ? '编辑中' : '编辑工作流'}
            </button>
            {editMode && Object.keys(paramOverrides).length > 0 && (
              <button
                className="ghost-button apply-edits"
                onClick={handleApplyEdits}
              >
                <Check size={14} />
                应用修改 ({Object.keys(paramOverrides).length})
              </button>
            )}
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
              editMode={editMode}
              onParamOverridesChange={setParamOverrides}
              paramOverrides={paramOverrides}
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

      {/* 工作流保存对话框 */}
      {showSaveDialog && (
        <WorkflowSaveDialog
          currentRunId={currentRunId}
          loadedWorkflowName={loadedWorkflowName}
          onSave={handleSaveWorkflow}
          onClose={() => setShowSaveDialog(false)}
        />
      )}

      {/* 工作流浏览器 */}
      {showBrowser && (
        <WorkflowBrowser
          onLoadWorkflow={handleLoadWorkflow}
          onClose={() => setShowBrowser(false)}
        />
      )}
    </div>
  )
}

export default App
