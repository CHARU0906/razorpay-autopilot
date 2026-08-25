import React, { useState, useCallback } from 'react'
import MetricStrip from './components/MetricStrip.jsx'
import IncidentPanel from './components/IncidentPanel.jsx'
import ActionLog from './components/ActionLog.jsx'

export default function App() {
  const [approvalLog, setApprovalLog] = useState([])

  const handleApprovalAction = useCallback(({ episode_id, decision, result }) => {
    const entry = {
      ts: result.timestamp,
      stage: 'outcome',
      tier: decision === 'reject' ? 'failure' : result.outcome === 'SUCCESS' ? 'success' : 'failure',
      episode_id,
      text: `${decision.toUpperCase()} → ${result.action}  outcome=${result.outcome}  tool=${result.tool}`,
    }
    setApprovalLog(prev => [...prev, entry])
  }, [])

  return (
    <div
      className="min-h-screen flex flex-col"
      style={{ backgroundColor: '#0A0E14', color: '#E8ECF1' }}
    >
      {/* Top metric strip */}
      <MetricStrip />

      {/* Main body: two-column layout */}
      <div className="flex flex-1 overflow-hidden" style={{ minHeight: 'calc(100vh - 106px)' }}>
        {/* Left: incident + approval gates — 2/5 width */}
        <div className="w-2/5 overflow-y-auto border-r border-border">
          <IncidentPanel onApprovalAction={handleApprovalAction} />
        </div>

        {/* Right: action log — 3/5 width */}
        <div className="w-3/5 flex flex-col overflow-hidden">
          <ActionLog extraEntries={approvalLog} />
        </div>
      </div>
    </div>
  )
}
