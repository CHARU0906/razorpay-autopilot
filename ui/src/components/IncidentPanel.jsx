import React, { useState, useCallback } from 'react'
import { GATED_EPISODE, INCIDENT_EPISODE } from '../data/episodeData.js'

function fmt_inr(n) {
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

// Simulated action agent call — mirrors the real Phase 3 Action Agent behavior
function simulateActionAgent(episode, approved) {
  // p_eff for escalate_to_merchant on auth_required at attempt_k=1
  // from ep_1_1406 trace: p_eff=0.1805 on 2nd attempt
  const p = approved ? 0.1805 : 0
  const succeeded = approved && Math.random() < p
  return {
    action: approved ? 'escalate_to_merchant' : 'stop',
    outcome: approved ? (succeeded ? 'SUCCESS' : 'FAILURE') : 'REJECTED',
    p_eff: p,
    tool: approved ? 'MockOpsQueue' : 'none',
    timestamp: new Date().toISOString(),
  }
}

function TrajectoryBar({ points, currentH, startH }) {
  return (
    <div className="mt-3">
      <div className="flex items-end gap-0.5 h-8">
        {points.map((pt, i) => {
          const pct = pt.success_rate
          const isActive = currentH >= startH + pt.offset_h
          return (
            <div key={i} className="flex-1 flex flex-col items-center gap-0.5">
              <div
                className="w-full transition-all duration-300"
                style={{
                  height: `${pct * 100}%`,
                  background: isActive
                    ? pt.success_rate < 0.86
                      ? '#E5484D'
                      : '#F5A623'
                    : '#1E2A3A',
                }}
              />
            </div>
          )
        })}
      </div>
      <div className="flex justify-between mt-1">
        {points.map((pt, i) => (
          <span key={i} className="font-mono text-[9px] text-muted">
            {(pt.success_rate * 100).toFixed(0)}%
          </span>
        ))}
      </div>
    </div>
  )
}

export function GatedEpisodeCard({ episode, onAction }) {
  const [state, setState] = useState('pending') // pending | processing | approved | rejected
  const [result, setResult] = useState(null)

  const handleApprove = useCallback(() => {
    setState('processing')
    setTimeout(() => {
      const r = simulateActionAgent(episode, true)
      setResult(r)
      setState(r.outcome === 'SUCCESS' ? 'approved' : r.outcome === 'FAILURE' ? 'failed' : 'approved')
      onAction({ episode_id: episode.episode_id, decision: 'approve', result: r })
    }, 800)
  }, [episode, onAction])

  const handleReject = useCallback(() => {
    setState('processing')
    setTimeout(() => {
      const r = simulateActionAgent(episode, false)
      setResult(r)
      setState('rejected')
      onAction({ episode_id: episode.episode_id, decision: 'reject', result: r })
    }, 400)
  }, [episode, onAction])

  const isPending = state === 'pending'
  const isProcessing = state === 'processing'
  const isDone = !isPending && !isProcessing

  return (
    <div className={`border border-amber/40 bg-panel p-4 pulse-amber ${isDone ? 'opacity-60' : ''}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-amber" />
          <span className="font-sans text-xs font-medium text-amber uppercase tracking-wider">
            Requires Human Approval
          </span>
        </div>
        <span className="font-mono text-xs text-muted">{episode.episode_id}</span>
      </div>

      {/* Episode details */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 mb-4">
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Amount</div>
          <div className="font-mono text-base font-semibold text-text">{fmt_inr(episode.amount_inr)}</div>
        </div>
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Expected Recovery</div>
          <div className="font-mono text-base font-semibold text-signal-blue">
            {fmt_inr(episode.expected_recovery_inr)} · P={episode.strategist_p.toFixed(3)}
          </div>
        </div>
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Failure</div>
          <div className="font-mono text-xs text-text">{episode.failure_code}</div>
        </div>
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Issuer · Risk</div>
          <div className="font-mono text-xs text-text">
            {episode.issuer_bank_code} · <span className="text-amber">{episode.risk_score_gateway.toFixed(4)}</span>
          </div>
        </div>
        <div className="col-span-2">
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Gate Reason</div>
          <div className="font-mono text-xs text-amber">{episode.gate_reason}</div>
        </div>
        <div className="col-span-2">
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">
            Strategist Recommendation → Policy Override
          </div>
          <div className="font-mono text-xs text-muted">
            <span className="text-signal-blue">{episode.strategist_recommendation}</span>
            <span className="text-border mx-2">→</span>
            <span className="text-amber">{episode.policy_action}</span>
            <span className="text-muted ml-2">EU={episode.strategist_eu.toFixed(2)} INR</span>
          </div>
        </div>
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Customer LTV</div>
          <div className="font-mono text-xs text-text">{fmt_inr(episode.lifetime_value_inr)}</div>
        </div>
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Merchant</div>
          <div className="font-mono text-xs text-text">{episode.merchant_vertical}</div>
        </div>
      </div>

      {/* Action buttons or result */}
      {isPending && (
        <div className="flex gap-2 pt-3 border-t border-border">
          <button
            onClick={handleApprove}
            className="flex-1 py-2 px-4 font-sans text-xs font-medium text-base bg-amber hover:bg-amber/90 active:bg-amber/80 transition-colors duration-100 uppercase tracking-wider"
          >
            Approve Escalation
          </button>
          <button
            onClick={handleReject}
            className="py-2 px-4 font-sans text-xs font-medium text-muted border border-border hover:border-text hover:text-text transition-colors duration-100 uppercase tracking-wider"
          >
            Reject
          </button>
        </div>
      )}

      {isProcessing && (
        <div className="flex items-center gap-2 pt-3 border-t border-border">
          <div className="w-3 h-3 border border-amber border-t-transparent rounded-full animate-spin" />
          <span className="font-mono text-xs text-muted">Executing via MockOpsQueue…</span>
        </div>
      )}

      {isDone && result && (
        <div className={`pt-3 border-t ${
          state === 'approved' || state === 'failed'
            ? 'border-signal-blue/30'
            : 'border-red/30'
        }`}>
          <div className="flex items-center justify-between">
            <span className={`font-mono text-xs font-medium ${
              state === 'rejected' ? 'text-red' :
              state === 'failed'   ? 'text-amber' : 'text-green'
            }`}>
              {result.outcome} — {result.action}
            </span>
            <span className="font-mono text-[10px] text-muted">
              {result.timestamp.slice(11, 19)}Z
            </span>
          </div>
          {result.p_eff > 0 && (
            <div className="font-mono text-[10px] text-muted mt-0.5">
              p_eff={result.p_eff.toFixed(4)} · tool={result.tool}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function IncidentCard({ incident }) {
  const elapsed = incident.sim_hour - incident.incident_start_h
  const pctElapsed = Math.min(elapsed / incident.incident_window_h, 1)

  return (
    <div className="border border-red/40 bg-panel p-4 pulse-red">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-red" />
          <span className="font-sans text-xs font-medium text-red uppercase tracking-wider">
            Active Incident · {incident.incident_id}
          </span>
        </div>
        <span className="font-mono text-xs text-muted">
          sim_h={incident.sim_hour.toFixed(1)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-2 mb-3">
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Cohort</div>
          <div className="font-mono text-xs text-text">{incident.cohort}</div>
        </div>
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Current Success Rate</div>
          <div className="font-mono text-sm font-semibold text-red">
            {(incident.current_rate * 100).toFixed(0)}%
          </div>
        </div>
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Detection Latency</div>
          <div className="font-mono text-xs text-text">+{incident.detection_latency_h.toFixed(1)}h</div>
        </div>
        <div>
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">Affected Episodes</div>
          <div className="font-mono text-xs text-text">{incident.affected_episodes}</div>
        </div>
        <div className="col-span-2">
          <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-0.5">
            Recommended Action
          </div>
          <div className="font-mono text-xs text-signal-blue">{incident.right_answer}</div>
        </div>
      </div>

      {/* Degradation trajectory */}
      <div>
        <div className="font-sans text-[10px] text-muted uppercase tracking-wider mb-1">
          Success Rate Trajectory
        </div>
        <TrajectoryBar
          points={incident.trajectory}
          currentH={incident.sim_hour}
          startH={incident.incident_start_h}
        />
      </div>

      {/* Window progress */}
      <div className="mt-3">
        <div className="flex justify-between mb-1">
          <span className="font-mono text-[10px] text-muted">Window progress</span>
          <span className="font-mono text-[10px] text-muted">
            {elapsed.toFixed(1)}h / {incident.incident_window_h}h
          </span>
        </div>
        <div className="h-0.5 bg-border">
          <div
            className="h-full bg-red transition-all duration-300"
            style={{ width: `${pctElapsed * 100}%` }}
          />
        </div>
      </div>
    </div>
  )
}

export default function IncidentPanel({ onApprovalAction }) {
  return (
    <div className="border-r border-border">
      <div className="px-4 py-3 border-b border-border bg-panel">
        <span className="font-sans text-xs font-medium text-muted uppercase tracking-wider">
          Active Gates &amp; Incidents
        </span>
      </div>
      <div className="p-4 space-y-4">
        <IncidentCard incident={INCIDENT_EPISODE} />
        <GatedEpisodeCard episode={GATED_EPISODE} onAction={onApprovalAction} />
      </div>
    </div>
  )
}
