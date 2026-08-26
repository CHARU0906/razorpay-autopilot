import React from 'react'
import { LLM_EPISODE_216 } from '../data/episodeData.js'

function fmt_inr(n) {
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function LlmReasoningPanel({ onClose }) {
  const ep = LLM_EPISODE_216

  return (
    <div
      className="border border-signal-blue/40 bg-panel shadow-2xl max-w-xl w-full flex flex-col rounded-none"
      style={{ background: '#141B26', maxHeight: '85vh' }}
    >
      {/* Sticky Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0 sticky top-0 bg-[#141B26] z-10">
        <div className="flex items-center gap-2.5">
          <div className="w-2.5 h-2.5 rounded-full bg-signal-blue animate-pulse" />
          <span className="font-sans text-xs font-semibold text-signal-blue uppercase tracking-wider">
            Classification: LLM-Assisted (Simulated)
          </span>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="font-mono text-xs text-muted hover:text-text hover:bg-border/50 transition-colors px-2 py-1 border border-border"
            aria-label="Close modal"
          >
            ✕ CLOSE
          </button>
        )}
      </div>

      {/* Scrollable Content Body */}
      <div className="p-5 overflow-y-auto space-y-4 font-sans text-xs" style={{ minHeight: 0 }}>
        {/* Production & Spec Note */}
        <div className="p-3 bg-panel/80 border border-border leading-relaxed text-muted">
          <span className="font-semibold text-text">Note:</span> In production, this step calls an LLM to classify ambiguous failure signals. In this benchmark demo, a deterministic keyword-matching stub is used as the LLM fallback (per SPEC P8 — no live LLM in the critical path).
        </div>

        {/* Core Explanation & Fallback Reasoning */}
        <div className="leading-relaxed text-text space-y-2">
          <p>
            The stub evaluated the failure message (<code className="font-mono text-amber text-[11px] bg-black/40 px-1 py-0.5 border border-border">{`'${ep.failure_message}'`}</code>) against its keyword rules, found no match, and applied its default fallback — classifying episode <code className="font-mono text-signal-blue text-[11px] bg-black/40 px-1 py-0.5 border border-border">{ep.episode_id}</code> as <code className="font-mono text-green text-[11px] bg-black/40 px-1 py-0.5 border border-border">{ep.llm_inferred}</code> with the reasoning:
          </p>
          <div className="font-mono text-[11px] p-2.5 bg-black/60 border border-signal-blue/40 text-signal-blue">
            "{ep.llm_reasoning}"
          </div>
          <p className="text-muted text-[11px] italic leading-normal">
            All ambiguous-population failure messages in this benchmark are deliberately uninformative (e.g. <code className="font-mono text-[10px]">'Do not honour'</code>), so the LLM path's role here is providing a better-calibrated default than the risk-score heuristic alone, rather than parsing rich text signal.
          </p>
        </div>

        {/* Episode Metadata Grid */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 p-3 bg-black/40 border border-border font-mono text-[11px]">
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
            <span className="text-amber font-semibold">{ep.failure_code}</span>
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
        <div className="border-t border-border pt-3 space-y-2.5 font-mono text-[11px]">
          <div className="font-sans text-[10px] font-semibold text-muted uppercase tracking-wider">
            Benchmark Outcome Impact
          </div>

          <div className="p-3 border border-red/40 bg-red/10">
            <div className="text-red font-semibold text-[10px] uppercase tracking-wide flex items-center justify-between">
              <span>• Deterministic Heuristic Path</span>
              <span className="text-[9px] text-red/80 font-normal">72h delay</span>
            </div>
            <div className="text-muted text-[11px] mt-1 leading-normal">
              Inferred <span className="text-text font-semibold">{ep.heuristic_inferred}</span> → executed <code className="text-red">send_recovery_link</code> (FAILED) → replanned to <code className="text-red">retry_72h</code> (72-hour delay + unnecessary customer friction).
            </div>
          </div>

          <div className="p-3 border border-green/40 bg-green/10">
            <div className="text-green font-semibold text-[10px] uppercase tracking-wide flex items-center justify-between">
              <span>• LLM Path (Simulated Stub)</span>
              <span className="text-[9px] text-green/80 font-normal">1h recovery</span>
            </div>
            <div className="text-muted text-[11px] mt-1 leading-normal">
              Correctly inferred <span className="text-green font-semibold">{ep.llm_inferred}</span> (matching Ground Truth) → executed <code className="text-green">retry_1h</code>, successfully recovering <span className="text-text font-semibold">{fmt_inr(ep.amount_inr)}</span> in 1 hour with 0 customer friction (<span className="text-signal-blue font-semibold">71 hours faster</span>).
            </div>
          </div>
        </div>
      </div>

      {/* Sticky Footer */}
      {onClose && (
        <div className="px-5 py-3 border-t border-border shrink-0 bg-[#141B26] flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 font-sans text-xs font-medium text-text bg-signal-blue/20 hover:bg-signal-blue/30 border border-signal-blue/50 transition-colors uppercase tracking-wider"
          >
            Done · Close Panel
          </button>
        </div>
      )}
    </div>
  )
}
