/**
 * RazorpayStatus — honest display of the Razorpay integration state.
 *
 * The integration layer (razorpay_integration/) is implemented against
 * Razorpay's documented API contract. It has NOT been verified against
 * Razorpay's live test infrastructure — KYC/PAN was not submitted.
 *
 * What IS verified: payload parsing, mock fallback, EU pipeline on a
 * locally-constructed representative payload.
 */

import React, { useState, useEffect } from 'react'

const API = 'http://localhost:8000'

export default function RazorpayStatus() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API}/razorpay/status`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => {
        setError('Backend not running. Start with: py -m api.server')
        setLoading(false)
      })
  }, [])

  if (loading) {
    return (
      <div className="p-3 font-mono text-[10px] text-muted flex items-center gap-2">
        <div className="w-2.5 h-2.5 border border-signal-blue border-t-transparent rounded-full animate-spin" />
        Loading…
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-3 font-mono text-[10px] text-red/70 border border-red/30 bg-red/5">
        {error}
      </div>
    )
  }

  return (
    <div className="border border-border font-sans text-xs">
      {/* Header — always shows the honest state */}
      <div className="px-3 py-2 border-b border-border bg-panel/40 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-amber-400 shrink-0" />
          <span className="font-mono text-[10px] font-semibold text-muted uppercase tracking-wider">
            Razorpay Integration
          </span>
        </div>
        {/* Permanent honest status badge — never changes to "LIVE" */}
        <span className="font-mono text-[9px] px-1.5 py-0.5 border border-amber-500/40 text-amber-300 bg-amber-950/30 rounded">
          IMPLEMENTED · NOT LIVE-VERIFIED
        </span>
      </div>

      <div className="p-3 space-y-3">
        {/* Permanent disclosure */}
        <div className="font-mono text-[9px] text-amber-300/80 border border-amber-500/20 bg-amber-950/10 p-2 leading-relaxed">
          KYC/PAN submission was not completed — live test-mode API calls have
          not been made against api.razorpay.com. The integration is contract-verified
          locally only.
        </div>

        {/* What IS verified */}
        <div className="space-y-1">
          <div className="font-sans text-[9px] font-semibold text-muted uppercase tracking-wider">
            Verified locally
          </div>
          {[
            'payment.failed payload parsing → EU pipeline (representative payload)',
            'Mock fallback behavior when no credentials configured',
            'HMAC-SHA256 signature validation logic (against Razorpay spec)',
            'payment_links endpoint structure (razorpay-python 2.0.1 SDK)',
          ].map((item, i) => (
            <div key={i} className="flex items-start gap-1.5 font-mono text-[9px] text-green/70">
              <span className="shrink-0 mt-0.5">✓</span>
              <span>{item}</span>
            </div>
          ))}
        </div>

        {/* What is NOT verified */}
        <div className="space-y-1">
          <div className="font-sans text-[9px] font-semibold text-muted uppercase tracking-wider">
            Not verified (no live API calls made)
          </div>
          {[
            'Actual HTTP call to api.razorpay.com/v1/payment_links',
            'Real payment.failed webhook from Razorpay servers',
            'Signature validation against a real Razorpay-signed payload',
          ].map((item, i) => (
            <div key={i} className="flex items-start gap-1.5 font-mono text-[9px] text-muted">
              <span className="shrink-0 mt-0.5 text-amber-400">~</span>
              <span>{item}</span>
            </div>
          ))}
        </div>

        {/* Demo instructions — what CAN be shown on camera */}
        <div className="border-t border-border/40 pt-2 space-y-1">
          <div className="font-sans text-[9px] font-semibold text-muted uppercase tracking-wider">
            What you can show on camera (honestly)
          </div>
          <div className="font-mono text-[9px] text-muted space-y-0.5">
            <div>• EU pipeline on Razorpay payload: <span className="text-text">py -m razorpay_integration.demo_local</span></div>
            <div>• Integration status: <span className="text-text">GET /razorpay/status</span></div>
            <div>• Contract code: <span className="text-text">razorpay_integration/client.py</span></div>
          </div>
          <div className="font-mono text-[9px] text-border mt-1">
            Label as "contract-implemented, locally verified" — not as a live API call.
          </div>
        </div>

        {/* Always-mock label for retry actions */}
        <div className="border-t border-border/40 pt-2">
          <div className="font-sans text-[9px] font-semibold text-muted uppercase tracking-wider mb-1">
            Always mock (no Razorpay API equivalent)
          </div>
          <div className="font-mono text-[9px] text-muted">
            retry_1h / retry_72h / retry_alternate_route — no real retry endpoint exists in Razorpay
          </div>
        </div>
      </div>
    </div>
  )
}
