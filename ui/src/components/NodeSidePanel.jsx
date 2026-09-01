import React, { useState, useCallback, useEffect } from 'react'
import { IncidentCard, GatedEpisodeCard } from './IncidentPanel.jsx'
import { GATED_EPISODE, INCIDENT_EPISODE } from '../data/episodeData.js'
import { routeState } from '../data/routeData.js'
import DecisionView from './DecisionView.jsx'

const API = 'http://localhost:8000'

// Demo episode IDs for the Decision view
// ep_1_34: the INC-1 regional_degradation episode (success path with replan)
// ep_1_20: a payment_method_restricted non-recoverable episode (honest failure case)
const DEMO_EPISODES = {
  incident: 'ep_1_34',
  non_recoverable: 'ep_1_20',
}

function useEpisodeTrace(episodeId) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const fetch_ = useCallback(async (eid) => {
    if (!eid) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/trace/${eid}`)
      if (!res.ok) {
        // Backend not running — surface a clear message rather than a cryptic error
        if (res.status === 404) throw new Error(`Episode ${eid} not found`)
        throw new Error(`HTTP ${res.status}`)
      }
      const json = await res.json()
      setData(json)
    } catch (e) {
      if (e.message.includes('Failed to fetch') || e.message.includes('ERR_CONNECTION_REFUSED')) {
        setError('Backend not running. Start it with: py -m api.server (in the repo root)')
      } else {
        setError(e.message)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (episodeId) fetch_(episodeId)
  }, [episodeId, fetch_])

  return { data, loading, error }
}

function CausalChainCard({ incident, isGated, isHealthy, route }) {
  const chain = isHealthy ? [
    `1. Signal: All route transactions nominal on ${route.label}`,
    `2. Context: Episode throughput normal, zero rolling error spikes`,
    `3. Diagnosis: Infrastructure and payment pathways operating nominally`,
    `4. Action Space: All standard recovery & retry pathways permitted`,
  ] : incident?.causal_chain || (isGated ? GATED_EPISODE.causal_chain : [
    `1. Monitored Cohort: ${route.label}`,
    `2. Context: Rolling success rate monitoring active`,
    `3. Diagnosis: Standard failure distribution without correlated degradation`,
    `4. Action Space: Full 13-action orchestration space available`,
  ])

  return (
    <div className="border border-border bg-panel p-4 space-y-3">
      <div className="flex items-center justify-between border-b border-border/60 pb-2">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-signal-blue" />
          <span className="font-sans text-xs font-semibold text-text uppercase tracking-wider">
            Causal Diagnostic Chain
          </span>
        </div>
        <span className="font-mono text-[10px] text-signal-blue">Stage 1 · Investigator</span>
      </div>

      <div className="text-[11px] font-sans text-muted leading-relaxed">
        {incident?.diagnostic_summary || (isGated ? GATED_EPISODE.diagnostic_summary : "Deterministic signal inference mapped to root cause.")}
      </div>

      <div className="space-y-2 pt-1">
        <div className="font-sans text-[10px] font-semibold text-muted uppercase tracking-wider">
          Diagnostic Reasoning Steps
        </div>
        <div className="space-y-1.5 font-mono text-[11px]">
          {chain.map((step, idx) => (
            <div
              key={idx}
              className="p-2 rounded bg-black/40 border border-border/40 text-text/90 leading-snug"
            >
              {step}
            </div>
          ))}
        </div>
      </div>

      <div className="pt-2 border-t border-border/50 grid grid-cols-2 gap-2 text-[10px] font-mono">
        <div>
          <span className="text-muted block uppercase">Eliminated Hypotheses</span>
          <span className="text-red">✗ customer_insolvency</span>
        </div>
        <div>
          <span className="text-muted block uppercase">Action Space Restricted</span>
          <span className="text-signal-blue">✓ compliant set</span>
        </div>
      </div>
    </div>
  )
}

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
  const [activeTab, setActiveTab] = useState('status') // 'status' | 'why' | 'decision'

  if (!route) return null

  const rs = routeState(route, simHour)
  const isIncidentNode = route.isIncident && rs.state !== 'healthy'

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

  // Pick episode for Decision view:
  // INC-1 node → use the demo incident episode (ep_1_34)
  // non-incident node → use the non-recoverable demo episode (ep_1_20)
  const decisionEpisodeId = (route.incidentId === 'INC-1')
    ? DEMO_EPISODES.incident
    : DEMO_EPISODES.non_recoverable

  const { data: traceData, loading: traceLoading, error: traceError } = useEpisodeTrace(
    activeTab === 'decision' ? decisionEpisodeId : null
  )

  return (
    <div
      className="flex flex-col border-l border-border overflow-hidden"
      style={{
        width: '400px',
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

      {/* Tabs */}
      <div className="flex border-b border-border bg-[#0E131B] text-xs font-mono">
        <button
          onClick={() => setActiveTab('status')}
          className={`flex-1 py-2 text-center transition-colors border-b-2 ${
            activeTab === 'status'
              ? 'border-signal-blue text-signal-blue font-semibold bg-panel/40'
              : 'border-transparent text-muted hover:text-text'
          }`}
        >
          STATUS
        </button>
        <button
          onClick={() => setActiveTab('why')}
          className={`flex-1 py-2 text-center transition-colors border-b-2 flex items-center justify-center gap-1 ${
            activeTab === 'why'
              ? 'border-signal-blue text-signal-blue font-semibold bg-panel/40'
              : 'border-transparent text-muted hover:text-text'
          }`}
        >
          WHY?
          <span className="text-[8px] px-1 bg-signal-blue/20 text-signal-blue rounded">CAUSAL</span>
        </button>
        <button
          onClick={() => setActiveTab('decision')}
          className={`flex-1 py-2 text-center transition-colors border-b-2 flex items-center justify-center gap-1 ${
            activeTab === 'decision'
              ? 'border-signal-blue text-signal-blue font-semibold bg-panel/40'
              : 'border-transparent text-muted hover:text-text'
          }`}
          title="Live EU(a) breakdown from backend pipeline"
        >
          EU(a)
          <span className="text-[8px] px-1 bg-signal-blue/20 text-signal-blue rounded">LIVE</span>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto" style={{ minHeight: 0 }}>
        {activeTab === 'why' ? (
          <div className="p-4 space-y-4">
            <CausalChainCard
              incident={incidentData}
              isGated={showGate}
              isHealthy={!isIncidentNode}
              route={route}
            />
          </div>
        ) : activeTab === 'decision' ? (
          <DecisionView
            decision={traceData?.decision}
            episodeMeta={traceData?.episode_meta}
            success={traceData?.success}
            replanCount={traceData?.replan_count}
            simulationNote={traceData?.simulation_note}
            loading={traceLoading}
            error={traceError}
            episodeId={decisionEpisodeId}
          />
        ) : isIncidentNode && incidentData ? (
          <div className="p-4 space-y-4">
            <IncidentCard incident={incidentData} />
            {showGate && (
              <GatedEpisodeCard episode={GATED_EPISODE} onAction={onApprovalAction} />
            )}
          </div>
        ) : (
          <div className="p-4">
            <HealthyNodeCard route={route} />
          </div>
        )}
      </div>
    </div>
  )
}
