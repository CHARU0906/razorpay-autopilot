import React from 'react'
import { BENCHMARK, REVENUE_AT_RISK, TOTAL_EPISODES } from '../data/benchmarkData.js'

function fmt_inr(n) {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(1)}Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(1)}L`
  return `₹${n.toLocaleString('en-IN')}`
}

function fmt_pct(n, decimals = 1) {
  return `${(n * 100).toFixed(decimals)}%`
}

const METRICS = [
  {
    label: 'Sim. Revenue Recovered',
    value: fmt_inr(BENCHMARK.autopilot.gross_revenue),
    sub: `${fmt_pct(BENCHMARK.autopilot.recovery_rate)} recovery rate`,
    color: 'text-signal-blue',
    detail: `mean across ${10} eval seeds`,
  },
  {
    label: 'Lift vs Smart-Dunning',
    value: `+${BENCHMARK.autopilot.lift_vs_sd_pct.toFixed(1)}%`,
    sub: `+₹${((BENCHMARK.autopilot.gross_revenue - BENCHMARK.smart_dunning.gross_revenue) / 1e6).toFixed(1)}M gross`,
    color: 'text-signal-blue',
    detail: `orchestration +${BENCHMARK.autopilot.orchestration_gain_pct}% · detection +${BENCHMARK.autopilot.detection_gain_pct}%`,
  },
  {
    label: 'Episodes Processed (Sim)',
    value: BENCHMARK.autopilot.interventions.toLocaleString(),
    sub: `${TOTAL_EPISODES.toLocaleString()} total episodes`,
    color: 'text-text',
    detail: `${(BENCHMARK.autopilot.recovery_rate * 100).toFixed(1)}% recovered`,
  },
  {
    label: 'Gap to Oracle Ceiling',
    value: fmt_inr(REVENUE_AT_RISK),
    sub: `${BENCHMARK.autopilot.pct_of_oracle.toFixed(1)}% of Oracle`,
    color: 'text-muted',
    detail: 'vs Oracle [CEILING]',
  },
  {
    label: 'Unnecessary Interventions',
    value: `${(BENCHMARK.autopilot.uir * 100).toFixed(1)}%`,
    sub: `vs Smart-Dunning 49.0%`,
    color: 'text-green',
    detail: 'UIR — customer-visible only',
  },
  {
    label: 'Contacts / Recovery',
    value: BENCHMARK.autopilot.contacts_per_recovery.toFixed(3),
    sub: `vs Smart-Dunning 0.776`,
    color: 'text-text',
    detail: 'friction efficiency',
  },
]

export default function MetricStrip({ slim = false }) {
  if (slim) {
    // Compact single-row status bar for hero-map layout
    return (
      <div
        className="flex items-center justify-between px-4 py-1.5 border-b border-border shrink-0"
        style={{ background: '#141B26' }}
      >
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-signal-blue" />
          <span className="font-sans text-[10px] font-medium text-muted tracking-widest uppercase">
            Razorpay Autopilot
          </span>
        </div>
        <div className="flex items-center gap-5">
          {METRICS.slice(0, 5).map((m, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <span className="font-sans text-[9px] text-muted uppercase tracking-wider">{m.label}:</span>
              <span className={`font-mono text-[11px] font-semibold ${m.color}`}>{m.value}</span>
            </div>
          ))}
          <div className="flex items-center gap-1.5 ml-2 px-2 py-0.5 border border-amber-500/40 rounded">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
            <span className="font-mono text-[10px] text-amber-300">SYNTHETIC SIM · seeds 1–10</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="border-b border-border">
      {/* Header bar */}
      <div className="flex items-center justify-between px-6 py-2 border-b border-border bg-panel">
        <div className="flex items-center gap-3">
          <div className="w-1.5 h-1.5 rounded-full bg-signal-blue" />
          <span className="font-sans text-xs font-medium text-muted tracking-widest uppercase">
            Razorpay Autopilot — Command Center
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span className="font-mono text-xs text-muted">
            seeds 1–10 · multi-step oracle
          </span>
          <div className="flex items-center gap-1.5 px-2 py-0.5 border border-amber-500/40 rounded">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
            <span className="font-mono text-xs text-amber-300">SYNTHETIC SIM</span>
          </div>
        </div>
      </div>

      {/* Metric cells */}
      <div className="grid grid-cols-6 divide-x divide-border">
        {METRICS.map((m, i) => (
          <div key={i} className="px-5 py-4 bg-base hover:bg-panel transition-colors duration-100">
            <div className="font-sans text-[10px] font-medium text-muted uppercase tracking-wider mb-1.5">
              {m.label}
            </div>
            <div className={`font-mono text-xl font-semibold leading-none ${m.color}`}>
              {m.value}
            </div>
            <div className="font-mono text-xs text-muted mt-1.5">
              {m.sub}
            </div>
            <div className="font-mono text-[10px] text-border mt-1">
              {m.detail}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
