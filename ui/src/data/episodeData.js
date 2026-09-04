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
  // Causal-chain diagnostics
  causal_chain: [
    '1. Observed Signal: failure_code=authentication_failed, auth_state=attempted_failed on ICICI card',
    '2. Risk Context: gateway_risk_score=0.9198 (elevated risk tier), customer LTV=₹53,915',
    '3. Causal Mechanism: Mandatory 3DS challenge / mandate auth expired, but elevated risk score prevents automated customer contact',
    '4. Ruled Out: Transient gateway blip, account funds deficit, card expiry',
    '5. Action Space Constraints: Policy Engine enforces human review gate before dispatching high-risk customer outreach',
  ],
  eliminated_hypotheses: ['transient_timeout', 'insufficient_funds', 'card_expired'],
  diagnostic_summary: 'Authentication challenge required, but elevated risk score (0.920 ≥ 0.850) triggers mandatory human escalation gate.',
}

/**
 * ep_1_216: do_not_honour, risk_score=0.686, amount=5205.68 INR
 * Real Phase 3 trace candidate for Fix 5 (LLM Reasoning Example - Transparency Panel).
 */
export const LLM_EPISODE_216 = {
  episode_id: 'ep_1_216',
  failure_code: 'do_not_honour',
  failure_message: 'Do not honour',
  amount_inr: 5205.68,
  payment_method: 'card',
  card_network: 'mastercard',
  issuer_bank_code: 'AXIS',
  merchant_vertical: 'insurance',
  risk_score_gateway: 0.686,
  prior_soft_declines: 1,
  ground_truth_class: 'transient',
  ground_truth_optimal: 'retry_1h',
  heuristic_inferred: 'insufficient_funds',
  heuristic_action: 'send_recovery_link (failed) → retry_72h (72h delay)',
  llm_inferred: 'transient',
  llm_reasoning: '[LLM-stub] no strong signal in failure_message; defaulting to transient',
  llm_action: 'retry_1h (succeeded in 1h, 0 friction)',
  causal_chain: [
    '1. Observed Signal: ambiguous decline code do_not_honour with raw message "Do not honour"',
    '2. Context: AXIS card, merchant vertical=insurance, risk_score=0.686, soft_declines=1',
    '3. LLM Causal Diagnosis: Generic issuer decline without fraud flag; classified as transient processing blip',
    '4. Ruled Out: Permanent fraud block (risk < 0.75), card expiry',
    '5. Action Space Constraints: Immediate silent retry (1h) executed with zero customer friction',
  ],
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
  causal_chain: [
    '1. Monitored Cohort: IN|rupay|HDFC (acquirer_route_id=route_c)',
    '2. Detector State: Cohort rolling success rate degraded from 0.94 to 0.82 across 80 episodes',
    '3. Causal Mechanism: Live HDFC RuPay switch processing degradation (infrastructure fault, NOT customer failure)',
    '4. Ruled Out: Customer solvency failure, credential expiry, 3DS authentication gap',
    '5. Action Space Constraints: Customer nudges strictly blocked (zero customer friction); downstream actions restricted to {hold_for_incident, retry_alternate_route, escalate}',
  ],
  diagnostic_summary: 'Correlated issuer degradation on HDFC RuPay route. Autopilot suppresses customer friction and holds until incident resolution.',
}

/**
 * ep_1_1196: expired_card + has_alternate_instrument_on_file=True
 * The "cost of a bad rule" episode for Phase 3 demo.
 *
 * Rule-Based fires request_new_payment_method (P=0.65, C_friction=₹1,469 → EU=-₹803)
 * Autopilot picks hold_for_incident / retry_alternate_route (zero friction, EU=+₹29/+₹23)
 *
 * This is a Regime A episode from seed=1. In Regime B heterogeneous GT, this pattern
 * drives the 39.8% UIR spike on the expired_card population.
 *
 * Sourced from actual strategist.py output on this episode — not fabricated.
 */
export const BAD_RULE_EPISODE = {
  episode_id: 'ep_1_1196',
  failure_code: 'card_expired',
  failure_message: 'Card expired',
  amount_inr: 1039.08,
  payment_method: 'card',
  card_expiry_state: 'expired',
  has_alternate_instrument_on_file: true,
  token_type: 'network_token',
  lifetime_value_inr: 75705.56,
  email_engagement_score: 0.424,
  // What Rule-Based does
  rb_action: 'request_new_payment_method',
  rb_rationale: 'Rule R2: card_expired → always request_new_payment_method. Does not check has_alternate_instrument_on_file=true.',
  rb_p_success: 0.65,
  rb_c_friction: 1468.69,  // P(churn_increment) × LTV × engagement_factor
  rb_eu: -803.16,          // 0.65 × ₹1,039 - ₹1,469 = -₹803
  rb_is_friction: true,
  // What Autopilot does (EU scoring with explicit friction cost)
  ap_action: 'hold_for_incident',  // winner by EU
  ap_action_alt: 'retry_alternate_route',  // second option, also zero-friction
  ap_eu: 28.96,
  ap_p_success: 0.030,
  ap_c_friction: 0,
  ap_is_friction: false,
  // The friction comparison
  friction_avoided_inr: 1468.69,  // C_friction that Rule-Based would incur
  // Causal reasoning
  ap_reasoning: 'Investigator: expired_card with alternate instrument on file and network token. Strategist: request_new_payment_method EU=-₹803 (C_friction=₹1,469 > P×Revenue). Zero-friction alternatives available with positive EU.',
}

/**
 * Promise-to-Pay walkthrough data — verified from bench/test_promise_tracker.py (3/3 passing)
 * and from actual Strategist EU scores on ep_1_8 (monthly IF subscriber).
 *
 * EU scores sourced from running score_all_actions on ep_1_8 with replan state
 * (after retry_72h failure, attempt_k=1).
 */
export const P2P_EPISODE = {
  episode_id: 'ep_1_8',
  failure_code: 'insufficient_funds',
  failure_message: 'Insufficient funds in account',
  amount_inr: 201316.5,
  billing_cycle: 'monthly',
  avg_days_between_txns: 39.94,
  lifetime_value_inr: 34095.89,
  email_engagement_score: 0.347,
  // EU scores after retry_72h failed (replan #1 state)
  // Source: score_all_actions(ep_1_8, state={attempt_k=1, replan_count=1})
  strategist_top3: [
    {
      action_id: 'retry_7d',
      eu: 94541.90,
      p_success: 0.476,
      c_friction: 0.00,
      p_source: 'model-scored',
      winner: true,
    },
    {
      action_id: 'send_recovery_link',
      eu: 83771.73,
      p_success: 0.418,
      c_friction: 232.75,
      p_source: 'prior-scored',
      winner: false,
    },
    {
      action_id: 'send_dunning_notification',
      eu: 66466.49,
      p_success: 0.331,
      c_friction: 58.19,
      p_source: 'prior-scored',
      winner: false,
    },
  ],
  // Case A: fulfilled promise
  case_a: {
    action: 'log_promise_to_pay',
    tool: 'MockPromiseAPI',
    due_in_hours: 72.0,
    channel: 'whatsapp',
    outcome: 'FULFILLED',
    log: '[ep_1_8] ✓ Promise-to-Pay FULFILLED on time (due_h=72.0h, attempt=1) — recovered',
  },
  // Case B: broken promise → replan
  case_b: {
    action: 'log_promise_to_pay',
    tool: 'MockPromiseAPI',
    due_in_hours: 48.0,
    channel: 'sms',
    outcome: 'BROKEN',
    log: '[ep_1_8] ✗ Promise-to-Pay BROKEN (due date passed without settlement) — feeding back into replanning loop (replan #1)',
    replan_state: { replan_count: 1, promise_broken: true },
  },
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
