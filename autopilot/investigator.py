"""Investigator — Stage 1 of the Autopilot pipeline (SPEC §5, P7).

Deterministic rules first; LLM call only for ambiguous episodes.
The LLM path is a stub that returns a structured result — enabling Phase 7
demo mode (LLM disabled) with no code changes.

Output: InvestigatorResult — a structured failure classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Failure codes whose observed signal is unambiguous → deterministic path.
HARD_STOP_CODES = frozenset({"stolen_or_lost_card", "risk_blocked", "payment_method_restricted"})
CLEAR_CODES: dict[str, str] = {
    "insufficient_funds": "insufficient_funds",
    "card_expired": "expired_card",
    "authentication_failed": "auth_required",
    "mandate_revoked": "auth_required",   # may be overridden by auth_state check below
    "issuer_down": "regional_degradation",
    "network_timeout": "transient",
    "GATEWAY_ERROR": "transient",
    "do_not_honour": "transient",         # ambiguous by spec; treated as soft transient here
    "risk_blocked": "non_recoverable",
    "stolen_or_lost_card": "non_recoverable",
    "payment_method_restricted": "non_recoverable",
}
AMBIGUOUS_CODES = frozenset({"do_not_honour", "GATEWAY_ERROR", "unknown_error"})
MANDATE_METHODS = frozenset({"upi_autopay", "emandate_nach"})


@dataclass
class InvestigatorResult:
    episode_id: str
    inferred_class: str             # e.g. "transient", "auth_required", …
    observability: str              # "clear" | "ambiguous"
    confidence: float               # 0–1; <0.6 triggers LLM path
    flags: list[str] = field(default_factory=list)
    llm_used: bool = False
    llm_reasoning: Optional[str] = None
    # Set by degradation detector (Phase 5 integration point)
    incident_id: Optional[str] = None
    incident_active: bool = False
    # Task 3: Root-cause causal diagnostic output
    causal_chain: list[str] = field(default_factory=list)
    diagnostic_summary: str = ""
    eliminated_hypotheses: list[str] = field(default_factory=list)
    action_space_constraints: list[str] = field(default_factory=list)


def _build_causal_diagnostics(
    inferred_class: str,
    observed: dict,
    confidence: float,
    flags: list[str],
    llm_used: bool = False,
    llm_reasoning: str | None = None,
    incident_active: bool = False,
    incident_id: str | None = None,
) -> tuple[list[str], str, list[str], list[str]]:
    """Construct a transparent multi-step causal diagnosis chain."""
    eid = observed.get("episode_id", "")
    code = observed.get("failure_code") or "unknown_error"
    source = observed.get("failure_source") or "gateway"
    auth = observed.get("auth_state") or "not_required"
    expiry = observed.get("card_expiry_state") or "valid"
    method = observed.get("payment_method") or "card"
    network = observed.get("card_network") or "standard"
    issuer = observed.get("issuer_bank_code") or "bank"
    route = observed.get("acquirer_route_id") or "route_a"
    country = observed.get("country") or "IN"
    risk = float(observed.get("risk_score_gateway") or 0.0)
    amount = float(observed.get("amount_inr") or 0.0)
    ltv = float(observed.get("lifetime_value_inr") or 0.0)
    soft = int(observed.get("prior_soft_declines_on_instrument_30d") or 0)
    cycle = observed.get("billing_cycle") or "recurring"
    cadence = float(observed.get("avg_days_between_txns") or 30.0)
    has_alt = bool(observed.get("has_alternate_instrument_on_file"))
    token = observed.get("token_type") or "none"
    cross = bool(observed.get("is_cross_border"))

    chain: list[str] = []
    eliminated: list[str] = []
    constraints: list[str] = []
    summary = ""

    if inferred_class == "non_recoverable":
        summary = f"Hard decline / compliance security block on {code}; automated recovery suppressed to prevent regulatory/financial risk."
        chain = [
            f"1. Observed Signal: failure_code='{code}' from source='{source}' on instrument={method} (risk_score={risk:.3f})",
            f"2. History & Context: {soft} prior soft declines, customer tenure={observed.get('customer_tenure_days', 0)}d, LTV=₹{ltv:,.0f}",
            f"3. Causal Mechanism: Irreversible decline (stolen/restricted credential or risk engine block) at issuer/risk gateway layer",
            f"4. Ruled Out: Transient gateway timeout, liquidity timing mismatch, temporary 3DS challenge",
            f"5. Action Space Constraints: Automated retry ladders strictly prohibited; restricted to {{escalate_to_merchant, stop}}",
        ]
        eliminated = ["transient_blip", "funds_timing_mismatch", "auth_challenge"]
        constraints = ["stop", "escalate_to_merchant"]

    elif inferred_class == "expired_card":
        summary = "Stored payment instrument expired at network/issuer level; silent same-route retries invalid."
        chain = [
            f"1. Observed Signal: failure_code='{code}', card_expiry_state='{expiry}' on {method}|{network}|{issuer}",
            f"2. Context: has_alternate_instrument_on_file={has_alt}, token_type='{token}', customer email_engagement={float(observed.get('email_engagement_score', 0)):.2f}",
            f"3. Causal Mechanism: Stored payment credential expiration date exceeded; issuer rejects pre-auth authorization",
            f"4. Ruled Out: Temporary network timeout, customer account insolvency, 3DS authentication challenge",
            f"5. Action Space Constraints: Same-route silent retries suppressed (P_eff ≈ 0.0); restricted to {{request_new_payment_method, send_recovery_link, retry_alternate_route}}",
        ]
        eliminated = ["transient_network_blip", "insufficient_funds", "fraud_block"]
        constraints = ["request_new_payment_method", "send_recovery_link", "retry_alternate_route"]

    elif inferred_class == "auth_required":
        summary = "Mandate or transaction authentication (SCA/3DS) challenge pending; re-authorization required."
        chain = [
            f"1. Observed Signal: failure_code='{code}', auth_state='{auth}' on {method} (mandate_status='{observed.get('mandate_status', 'none')}')",
            f"2. Context: Recurring {cycle} charge of ₹{amount:,.0f}, lifetime successful txns={observed.get('lifetime_successful_txns', 0)}",
            f"3. Causal Mechanism: Regulatory SCA/Two-Factor Challenge or expired AutoPay mandate consent requiring customer re-authentication",
            f"4. Ruled Out: Account insolvency, card credential expiration, gateway infrastructure failure",
            f"5. Action Space Constraints: Silent retries suppressed (P_eff ≈ 0.0); restricted to {{request_reauth, send_recovery_link, escalate_to_merchant}}",
        ]
        eliminated = ["insufficient_funds", "expired_card", "infrastructure_outage"]
        constraints = ["request_reauth", "send_recovery_link", "escalate_to_merchant"]

    elif inferred_class == "insufficient_funds":
        summary = f"Soft decline due to balance liquidity timing mismatch ({cycle} billing cycle); recovery requires timing delay."
        chain = [
            f"1. Observed Signal: failure_code='insufficient_funds' from issuer={issuer} for amount=₹{amount:,.0f}",
            f"2. Context: {cycle} billing cadence (avg txn interval={cadence:.1f}d), tenure={observed.get('customer_tenure_days', 0)}d, LTV=₹{ltv:,.0f}",
            f"3. Causal Mechanism: Scheduled charge landed prior to customer account liquidity replenishment / salary top-up",
            f"4. Ruled Out: Irreversible fraud block, invalid credentials, gateway communication timeout",
            f"5. Action Space Constraints: Immediate short retries (1h/6h) suppressed to conserve attempt budget; delayed retries (72h/7d) and recovery links enabled",
        ]
        eliminated = ["fraud_block", "expired_credential", "gateway_timeout"]
        constraints = ["retry_72h", "retry_7d", "send_recovery_link", "send_dunning_notification"]

    elif inferred_class == "regional_degradation":
        summary = f"Correlated route/issuer infrastructure degradation on [{country}|{network}|{issuer}]; customer-side friction prohibited."
        chain = [
            f"1. Observed Signal: failure_code='{code}' on cohort [{country}|{network}|{issuer}] via {route}",
            f"2. Degradation Context: Cross-episode failure rate spike detected across cohort (active incident={incident_id or 'evaluating'})",
            f"3. Causal Mechanism: Upstream issuer switch or acquirer pipeline degradation (live infrastructure incident, NOT customer insolvency)",
            f"4. Ruled Out: Customer balance deficit, expired card credential, fraud block",
            f"5. Action Space Constraints: Customer friction actions strictly suppressed (zero customer friction); restricted to {{hold_for_incident, retry_alternate_route, escalate_to_merchant}}",
        ]
        eliminated = ["customer_insolvency", "expired_card", "customer_auth_fault"]
        constraints = ["hold_for_incident", "retry_alternate_route", "escalate_to_merchant"]

    elif inferred_class == "transient":
        summary = "Transient packet loss or gateway latency timeout; recoverable via short silent retry or route fallback."
        chain = [
            f"1. Observed Signal: failure_code='{code}' from source='{source}' (cross_border={cross})",
            f"2. Context: amount=₹{amount:,.0f}, gateway_risk={risk:.3f}, prior soft declines={soft}",
            f"3. Causal Mechanism: Temporary network socket timeout or upstream processor queue saturation during settlement handshake",
            f"4. Ruled Out: Hard decline, card credential expiration, customer insolvency",
            f"5. Action Space Constraints: Short silent retries (1h/6h) or alternate route fallback; customer friction actions avoided",
        ]
        eliminated = ["hard_decline", "expired_card", "customer_insolvency"]
        constraints = ["retry_1h", "retry_6h", "retry_alternate_route"]

    else:
        summary = f"Ambiguous decline code '{code}' evaluated via multi-signal inference (confidence={confidence:.2f})."
        chain = [
            f"1. Observed Signal: ambiguous failure_code='{code}' from source='{source}'",
            f"2. Context: risk_score={risk:.3f}, soft_declines={soft}, failure_message='{observed.get('failure_message', '')}'",
            f"3. Multi-Signal Inference: Supporting indicators classify episode as {inferred_class}" + (f" ({llm_reasoning})" if llm_used else ""),
            f"4. Ruled Out: Unambiguous hard deterministic classification",
            f"5. Action Space Constraints: Filtered to safe candidate action space for {inferred_class}",
        ]
        eliminated = ["unambiguous_hard_stop"]
        constraints = ["retry_1h", "retry_6h", "retry_24h", "send_recovery_link", "escalate_to_merchant"]

    return chain, summary, eliminated, constraints


def investigate(observed: dict, episode_state: dict, *, llm_enabled: bool = False) -> InvestigatorResult:
    """Run deterministic classification; fall through to LLM only if ambiguous."""
    eid = observed["episode_id"]
    code = observed.get("failure_code") or "unknown_error"
    auth = observed.get("auth_state") or "not_required"
    expiry = observed.get("card_expiry_state") or "valid"
    method = observed.get("payment_method") or "card"
    source = observed.get("failure_source") or "gateway"
    risk = float(observed.get("risk_score_gateway") or 0.0)

    flags: list[str] = []

    # --- R1: hard-stop codes → non_recoverable, high confidence ---
    if code in HARD_STOP_CODES:
        flags = ["hard_stop_code"]
        chain, summary, elim, constr = _build_causal_diagnostics(
            "non_recoverable", observed, 0.98, flags
        )
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="non_recoverable",
            observability="clear",
            confidence=0.98,
            flags=flags,
            causal_chain=chain,
            diagnostic_summary=summary,
            eliminated_hypotheses=elim,
            action_space_constraints=constr,
        )

    # --- R2: explicit expiry signal ---
    if code == "card_expired" or expiry == "expired":
        flags = ["expired_card_signal"]
        chain, summary, elim, constr = _build_causal_diagnostics(
            "expired_card", observed, 0.95, flags
        )
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="expired_card",
            observability="clear",
            confidence=0.95,
            flags=flags,
            causal_chain=chain,
            diagnostic_summary=summary,
            eliminated_hypotheses=elim,
            action_space_constraints=constr,
        )

    # --- R3: auth signals ---
    if (
        code == "authentication_failed"
        or auth in {"attempted_failed", "mandate_auth_pending"}
        or (code == "mandate_revoked" and method in MANDATE_METHODS)
    ):
        flags = ["auth_signal"]
        chain, summary, elim, constr = _build_causal_diagnostics(
            "auth_required", observed, 0.92, flags
        )
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="auth_required",
            observability="clear",
            confidence=0.92,
            flags=flags,
            causal_chain=chain,
            diagnostic_summary=summary,
            eliminated_hypotheses=elim,
            action_space_constraints=constr,
        )

    # --- R4: mandate revoked but not a mandate method → non_recoverable ---
    if code == "mandate_revoked":
        flags = ["mandate_revoked_non_mandate_method"]
        chain, summary, elim, constr = _build_causal_diagnostics(
            "non_recoverable", observed, 0.85, flags
        )
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="non_recoverable",
            observability="clear",
            confidence=0.85,
            flags=flags,
            causal_chain=chain,
            diagnostic_summary=summary,
            eliminated_hypotheses=elim,
            action_space_constraints=constr,
        )

    # --- R5: clear funds signal ---
    if code == "insufficient_funds":
        flags = ["funds_signal"]
        chain, summary, elim, constr = _build_causal_diagnostics(
            "insufficient_funds", observed, 0.95, flags
        )
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="insufficient_funds",
            observability="clear",
            confidence=0.95,
            flags=flags,
            causal_chain=chain,
            diagnostic_summary=summary,
            eliminated_hypotheses=elim,
            action_space_constraints=constr,
        )

    # --- R6: issuer_down → regional_degradation (investigated further by detector) ---
    if code == "issuer_down":
        flags = ["possible_degradation"]
        chain, summary, elim, constr = _build_causal_diagnostics(
            "regional_degradation", observed, 0.82, flags
        )
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="regional_degradation",
            observability="clear",
            confidence=0.82,
            flags=flags,
            causal_chain=chain,
            diagnostic_summary=summary,
            eliminated_hypotheses=elim,
            action_space_constraints=constr,
        )

    # --- R7: network_timeout → transient ---
    if code == "network_timeout":
        flags = ["network_timeout"]
        chain, summary, elim, constr = _build_causal_diagnostics(
            "transient", observed, 0.80, flags
        )
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="transient",
            observability="clear",
            confidence=0.80,
            flags=flags,
            causal_chain=chain,
            diagnostic_summary=summary,
            eliminated_hypotheses=elim,
            action_space_constraints=constr,
        )

    # --- Ambiguous territory: do_not_honour, GATEWAY_ERROR, unknown_error ---
    inferred = _heuristic_ambiguous(code, observed)
    confidence = _ambiguous_confidence(code, observed)

    if confidence < 0.60 and llm_enabled:
        llm_class, llm_reason = _llm_classify_stub(observed)
        flags = ["llm_path"] + flags
        chain, summary, elim, constr = _build_causal_diagnostics(
            llm_class, observed, 0.70, flags, llm_used=True, llm_reasoning=llm_reason
        )
        return InvestigatorResult(
            episode_id=eid,
            inferred_class=llm_class,
            observability="ambiguous",
            confidence=0.70,
            flags=flags,
            llm_used=True,
            llm_reasoning=llm_reason,
            causal_chain=chain,
            diagnostic_summary=summary,
            eliminated_hypotheses=elim,
            action_space_constraints=constr,
        )

    flags = ["ambiguous_code"] + flags
    chain, summary, elim, constr = _build_causal_diagnostics(
        inferred, observed, confidence, flags
    )
    return InvestigatorResult(
        episode_id=eid,
        inferred_class=inferred,
        observability="ambiguous",
        confidence=confidence,
        flags=flags,
        causal_chain=chain,
        diagnostic_summary=summary,
        eliminated_hypotheses=elim,
        action_space_constraints=constr,
    )


def _heuristic_ambiguous(code: str, observed: dict) -> str:
    """Best deterministic guess for ambiguous codes using supporting signals."""
    risk = float(observed.get("risk_score_gateway") or 0.0)
    source = observed.get("failure_source") or "gateway"
    soft_declines = int(observed.get("prior_soft_declines_on_instrument_30d") or 0)

    if code == "GATEWAY_ERROR":
        return "transient"
    if code == "do_not_honour":
        # High risk score + multiple soft declines → non_recoverable; else treat as funds-like
        if risk > 0.75 and soft_declines >= 2:
            return "non_recoverable"
        return "insufficient_funds"
    # unknown_error — fall back to transient unless risk is very high
    if risk > 0.80:
        return "non_recoverable"
    return "transient"


def _ambiguous_confidence(code: str, observed: dict) -> float:
    risk = float(observed.get("risk_score_gateway") or 0.0)
    soft = int(observed.get("prior_soft_declines_on_instrument_30d") or 0)
    if code == "GATEWAY_ERROR":
        return 0.72  # source=gateway is usually transient
    if code == "do_not_honour":
        # Strong signal if risk+soft agree
        return 0.68 if (risk > 0.75 or soft >= 3) else 0.55
    # unknown_error — weakest signal
    return 0.50 if risk > 0.80 else 0.45


def _llm_classify_stub(observed: dict) -> tuple[str, str]:
    """
    Stub for the LLM ambiguity-classification call (SPEC P7a).
    In production this would call the LLM with failure_message + context.
    Returns (inferred_class, reasoning).
    Deterministic fallback: parse failure_message for keywords.
    """
    msg = (observed.get("failure_message") or "").lower()
    if "funds" in msg or "balance" in msg:
        cls = "insufficient_funds"
        reason = "failure_message mentions funds/balance → insufficient_funds"
    elif "timeout" in msg or "unavailable" in msg or "try again" in msg:
        cls = "transient"
        reason = "failure_message suggests transient availability issue"
    elif "auth" in msg or "3ds" in msg or "otp" in msg:
        cls = "auth_required"
        reason = "failure_message mentions authentication flow"
    elif "expired" in msg or "update" in msg:
        cls = "expired_card"
        reason = "failure_message mentions expiry/update"
    else:
        cls = "transient"
        reason = "no strong signal in failure_message; defaulting to transient"
    return cls, f"[LLM-stub] {reason}"
