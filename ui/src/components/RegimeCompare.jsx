/**
 * RegimeCompare — live Regime A vs Regime B toggle.
 *
 * Calls POST /bench/compare?seed=N and renders the side-by-side result.
 * Shows Rule-Based holding in Regime A and collapsing in Regime B.
 *
 * NOTE: This runs ~30-60 seconds on first trigger (generates 3,000 episodes
 * per regime, runs 2 strategies). Shows a spinner while running.
 *
 * All numbers are synthetic. Stated inline.
 */

import React, { useState, useCallback } from 'react'

const API = 'http://localhost:8000'

function fmt_pct(n) { return `${(n * 100).toFixed(1)}%` }
function fmt_inr_cr(n) { return `₹${(n / 1e7).toFixed(2)}Cr` }

function DeltaBadge({ delta, invert = false }) {
  const bad = invert ? delta > 0 : delta < 0
  const color = bad ? 'text-red' : 'text-green'
  const sign = delta >= 0 ? '+' : ''
  return (
    <span className={`font-mono text-[10px] font-bold ${color}`}>
      {sign}{(delta * 100).toFixed(1)}pp
    </span>
  )
}

function StrategyRow({ name, label, regimeA, regimeB }) {
  const delta_rr = (regimeB?.recovery_rate ?? 0) - (regimeA?.recovery_rate ?? 0)
  const delta_uir = (regimeB?.uir ?? 0) - (regimeA?.uir ?? 0)
  const isRuleBased = name === 'rule_based'

  return (
    <div className={`border-b border-border/40 p-3 ${isRuleBased ? 'bg-amber/5' : 'bg-signal-blue/5'}`}>
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-1.5 h-1.5 rounded-full ${isRuleBased ? 'bg-amber' : 'bg-signal-blue'}`} />
        <span className={`font-mono text-[11px] font-semibold ${isRuleBased ? 'text-amber' : 'text-signal-blue'}`}>
          {label}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 font-mono text-[10px]">
        <div />
        <div className="text-center text-muted uppercase text-[9px]">Regime A</div>
        <div className="text-center text-muted uppercase text-[9px]">Regime B → Delta</div>

        <div className="text-muted">Recovery %</div>
        <div className="text-center text-text font-semibold">{fmt_pct(regimeA?.recovery_rate ?? 0)}</div>
        <div className="text-center">
          <span className="text-text font-semibold">{fmt_pct(regimeB?.recovery_rate ?? 0)}</span>
          <span className="ml-1.5"><DeltaBadge delta={delta_rr} /></span>
        </div>

        <div className="text-muted">UIR %</div>
        <div className="text-center text-text">{fmt_pct(regimeA?.uir ?? 0)}</div>
        <div className="text-center">
          <span className="text-text">{fmt_pct(regimeB?.uir ?? 0)}</span>
          <span className="ml-1.5"><DeltaBadge delta={delta_uir} invert={true} /></span>
        </div>

        <div className="text-muted">Revenue</div>
        <div className="text-center text-text">{fmt_inr_cr(regimeA?.gross_revenue ?? 0)}</div>
        <div className="text-center text-text">{fmt_inr_cr(regimeB?.gross_revenue ?? 0)}</div>
      </div>
    </div>
  )
}

export default function RegimeCompare() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [seed, setSeed] = useState(1)

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/bench/compare?seed=${seed}`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setResult(data)
    } catch (e) {
      setError(`API error: ${e.message}. Is the backend running? (py -m api.server)`)
    } finally {
      setLoading(false)
    }
  }, [seed])

  return (
    <div className="border border-border bg-panel flex flex-col" style={{ minWidth: 340 }}>
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-border bg-[#141B26] flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-signal-blue" />
          <span className="font-sans text-xs font-medium text-muted uppercase tracking-wider">
            Regime A vs B
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[9px] text-muted">seed:</span>
          <select
            value={seed}
            onChange={e => setSeed(Number(e.target.value))}
            className="font-mono text-[9px] bg-[#0A0E14] border border-border text-text px-1 py-0.5"
          >
            {[1,2,3,4,5].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <button
            onClick={run}
            disabled={loading}
            className="font-mono text-[9px] px-2 py-1 border border-signal-blue/50 text-signal-blue hover:border-signal-blue disabled:opacity-40 transition-colors"
          >
            {loading ? '⏳ running…' : '▶ Run Live'}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {!result && !loading && !error && (
          <div className="p-4 font-mono text-[10px] text-muted space-y-1.5">
            <div>Click "▶ Run Live" to generate 3,000 synthetic episodes per regime</div>
            <div>and run Rule-Based + Autopilot on both.</div>
            <div className="text-[9px] text-border mt-2">Takes ~30–60 seconds. Requires backend: py -m api.server</div>
          </div>
        )}

        {loading && (
          <div className="p-4 flex items-center gap-2 font-mono text-[10px] text-muted">
            <div className="w-3 h-3 border border-signal-blue border-t-transparent rounded-full animate-spin shrink-0" />
            Generating episodes + running strategies (~30–60s)…
          </div>
        )}

        {error && (
          <div className="p-3 font-mono text-[10px] text-red/80 border border-red/30 bg-red/5 m-3">
            {error}
          </div>
        )}

        {result && (
          <div className="space-y-0">
            <StrategyRow
              name="rule_based"
              label="Rule-Based"
              regimeA={result.regime_a?.rule_based}
              regimeB={result.regime_b?.rule_based}
            />
            <StrategyRow
              name="autopilot"
              label="Autopilot"
              regimeA={result.regime_a?.autopilot}
              regimeB={result.regime_b?.autopilot}
            />

            {/* Summary */}
            <div className="p-3 border-t border-border font-mono text-[10px] space-y-1">
              <div className="text-muted uppercase text-[9px] mb-1">What this shows</div>
              <div>
                Rule-Based Δ:{' '}
                <span className={result.summary.rule_based_delta < -0.05 ? 'text-red font-bold' : 'text-text'}>
                  {(result.summary.rule_based_delta * 100).toFixed(1)}pp
                </span>
                {' '}recovery A→B
              </div>
              <div>
                Autopilot Δ:{' '}
                <span className={result.summary.autopilot_delta >= -0.02 ? 'text-green font-bold' : 'text-amber'}>
                  {(result.summary.autopilot_delta * 100).toFixed(1)}pp
                </span>
                {' '}recovery A→B
              </div>
              <div className="pt-1 border-t border-border/40 text-[9px] text-muted">
                Seed {result.seed} · {result.simulation_note}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
