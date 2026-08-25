/**
 * NodeSidePanel — slides in from the right when a route node is clicked.
 * Reuses IncidentCard and GatedEpisodeCard exactly as built in IncidentPanel.
 * No rebuilding — just wires clicked-node data into existing components.
 */
import React from 'react'
import { IncidentCard, GatedEpisodeCard } from './IncidentPanel.jsx'
import { GATED_EPISODE, INCIDENT_EPISODE } from '../data/episodeData.js'
import { routeState } from '../data/routeData.js'

function HealthyNodeCard({ route }) {
  return (
    <div className="border border-border bg-panel p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-signal-blue" />
          <span className="font-sans text-xs font-medium text-muted uppercase tracking-wider">
            Route · Healthy
          </span>
        </div>
        <span className="font-mono text-xs text-muted">{route.id}</span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Route Key</div>
          <div className="font-mono text-xs text-text">{route.label}</div>
        </div>
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Episodes</div>
          <div className="font-mono text-xs text-text">{route.episodeCount}</div>
        </div>
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Status</div>
          <div className="font-mono text-xs text-signal-blue">✓ nominal</div>
        </div>
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Incident</div>
          <div className="font-mono text-xs text-muted">none</div>
        </div>
      </div>
      <div className="mt-3 pt-3 border-t border-border">
        <div className="font-mono text-[10px] text-muted">
          No active gates or degradation on this route.
        </div>
      </div>
    </div>
  )
}

export default function NodeSidePanel({ route, simHour, onClose, onApprovalAction }) {
  if (!route) return null

  const rs = routeState(route, simHour)
  const isIncidentNode = route.isIncident && rs.state !== 'healthy'

  // Map the clicked incident node to the pre-built incident data
  // INC-1 node maps to INCIDENT_EPISODE; INC-1 also has the gate
  const incidentData = isIncidentNode ? {
    ...INCIDENT_EPISODE,
    incident_id: route.incidentId,
    cohort: route.label,
    sim_hour: simHour,
    incident_start_h: route.incident_start_h,
    incident_window_h: route.window_h,
    trajectory: route.trajectory,
    current_rate: rs.currentRate,
    detection_latency_h: route.detection_latency_h,
    affected_episodes: route.episodeCount,
    right_answer: route.incidentId === 'INC-2' ? 'retry_alternate_route' : 'hold_for_incident',
  } : null

  const showGate = route.incidentId === 'INC-1' && rs.state === 'detected'

  return (
    <div
      className="flex flex-col border-l border-border overflow-hidden"
      style={{
        width: '340px',
        background: '#0A0E14',
        height: '100%',
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border shrink-0"
           style={{ background: '#141B26' }}>
        <span className="font-sans text-xs font-medium text-muted uppercase tracking-wider">
          {route.label}
        </span>
        <button
          onClick={onClose}
          className="font-mono text-xs text-muted hover:text-text transition-colors px-1"
          aria-label="Close panel"
        >
          ✕
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {isIncidentNode && incidentData ? (
          <>
            <IncidentCard incident={incidentData} />
            {showGate && (
              <GatedEpisodeCard episode={GATED_EPISODE} onAction={onApprovalAction} />
            )}
          </>
        ) : (
          <HealthyNodeCard route={route} />
        )}
      </div>
    </div>
  )
}
