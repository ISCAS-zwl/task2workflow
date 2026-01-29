import React, { useState } from 'react'
import DAGView from './DAGView'
import PlanningView from './PlanningView'
import ToolPanel from './ToolPanel'
import { Network, FileJson, Share2 } from 'lucide-react'
import './WorkflowTabs.css'

const tabs = [
  { key: 'dag', label: 'DAG 流程图', icon: Network },
  { key: 'json', label: 'JSON 配置', icon: FileJson },
  { key: 'workflow', label: 'WorkflowIR', icon: Share2 }
]

const tabDescriptions = {
  dag: '节点卡片 + 连线顺序，便于梳理整体依赖关系。',
  json: '原始 / 修复 JSON 配置，随时校验与复制。',
  workflow: 'WorkflowIR 结构，查看节点输入输出与依赖。'
}

function WorkflowTabs({
  dagData,
  planningData,
  executionData,
  editMode,
  onParamOverridesChange,
  paramOverrides,
  onNodeCreate,
  onNodeDelete,
  onEdgeCreate,
  onEdgeDelete,
  onNodesChange
}) {
  const [activeTab, setActiveTab] = useState('dag')

  return (
    <div className="workflow-tabs">
      <div className="tabs-header">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            className={`tab-button ${activeTab === key ? 'active' : ''}`}
            onClick={() => setActiveTab(key)}
          >
            <Icon size={16} />
            <span>{label}</span>
          </button>
        ))}
      </div>
      <p className="tab-description">{tabDescriptions[activeTab]}</p>

      <div className="tabs-content">
        {activeTab === 'dag' && (
          <div className="dag-container">
            {editMode && (
              <ToolPanel editMode={editMode} />
            )}
            <div className="dag-main">
              <DAGView
                data={dagData}
                executionData={executionData}
                editMode={editMode}
                onParamOverridesChange={onParamOverridesChange}
                paramOverrides={paramOverrides}
                onNodeCreate={onNodeCreate}
                onNodeDelete={onNodeDelete}
                onEdgeCreate={onEdgeCreate}
                onEdgeDelete={onEdgeDelete}
                onNodesChange={onNodesChange}
              />
            </div>
          </div>
        )}
        {activeTab === 'json' && (
          <PlanningView data={planningData} mode="json" />
        )}
        {activeTab === 'workflow' && (
          <PlanningView data={planningData} mode="workflow" />
        )}
      </div>
    </div>
  )
}

export default WorkflowTabs
