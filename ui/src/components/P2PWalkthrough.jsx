/**
 * P2PWalkthrough — Promise-to-Pay second walkthrough panel.
 *
 * Shows the same EU(a) framework applied to a monthly subscriber who can't
 * pay today but will pay on salary day. All numbers sourced from verified
 * bench/test_promise_tracker.py (3/3 passing) and actual score_all_actions
 * output on ep_1_8 with replan state.
 *
 * No numbers are fabricated in this component.
 */

import React, { useState } from 'react'
import { P2P_EPISODE } from '../data/episodeData.js'

function fmt_inr(n) {
  if (!n && n !== 0) return '—'
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(1)}L`
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

function EUBar({ eu, maxEU, isWinner }) {
  const pct = Math.min(100, (Math.abs(eu) / Math.max(maxEU, 1)) * 100)
  return (
    <div className="h-1 bg-border/40 rounded overflow-hidden mt-1">
      <div
        className={`h-full rounded ${eu > 0 ? (isWinner ? 'bg-signal-blue' : 'bg-signal-blue/50') : 'bg-red/60'}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

function StrategistCard({ actions }) {
  const maxEU = Math.max(...actions.map(a => Math.abs(a.eu)), 1)
  return (
    <div className="border border-border bg-panel/40 p-3 space-y-2">
      <div className="flex items-center justify-between mb-1">
        <span className="font-sans text-[10px] font-semibold text-muted uppercase tracking-wider">
          Stage 2 — Strategist: EU(a) after retry_72h fails
        </span>
        <span className="font-mono text-[9px] text-muted">replan #1 state</span>
      </div>
      {actions.map(a => (
        <div key={a.action_id} className={`p-2 border ${a.winner ? 'border-signal-blue/60 bg-signal-blue/5' : 'border-border/60'}`}>
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 min-w-0">
              {a.winner && (
                <span className="font-mono text-[8px] px-1 bg-signal-blue text-white font-bold shrink-0">WIN</span>
              )}
              <span className={`font-mono text-[10px] font-semibold ${a.winner ? 'text-signal-blue' : 'text-text'}`}>
                {a.action_id}
              </span>
              <span className={`font-mono text-[8px] px-1 rounded border ${
                a.p_source === 'model-scored'
                  ? 'border-signal-blue/40 text-signal-blue bg-signal-blue/10'
                  : 'border-border text-muted bg-border/20'
              }`}>
                {a.p_source === 'model-scored' ? 'model' : 'prior'}
              </span>
            </div>
            <span className={`font-mono text-[11px] font-bold shrink-0 ${a.winner ? 'text-signal-blue' : 'text-text'}`}>
              {fmt_inr(a.eu)}
            </span>
          </div>
          <EUBar eu={a.eu} maxEU={maxEU} isWinner={a.winner} />
          <div className="grid grid-cols-3 gap-1 mt-1.5 font-mono text-[9px] text-muted">
            <div>P={( a.p_success * 100).toFixed(1)}%</div>
            <div>C_friction={a.c_friction > 0 ? `-${fmt_inr(a.c_friction)}` : '—'}</div>
            <div>{a.action_id === 'retry_7d' ? 'delay=168h' : a.action_id === 'send_recovery_link' ? 'delay=8h' : 'delay=4h'}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

function LifecycleCard({ caseData, label, color, isGood }) {
  return (
    <div className={`border p-3 space-y-2 ${isGood ? 'border-signal-blue/40 bg-signal-blue/5' : 'border-amber/40 bg-amber/5'}`}>
      <div className="flex items-center gap-2">
        <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${isGood ? 'bg-signal-blue' : 'bg-amber'}`} />
        <span className={`font-mono text-[10px] font-semibold uppercase tracking-wider ${isGood ? 'text-signal-blue' : 'text-amber'}`}>
          {label}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[10px]">
        <div><span className="text-muted">Action: </span><span className="text-text">{caseData.action}</span></div>
        <div><span className="text-muted">Tool: </span><span className="text-text">{caseData.tool}</span></div>
        <div><span className="text-muted">Due in: </span><span className="text-text">{caseData.due_in_hours}h</span></div>
        <div><span className="text-muted">Channel: </span><span className="text-text">{caseData.channel}</span></div>
      </div>
      <div className={`font-mono text-[10px] px-2 py-1.5 rounded ${isGood ? 'bg-signal-blue/10 text-signal-blue' : 'bg-amber/10 text-amber'}`}>
        {caseData.log}
      </div>
      {!isGood && caseData.replan_state && (
        <div className="font-mono text-[9px] text-muted">
          State after: replan_count={caseData.replan_state.replan_count} · promise_broken=true → Strategist replans with elevated urgency
        </div>
      )}
    </div>
  )
}

export default function P2PWalkthrough() {
  const ep = P2P_EPISODE
  const [activeCase, setActiveCase] = useState('a') // 'a' | 'b'

  return (
    <div className="p-4 space-y-4 overflow-y-auto font-sans text-xs">
      {/* Header */}
      <div className="px-2 py-1.5 border border-amber-500/40 rounded flex items-center gap-2">
        <div className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
        <span className="font-mono text-[9px] text-amber-300">
          Synthetic simulator only · EU scores from score_all_actions(ep_1_8) · P2P tests: 3/3 passing
        </span>
      </div>

      {/* Episode header */}
      <div className="border border-border bg-panel/40 p-3 space-y-1">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10px] font-semibold text-text">{ep.episode_id}</span>
          <span className="font-mono text-[9px] text-amber">insufficient_funds · monthly subscriber</span>
        </div>
        <div className="grid grid-cols-3 gap-x-4 gap-y-0.5 font-mono text-[10px]">
          <div><span className="text-muted">Amount: </span><span className="text-text">{fmt_inr(ep.amount_inr)}</span></div>
          <div><span className="text-muted">LTV: </span><span className="text-text">{fmt_inr(ep.lifetime_value_inr)}</span></div>
          <div><span className="text-muted">Engagement: </span><span className="text-text">{ep.email_engagement_score.toFixed(2)}</span></div>
          <div><span className="text-muted">Billing: </span><span className="text-text">{ep.billing_cycle}</span></div>
          <div><span className="text-muted">Txn interval: </span><span className="text-text">{ep.avg_days_between_txns.toFixed(1)}d</span></div>
        </div>
      </div>

      {/* Investigator */}
      <div className="border border-border bg-panel/40 p-3">
        <div className="flex items-center justify-between mb-1">
          <span className="font-sans text-[10px] font-semibold text-muted uppercase tracking-wider">Stage 1 — Investigator</span>
          <span className="font-mono text-[9px] text-signal-blue">insufficient_funds · conf=0.95</span>
        </div>
        <div className="font-mono text-[10px] text-text">
          Soft decline due to balance liquidity timing mismatch (monthly billing cycle); recovery requires timing delay.
          Immediate short retries suppressed to conserve attempt budget.
        </div>
      </div>

      {/* EU Scoring */}
      <StrategistCard actions={ep.strategist_top3} />

      {/* P2P Lifecycle */}
      <div className="space-y-2">
        <div className="font-sans text-[10px] font-semibold text-muted uppercase tracking-wider">
          Promise-to-Pay Lifecycle
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setActiveCase('a')}
            className={`flex-1 py-1.5 font-mono text-[9px] border transition-colors ${
              activeCase === 'a'
                ? 'border-signal-blue/60 text-signal-blue bg-signal-blue/10'
                : 'border-border text-muted hover:text-text'
            }`}
          >
            Case A: Fulfilled ✓
          </button>
          <button
            onClick={() => setActiveCase('b')}
            className={`flex-1 py-1.5 font-mono text-[9px] border transition-colors ${
              activeCase === 'b'
                ? 'border-amber/60 text-amber bg-amber/10'
                : 'border-border text-muted hover:text-text'
            }`}
          >
            Case B: Broken → Replan
          </button>
        </div>
        {activeCase === 'a' ? (
          <LifecycleCard
            caseData={ep.case_a}
            label="Customer fulfills commitment on time"
            isGood={true}
          />
        ) : (
          <LifecycleCard
            caseData={ep.case_b}
            label="Commitment window expires — replanning triggered"
            isGood={false}
          />
        )}
      </div>

      {/* Architecture note */}
      <div className="border-t border-border/40 pt-3 font-mono text-[9px] text-muted space-y-1">
        <div className="font-sans text-[9px] font-semibold text-muted uppercase tracking-wider mb-1">
          Same architecture, different surface
        </div>
        <div>Same Strategist (EU scoring) → same Policy Engine → same Outcome Agent replanning loop.</div>
        <div>P2P tracking is what happens inside the send_recovery_link execution path — not a separate decision system.</div>
        <div className="text-border">Verified: py -m bench.test_promise_tracker (3/3 passing)</div>
      </div>
    </div>
  )
}
