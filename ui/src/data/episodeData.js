/**
 * Real episode data for the UI — sourced from actual Phase 3 traces.
 * ep_1_1406: auth_required, risk_score=0.9198, amount=3857 INR
 * This is the actual policy-gated episode confirmed working in Phase 3.
 */

export const GATED_EPISODE = {
  episode_id: 'ep_1_1406',
  merchant_id: 'merch_04',
  merchant_vertical: 'edtech',
  customer_id: 'cust_0281',
  amount_inr: 3857.33,
  currency: 'INR',
  failure_code: 'authentication_failed',
  failure_message: 'Authentication failed or was not completed',
  failure_source: 'issuer',
  payment_method: 'card',
  card_network: null,
  issuer_bank_code: 'ICICI',
  country: 'IN',
  risk_score_gateway: 0.9198,
  lifetime_value_inr: 53914.70,
  email_engagement_score: 0.412,
  sim_hour: 156.48,
  // What Autopilot wanted to do
  strategist_recommendation: 'request_reauth',
  strategist_eu: 2339.20,
  strategist_p: 0.720,
  // Why it was gated
  gate_reason: 'risk_score 0.920 ≥ autonomous threshold 0.850 with customer-visible action',
  gate_tier: 'requires-human',
  // Policy override
  policy_action: 'escalate_to_merchant',
  policy_params: { queue: 'recovery_ops', note: 'risk_score=0.920' },
  // Expected recovery if approved
  expected_recovery_inr: Math.round(2339.20 + 3857.33 * 0.002),
}

/**
 * Incident episode for the active incident panel.
 * ep_1_34: INC-1, IN/rupay/HDFC, sim_hour=253.57
 */
export const INCIDENT_EPISODE = {
  episode_id: 'ep_1_34',
  incident_id: 'INC-1',
  cohort: 'IN / rupay / HDFC',
  sim_hour: 253.57,
  incident_start_h: 240.0,
  incident_window_h: 18,
  trajectory: [
    { offset_h: 0.0,  success_rate: 0.94 },
    { offset_h: 4.5,  success_rate: 0.91 },
    { offset_h: 9.0,  success_rate: 0.87 },
    { offset_h: 13.5, success_rate: 0.82 },
  ],
  current_rate: 0.82,
  detection_latency_h: 8.5,
  affected_episodes: 80,
  right_answer: 'hold_for_incident',
}

/**
 * Phase 3 trace log entries for ep_1_34 — real output from autopilot.trace_episode.
 * These are verbatim from the Phase 3 single-episode trace.
 */
export const TRACE_LOG_ENTRIES = [
  {
    ts: '2026-01-11T13:34:07Z',
    stage: 'investigator',
    tier: 'automatic',
    episode_id: 'ep_1_34',
    text: 'inferred_class=regional_degradation  confidence=0.82  flags=[possible_degradation]',
  },
  {
    ts: '2026-01-11T13:34:07Z',
    stage: 'strategist',
    tier: 'automatic',
    episode_id: 'ep_1_34',
    text: 'retry_1h EU=7261.86 INR  P=0.745  retry_alternate_route EU=6969.64  hold_for_incident EU=1167.44',
  },
  {
    ts: '2026-01-11T13:34:07Z',
    stage: 'policy',
    tier: 'automatic',
    episode_id: 'ep_1_34',
    text: 'tier=automatic  action=retry_1h  reason=Within automatic autonomy thresholds',
  },
  {
    ts: '2026-01-11T13:35:07Z',
    stage: 'action',
    tier: 'automatic',
    episode_id: 'ep_1_34',
    text: 'tool=MockRetryAPI  action=retry_1h  p_eff=0.4068  outcome=FAILURE',
  },
  {
    ts: '2026-01-11T13:35:07Z',
    stage: 'outcome',
    tier: 'failure',
    episode_id: 'ep_1_34',
    text: 'retry_1h FAILED (p_eff=0.407, attempt=1) — outcome-driven replanning #1',
  },
  {
    ts: '2026-01-11T13:35:07Z',
    stage: 'investigator',
    tier: 'automatic',
    episode_id: 'ep_1_34',
    text: 'inferred_class=regional_degradation  confidence=0.82  [replan #1]',
  },
  {
    ts: '2026-01-11T13:35:07Z',
    stage: 'strategist',
    tier: 'automatic',
    episode_id: 'ep_1_34',
    text: 'retry_1h EU=6317.49 INR  P=0.648  [fatigue applied, attempt_k=1]',
  },
  {
    ts: '2026-01-11T13:35:07Z',
    stage: 'policy',
    tier: 'automatic',
    episode_id: 'ep_1_34',
    text: 'tier=automatic  action=retry_1h  reason=Within automatic autonomy thresholds',
  },
  {
    ts: '2026-01-11T13:36:07Z',
    stage: 'action',
    tier: 'automatic',
    episode_id: 'ep_1_34',
    text: 'tool=MockRetryAPI  action=retry_1h  p_eff=0.3557  outcome=SUCCESS',
  },
  {
    ts: '2026-01-11T13:36:07Z',
    stage: 'outcome',
    tier: 'success',
    episode_id: 'ep_1_34',
    text: 'retry_1h SUCCEEDED (p_eff=0.356, attempt=2) — ₹9,751.87 recovered',
  },
  {
    ts: '2026-01-11T13:36:10Z',
    stage: 'investigator',
    tier: 'approval',
    episode_id: 'ep_1_1406',
    text: 'inferred_class=auth_required  confidence=0.92  flags=[auth_signal]',
  },
  {
    ts: '2026-01-11T13:36:10Z',
    stage: 'strategist',
    tier: 'approval',
    episode_id: 'ep_1_1406',
    text: 'request_reauth EU=2339.20 INR  P=0.720  [best action for auth_required]',
  },
  {
    ts: '2026-01-11T13:36:10Z',
    stage: 'policy',
    tier: 'approval',
    episode_id: 'ep_1_1406',
    text: 'tier=requires-human  risk_score=0.920 ≥ 0.850  → escalate_to_merchant  AWAITING APPROVAL',
  },
]
