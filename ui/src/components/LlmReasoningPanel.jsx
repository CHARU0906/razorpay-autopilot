import React from 'react'
import { LLM_EPISODE_216 } from '../data/episodeData.js'

function fmt_inr(n) {
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function LlmReasoningPanel({ onClose }) {
  const ep = LLM_EPISODE_216

  return (
    <div className="border border-signal-blue/40 bg-panel p-4 shadow-xl max-w-xl w-full" style={{ background: '#141B26' }}>
      {/* Header */}
      <div className="flex items-center justify-between pb-3 mb-3 border-b border-border">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-signal-blue animate-pulse" />
          <span className="font-sans text-xs font-semibold text-signal-blue uppercase tracking-wider">
            Classification: LLM-Assisted (Simulated)
          </span>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="font-mono text-xs text-muted hover:text-text transition-colors px-1"
            aria-label="Close modal"
          >
            ✕
          </button>
        )}
      </div>

      {/* Production & Spec Note */}
      <div className="p-3 mb-3 bg-panel/80 border border-border text-xs leading-relaxed font-sans text-muted">
        <span className="font-semibold text-text">Note:</span> In production, this step calls an LLM to classify ambiguous failure signals. In this benchmark demo, a deterministic keyword-matching stub is used as the LLM fallback (per SPEC P8 — no live LLM in the critical path).
      </div>

      {/* Core Explanation & Fallback Reasoning */}
      <div className="mb-4 text-xs leading-relaxed text-text font-sans space-y-2">
        <p>
          The stub evaluated the failure message (<code className="font-mono text-amber text-[11px] bg-black/40 px-1 py-0.5 border border-border">{`'${ep.failure_message}'`}</code>) against its keyword rules, found no match, and applied its default fallback — classifying episode <code className="font-mono text-signal-blue text-[11px] bg-black/40 px-1 py-0.5 border border-border">{ep.episode_id}</code> as <code className="font-mono text-green text-[11px] bg-black/40 px-1 py-0.5 border border-border">{ep.llm_inferred}</code> with the reasoning:
        </p>
        <div className="font-mono text-[11px] p-2 bg-black/50 border border-signal-blue/30 text-signal-blue rounded-none">
          "{ep.llm_reasoning}"
        </div>
        <p className="text-muted text-[11px] italic">
          All ambiguous-population failure messages in this benchmark are deliberately uninformative (e.g. <code className="font-mono text-[10px]">'Do not honour'</code>), so the LLM path's role here is providing a better-calibrated default than the risk-score heuristic alone, rather than parsing rich text signal.
        </p>
      </div>

      {/* Episode Details */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 mb-4 p-2.5 bg-black/30 border border-border font-mono text-[11px]">
        <div>
          <span className="text-muted uppercase text-[9px] block">Episode ID</span>
          <span className="text-text font-semibold">{ep.episode_id}</span>
        </div>
        <div>
          <span className="text-muted uppercase text-[9px] block">Amount</span>
          <span className="text-text font-semibold">{fmt_inr(ep.amount_inr)}</span>
        </div>
        <div>
          <span className="text-muted uppercase text-[9px] block">Failure Code</span>
          <span className="text-amber">{ep.failure_code}</span>
        </div>
        <div>
          <span className="text-muted uppercase text-[9px] block">Gateway Risk Score</span>
          <span className="text-amber">{ep.risk_score_gateway.toFixed(3)}</span>
        </div>
        <div>
          <span className="text-muted uppercase text-[9px] block">Instrument</span>
          <span className="text-text">{ep.payment_method} ({ep.card_network} / {ep.issuer_bank_code})</span>
        </div>
        <div>
          <span className="text-muted uppercase text-[9px] block">Ground Truth Class</span>
          <span className="text-green font-semibold">{ep.ground_truth_class} ({ep.ground_truth_optimal})</span>
        </div>
      </div>

      {/* Benchmark Outcome Comparison */}
      <div className="border-t border-border pt-3 space-y-2 font-mono text-[11px]">
        <div className="font-sans text-[10px] font-semibold text-muted uppercase tracking-wider mb-1">
          Benchmark Outcome Impact
        </div>

        <div className="p-2 border border-red/30 bg-red/5">
          <div className="text-red font-semibold text-[10px] uppercase tracking-wide">
            • Deterministic Heuristic Path
          </div>
          <div className="text-muted text-[11px] mt-0.5">
            Inferred <span className="text-text font-semibold">{ep.heuristic_inferred}</span> → executed <code className="text-red">send_recovery_link</code> (FAILED) → replanned to <code className="text-red">retry_72h</code> (72-hour delay + unnecessary customer friction).
          </div>
        </div>

        <div className="p-2 border border-green/30 bg-green/5">
          <div className="text-green font-semibold text-[10px] uppercase tracking-wide">
            • LLM Path (Simulated Stub)
          </div>
          <div className="text-muted text-[11px] mt-0.5">
            Correctly inferred <span className="text-green font-semibold">{ep.llm_inferred}</span> (matching Ground Truth) → executed <code className="text-green">retry_1h</code>, successfully recovering <span className="text-text font-semibold">{fmt_inr(ep.amount_inr)}</span> in 1 hour with 0 customer friction (<span className="text-signal-blue font-semibold">71 hours faster</span>).
          </div>
        </div>
      </div>
    </div>
  )
}
