/**
 * DecisionView — renders the Strategist's EU(a) comparison for a single episode.
 *
 * Data comes from GET /trace/{episode_id} — real EU scores from strategist.py.
 * Also shows the counterfactual (what Rule-Based would have done) from GET /counterfactual/{id}.
 * The "bad rule" panel uses hardcoded ep_1_1196 data verified against the pipeline.
 */

import React, { useState, useCallback } from 'react'
import { BAD_RULE_EPISODE } from '../data/episodeData.js'

const API = 'http://localhost:8000'

function fmt_inr(n) {
  if (n === null || n === undefined) return '—'
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(1)}L`
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

// ── p_source badge ────────────────────────────────────────────────────────────

function PSourceBadge({ source }) {
  const isModel = source === 'model-scored'
  return (
    <span
      className={`font-mono text-[8px] px-1 py-0.5 rounded border ${
        isModel
          ? 'border-signal-blue/50 text-signal-blue bg-signal-blue/10'
          : 'border-border text-muted bg-border/20'
      }`}
      title={
        isModel
          ? 'P(success) from fitted logistic regression — retry_delay_logreg, training seeds 1000–1019'
          : 'P(success) from calibrated prior table in costs.yaml + class-action fit multiplier'
      }
    >
      {isModel ? 'model' : 'prior'}
    </span>
  )
}

// ── Single action card ────────────────────────────────────────────────────────

function ActionCard({ score, isWinner, maxEU }) {
  const eu = score.expected_utility
  const isPositive = eu > 0
  const isStop = score.action_id === 'stop'

  return (
    <div
      className={`border p-3 space-y-2 ${
        isWinner
          ? 'border-signal-blue/70 bg-signal-blue/5'
          : 'border-border bg-panel/40'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {isWinner && (
            <span className="font-mono text-[9px] px-1.5 py-0.5 bg-signal-blue text-white font-bold shrink-0">
              WINNER
            </span>
          )}
          <span className={`font-mono text-[11px] font-semibold truncate ${isWinner ? 'text-signal-blue' : 'text-text'}`}>
            {score.action_id}
          </span>
          <PSourceBadge source={score.p_source} />
        </div>
        <span className={`font-mono text-sm font-bold shrink-0 ${
          isStop ? 'text-muted' : isPositive ? 'text-signal-blue' : 'text-red'
        }`}>
          {isStop ? 'EU = 0' : `EU = ${fmt_inr(eu)}`}
        </span>
      </div>

      {!isStop && (
        <div className="h-1 bg-border/40 rounded overflow-hidden">
          <div
            className={`h-full rounded ${isPositive ? 'bg-signal-blue' : 'bg-red/60'}`}
            style={{ width: `${Math.min(100, (Math.abs(eu) / Math.max(maxEU, 1)) * 100)}%` }}
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-[10px]">
        <div className="flex justify-between">
          <span className="text-muted">P(success)</span>
          <span className="text-text">{(score.p_success * 100).toFixed(1)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">Revenue</span>
          <span className="text-text">{fmt_inr(score.revenue_inr)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">C_friction</span>
          <span className={score.c_friction > 0 ? 'text-amber' : 'text-muted'}>
            {score.c_friction > 0 ? `-${fmt_inr(score.c_friction)}` : '—'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted">C_risk + C_int</span>
          <span className="text-muted">
            {(score.c_risk + score.c_intervention) > 0
              ? `-${fmt_inr(score.c_risk + score.c_intervention)}`
              : '—'}
          </span>
        </div>
        {score.policy_k > 1 && (
          <div className="flex justify-between col-span-2">
            <span className="text-muted">Horizon K</span>
            <span className="text-text">{score.policy_k} attempts</span>
          </div>
        )}
        {score.delay_h > 0 && (
          <div className="flex justify-between col-span-2">
            <span className="text-muted">Delay</span>
            <span className="text-text">{score.delay_h}h</span>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Policy gate card ──────────────────────────────────────────────────────────

function PolicyGateCard({ tier, reason, winner }) {
  const isAuto = tier === 'automatic'
  const isHuman = tier === 'requires-human'
  const borderCls = isAuto ? 'border-signal-blue/40 bg-signal-blue/5' : 'border-amber/40 bg-amber/5'
  const label = isAuto ? 'AUTO-APPROVED' : isHuman ? 'REQUIRES HUMAN' : 'REQUIRES APPROVAL'
  const textColor = isAuto ? 'text-signal-blue' : 'text-amber'

  return (
    <div className={`border p-3 ${borderCls}`}>
      <div className="flex items-center justify-between mb-1">
        <span className={`font-mono text-[10px] font-bold ${textColor} uppercase tracking-wider`}>
          Stage 3 — Policy Gate: {label}
        </span>
      </div>
      <div className="font-mono text-[10px] text-muted">{reason}</div>
      <div className="font-mono text-[10px] text-text mt-1">
        Dispatched: <span className={textColor}>{winner}</span>
      </div>
    </div>
  )
}

// ── Counterfactual panel ──────────────────────────────────────────────────────

function CounterfactualPanel({ episodeId, apWinner }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [shown, setShown] = useState(false)

  const load = useCallback(async () => {
    if (data) { setShown(s => !s); return }
    setShown(true)
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/counterfactual/${episodeId}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e) {
      if (e.message.includes('Failed to fetch') || e.message.includes('REFUSED')) {
        setError('Backend not running: py -m api.server')
      } else {
        setError(e.message)
      }
    } finally {
      setLoading(false)
    }
  }, [episodeId, data])

  return (
    <div className="border border-border">
      <button
        onClick={load}
        className="w-full px-3 py-2 flex items-center justify-between hover:bg-panel/60 transition-colors"
      >
        <span className="font-mono text-[10px] text-muted">
          What would Rule-Based have done here?
        </span>
        <span className="font-mono text-[9px] text-signal-blue">
          {shown ? '▲ hide' : '▼ show'}
        </span>
      </button>

      {shown && (
        <div className="border-t border-border p-3 font-mono text-[10px]">
          {loading && <span className="text-muted">Loading…</span>}
          {error && <span className="text-red/80">{error}</span>}
          {data && (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <div className="border border-signal-blue/30 bg-signal-blue/5 p-2">
                  <div className="text-signal-blue font-bold text-[9px] uppercase mb-1">Autopilot</div>
                  <div className="text-text">{data.autopilot.action}</div>
                  <div className="text-muted text-[9px]">EU = {fmt_inr(data.autopilot.eu)}</div>
                  <div className={`text-[9px] mt-0.5 ${data.autopilot.is_friction ? 'text-amber' : 'text-green'}`}>
                    {data.autopilot.is_friction ? '⚠ friction' : '✓ zero-friction'}
                  </div>
                </div>
                <div className="border border-amber/30 bg-amber/5 p-2">
                  <div className="text-amber font-bold text-[9px] uppercase mb-1">Rule-Based</div>
                  <div className="text-text">{data.rule_based.action}</div>
                  <div className="text-muted text-[9px]">{data.rule_based.rationale.slice(0, 60)}…</div>
                  <div className={`text-[9px] mt-0.5 ${data.rule_based.is_friction ? 'text-red' : 'text-muted'}`}>
                    {data.rule_based.is_friction ? '✗ friction action' : '— no friction'}
                  </div>
                </div>
              </div>
              {data.comparison.rb_adds_friction_autopilot_avoids && (
                <div className="border border-red/30 bg-red/5 px-2 py-1 text-[9px] text-red/80">
                  Rule-Based adds customer friction that Autopilot avoids.{' '}
                  {data.comparison.best_zero_friction_eu != null && (
                    <>Best zero-friction EU: {fmt_inr(data.comparison.best_zero_friction_eu)} ({data.comparison.best_zero_friction_action})</>
                  )}
                </div>
              )}
              <div className="text-[9px] text-border">{data.simulation_note}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── "Cost of a bad rule" panel (hardcoded ep_1_1196) ─────────────────────────

function BadRulePanel() {
  const [open, setOpen] = useState(false)
  const ep = BAD_RULE_EPISODE

  return (
    <div className="border border-amber/40">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full px-3 py-2 flex items-center justify-between hover:bg-amber/5 transition-colors"
      >
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-amber shrink-0" />
          <span className="font-mono text-[10px] text-amber">
            The cost of a bad rule — ep_1_1196 (expired_card + alternate instrument)
          </span>
        </div>
        <span className="font-mono text-[9px] text-muted">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-amber/30 p-3 space-y-3">
          <div className="font-mono text-[9px] text-muted">
            card_expired · has_alternate_instrument=true · token_type=network_token · amount={fmt_inr(ep.amount_inr)} · LTV={fmt_inr(ep.lifetime_value_inr)}
          </div>

          <div className="grid grid-cols-2 gap-2 font-mono text-[10px]">
            {/* Rule-Based */}
            <div className="border border-red/40 bg-red/5 p-2 space-y-1">
              <div className="text-red font-bold text-[9px] uppercase">Rule-Based</div>
              <div className="text-text">{ep.rb_action}</div>
              <div className="text-muted text-[9px]">{ep.rb_rationale}</div>
              <div className="pt-1 border-t border-red/20 space-y-0.5">
                <div className="flex justify-between">
                  <span className="text-muted">P(success)</span>
                  <span className="text-text">{(ep.rb_p_success * 100).toFixed(0)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">C_friction</span>
                  <span className="text-red">-{fmt_inr(ep.rb_c_friction)}</span>
                </div>
                <div className="flex justify-between font-bold">
                  <span className="text-muted">EU(a)</span>
                  <span className="text-red">{fmt_inr(ep.rb_eu)}</span>
                </div>
                <div className="text-[9px] text-red/70">Negative EU — customer friction exceeds expected recovery</div>
              </div>
            </div>

            {/* Autopilot */}
            <div className="border border-signal-blue/40 bg-signal-blue/5 p-2 space-y-1">
              <div className="text-signal-blue font-bold text-[9px] uppercase">Autopilot</div>
              <div className="text-text">{ep.ap_action}</div>
              <div className="text-muted text-[9px] leading-relaxed">{ep.ap_reasoning.slice(0, 120)}…</div>
              <div className="pt-1 border-t border-signal-blue/20 space-y-0.5">
                <div className="flex justify-between">
                  <span className="text-muted">P(success)</span>
                  <span className="text-text">{(ep.ap_p_success * 100).toFixed(1)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">C_friction</span>
                  <span className="text-green">—</span>
                </div>
                <div className="flex justify-between font-bold">
                  <span className="text-muted">EU(a)</span>
                  <span className="text-signal-blue">+{fmt_inr(ep.ap_eu)}</span>
                </div>
                <div className="text-[9px] text-green">Zero customer friction</div>
              </div>
            </div>
          </div>

          <div className="font-mono text-[9px] text-muted border-t border-border/40 pt-2">
            C_friction = P(churn_increment|action) × LTV × engagement_factor — all in INR.
            Rule-Based's C_friction ({fmt_inr(ep.rb_c_friction)}) exceeds P×Revenue ({fmt_inr(ep.rb_p_success * ep.amount_inr)}) because LTV={fmt_inr(ep.lifetime_value_inr)}.
            This episode pattern drives the 39.8% UIR in Regime B. Synthetic simulator only.
          </div>
        </div>
      )}
    </div>
  )
}

// ── Validation roadmap checklist ──────────────────────────────────────────────

function ValidationRoadmap() {
  const steps = [
    {
      label: 'Shadow logging',
      desc: 'Log Autopilot recommendations alongside existing dunning cron — no execution.',
      status: 'not started',
      detail: 'Minimum 3 months, ≥5 merchant cohorts. Validates P(success|a) calibration on real data.',
    },
    {
      label: 'Calibration check',
      desc: 'Compare recommended action outcomes to real recovery data.',
      status: 'not started',
      detail: 'Checks that costs.yaml constants and _class_action_fit multipliers reflect real CLV distributions.',
    },
    {
      label: 'Canary A/B',
      desc: '5–10% traffic with automated circuit breaker.',
      status: 'not started',
      detail: 'Circuit breaker: halt if live UIR > 1% or recovery rate drops below existing baseline.',
    },
    {
      label: 'Full rollout',
      desc: 'Policy Engine autonomy tiers + human gate for high-risk episodes.',
      status: 'blocked',
      detail: 'Blocked on shadow logging + canary passing. Not started.',
    },
  ]

  return (
    <div className="border border-border">
      <div className="px-3 py-2 border-b border-border bg-panel/40 flex items-center gap-2">
        <div className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
        <span className="font-sans text-[10px] font-semibold text-muted uppercase tracking-wider">
          What we'd need to trust this in production
        </span>
        <span className="font-mono text-[9px] text-amber-300 ml-auto">synthetic only — 0/3 validated</span>
      </div>
      <div className="divide-y divide-border/40">
        {steps.map((step, i) => (
          <div key={i} className="px-3 py-2 flex items-start gap-3">
            <div className={`mt-0.5 shrink-0 w-3 h-3 rounded-sm border flex items-center justify-center text-[8px] ${
              step.status === 'not started' ? 'border-border text-muted' :
              step.status === 'blocked' ? 'border-red/40 text-red/60' :
              'border-green/50 text-green'
            }`}>
              {step.status === 'not started' ? '○' : step.status === 'blocked' ? '✗' : '✓'}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] text-text font-semibold">{step.label}</span>
                <span className={`font-mono text-[8px] px-1 py-0.5 rounded border ${
                  step.status === 'blocked' ? 'border-red/40 text-red/60' : 'border-border text-muted'
                }`}>
                  {step.status}
                </span>
              </div>
              <div className="font-mono text-[9px] text-muted mt-0.5">{step.desc}</div>
              <div className="font-mono text-[9px] text-border mt-0.5">{step.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export default function DecisionView({
  decision,
  episodeMeta,
  success,
  replanCount,
  simulationNote,
  loading,
  error,
  episodeId,
}) {
  if (loading) {
    return (
      <div className="p-4 flex items-center gap-2 text-muted font-mono text-xs">
        <div className="w-3 h-3 border border-signal-blue border-t-transparent rounded-full animate-spin" />
        Running episode through pipeline…
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 m-3 font-mono text-xs text-red/80 border border-red/30 bg-red/5">
        {error}
      </div>
    )
  }

  if (!decision) {
    return (
      <div className="p-4 space-y-4">
        <div className="font-mono text-xs text-muted">
          Click EU(a) tab on any node to load live EU breakdown from the pipeline.
        </div>
        <BadRulePanel />
        <ValidationRoadmap />
      </div>
    )
  }

  const actions = decision.competing_actions || []
  const maxEU = Math.max(...actions.map(a => Math.abs(a.expected_utility)), 1)

  return (
    <div className="p-4 space-y-4 overflow-y-auto font-sans text-xs">
      {/* Simulation disclaimer */}
      <div className="px-2 py-1.5 border border-amber-500/40 rounded flex items-center gap-2">
        <div className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
        <span className="font-mono text-[9px] text-amber-300">
          {simulationNote || 'Synthetic simulator · MockRetryAPI · no live Razorpay API calls'}
        </span>
      </div>

      {/* Episode header */}
      {episodeMeta && (
        <div className="border border-border bg-panel/40 p-3 space-y-1">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] font-semibold text-text">
              {episodeMeta.episode_id}
            </span>
            <span className={`font-mono text-[10px] font-bold ${success ? 'text-green' : 'text-red'}`}>
              {success ? '✓ RECOVERED' : '✗ NOT RECOVERED'}
              {replanCount > 0 && ` (${replanCount} replan${replanCount > 1 ? 's' : ''})`}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-x-4 gap-y-0.5 font-mono text-[10px]">
            <div><span className="text-muted">Failure: </span><span className="text-amber">{episodeMeta.failure_code}</span></div>
            <div><span className="text-muted">Amount: </span><span className="text-text">{fmt_inr(episodeMeta.amount_inr)}</span></div>
            <div><span className="text-muted">Risk: </span><span className="text-text">{episodeMeta.risk_score_gateway?.toFixed(3)}</span></div>
            <div><span className="text-muted">Method: </span><span className="text-text">{episodeMeta.payment_method}</span></div>
            <div><span className="text-muted">Issuer: </span><span className="text-text">{episodeMeta.issuer_bank_code}</span></div>
            <div><span className="text-muted">LTV: </span><span className="text-text">{fmt_inr(episodeMeta.lifetime_value_inr)}</span></div>
          </div>
        </div>
      )}

      {/* Investigator */}
      <div className="border border-border bg-panel/40 p-3 space-y-1">
        <div className="flex items-center justify-between mb-1">
          <span className="font-sans text-[10px] font-semibold text-muted uppercase tracking-wider">
            Stage 1 — Investigator
          </span>
          <span className="font-mono text-[9px] text-signal-blue">
            {decision.inferred_class} · conf={decision.confidence?.toFixed(2)}
          </span>
        </div>
        <div className="font-mono text-[10px] text-text">{decision.diagnostic_summary}</div>
      </div>

      {/* Stage 2 — competing actions */}
      <div className="space-y-2">
        <div className="flex items-center justify-between flex-wrap gap-1">
          <span className="font-sans text-[10px] font-semibold text-muted uppercase tracking-wider">
            Stage 2 — Strategist: EU(a)
          </span>
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-[8px] px-1 py-0.5 border border-signal-blue/50 text-signal-blue bg-signal-blue/10 rounded">model</span>
            <span className="font-mono text-[8px] text-muted">= logreg</span>
            <span className="font-mono text-[8px] px-1 py-0.5 border border-border text-muted bg-border/20 rounded">prior</span>
            <span className="font-mono text-[8px] text-muted">= costs.yaml</span>
          </div>
        </div>
        <div className="space-y-2">
          {actions.map((score) => (
            <ActionCard
              key={score.action_id}
              score={score}
              isWinner={score.action_id === decision.winner}
              maxEU={maxEU}
            />
          ))}
        </div>
      </div>

      {/* Policy Gate */}
      <PolicyGateCard
        tier={decision.policy_tier}
        reason={decision.policy_reason}
        winner={decision.winner}
      />

      {/* Counterfactual toggle */}
      {episodeId && (
        <CounterfactualPanel episodeId={episodeId} apWinner={decision.winner} />
      )}

      {/* Bad rule panel */}
      <BadRulePanel />

      {/* Validation roadmap */}
      <ValidationRoadmap />
    </div>
  )
}
