import React from 'react'
import { FileText, CheckCircle, XCircle, Loader, Layers, AlertTriangle } from 'lucide-react'
import './PlanningView.css'

const EmptyState = ({ icon: Icon = FileText, title, hint }) => (
  <div className="empty-state">
    <Icon size={48} className="empty-icon" />
    <p>{title}</p>
    {hint && <span className="empty-hint">{hint}</span>}
  </div>
)

const stages = [
  { key: 'raw_json', label: '生成 JSON', icon: FileText },
  { key: 'fixed_json', label: 'JSON 修复', icon: CheckCircle },
  { key: 'workflow_ir', label: '输出 WorkflowIR', icon: Layers }
]

function JsonPlanningView({ data }) {
  return (
    <div className="planning-view json-mode">
      <div className="stages-timeline">
        {stages.map((stage, index) => {
          const hasData = Boolean(data[stage.key])
          const Icon = hasData ? CheckCircle : stage.key === data.current_stage ? Loader : stage.icon
          const status = hasData ? 'completed' : stage.key === data.current_stage ? 'active' : 'pending'

          return (
            <React.Fragment key={stage.key}>
              <div className={`stage-item ${status}`}>
                <Icon className="stage-icon" size={18} />
                <span className="stage-label">{stage.label}</span>
              </div>
              {index < stages.length - 1 && <div className="stage-line" />}
            </React.Fragment>
          )
        })}
      </div>

      <div className="planning-content">
        {data.raw_json && (
          <div className="planning-section">
            <h3 className="section-title">原始 JSON</h3>
            <pre className="code-block">{data.raw_json}</pre>
          </div>
        )}

        {data.fixed_json && (
          <div className="planning-section">
            <h3 className="section-title">修复后的 JSON</h3>
            <pre className="code-block">{JSON.stringify(data.fixed_json, null, 2)}</pre>
          </div>
        )}

        {data.workflow_ir && (
          <div className="planning-section">
            <h3 className="section-title">WorkflowIR 预览</h3>
            <div className="workflow-summary">
              <div className="summary-item">
                <span className="summary-label">节点数量</span>
                <span className="summary-value">{data.workflow_ir.nodes?.length || 0}</span>
              </div>
              <div className="summary-item">
                <span className="summary-label">边数量</span>
                <span className="summary-value">{data.workflow_ir.edges?.length || 0}</span>
              </div>
            </div>
            <pre className="code-block">{JSON.stringify(data.workflow_ir, null, 2)}</pre>
          </div>
        )}

        {data.error && (
          <div className="error-message">
            <AlertTriangle size={16} />
            <span>{data.error}</span>
          </div>
        )}
      </div>
    </div>
  )
}

function WorkflowIRView({ workflow }) {
  if (!workflow) {
    return (
      <div className="planning-view workflow-mode">
        <EmptyState 
          icon={Layers} 
          title="等待 WorkflowIR 生成..." 
          hint="执行规划结束后将展现节点依赖与输入输出。" 
        />
      </div>
    )
  }

  const nodes = workflow.nodes || []
  const edges = workflow.edges || []

  const llmCount = nodes.filter(node => node.executor === 'llm').length
  const toolCount = nodes.filter(node => node.executor === 'tool').length
  const entryNodes = nodes.filter(node => node.source === 'null' || !edges.some(edge => edge.target === node.id))
  const exitNodes = nodes.filter(node => node.target === 'null' || !edges.some(edge => edge.source === node.id))

  const formatParameter = (parameter) => {
    if (parameter === undefined || parameter === null) return '{}'
    return typeof parameter === 'string'
      ? parameter
      : JSON.stringify(parameter, null, 2)
  }

  const getUpstream = (node) => {
    const preOutput = node.input?.pre_output
    if (!preOutput || preOutput === 'null') return '无'
    return preOutput.split('.')[0]
  }

  return (
    <div className="planning-view workflow-mode">
      <div className="workflow-stats-grid">
        <div className="workflow-stat-card">
          <span className="stat-label">节点总数</span>
          <span className="stat-value">{nodes.length}</span>
        </div>
        <div className="workflow-stat-card">
          <span className="stat-label">边数量</span>
          <span className="stat-value">{edges.length}</span>
        </div>
        <div className="workflow-stat-card">
          <span className="stat-label">TOOL / LLM</span>
          <span className="stat-value">{toolCount} / {llmCount}</span>
        </div>
        <div className="workflow-stat-card">
          <span className="stat-label">入口 / 出口</span>
          <span className="stat-value">{entryNodes.length} / {exitNodes.length}</span>
        </div>
      </div>

      <div className="workflow-nodes-grid">
        {nodes.map(node => (
          <div key={node.id} className="workflow-node-card">
            <div className="workflow-node-header">
              <div>
                <span className="workflow-node-id">{node.id}</span>
                <h4>{node.name || '未命名节点'}</h4>
              </div>
              <span className={`node-badge ${node.executor}`}>
                {node.executor === 'llm' ? 'LLM' : 'TOOL'}
              </span>
            </div>

            <p className="workflow-node-desc">{node.description || '暂无描述'}</p>

            <div className="node-info-row">
              <div>
                <span className="info-label">工具 / 模型</span>
                <span className="info-value">{node.tool_name || '内置模型'}</span>
              </div>
              <div>
                <span className="info-label">依赖节点</span>
                <span className="info-value">{getUpstream(node)}</span>
              </div>
            </div>

            <div className="node-io-block">
              <span className="info-label">参数</span>
              <pre className="info-code">{formatParameter(node.input?.parameter)}</pre>
            </div>

            {node.output && (
              <div className="node-io-block">
                <span className="info-label">输出期望</span>
                <p className="info-text">{node.output}</p>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function PlanningView({ data, mode = 'json' }) {
  if (!data) {
    return (
      <div className="planning-view">
        <EmptyState 
          title={mode === 'workflow' ? '等待 WorkflowIR 生成...' : '等待规划结果...'} 
          hint="当后端开始规划后，这里会实时显示结构化数据。" 
        />
      </div>
    )
  }

  if (mode === 'workflow') {
    return <WorkflowIRView workflow={data.workflow_ir} />
  }

  return <JsonPlanningView data={data} />
}

export default PlanningView
