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
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="non_recoverable",
            observability="clear",
            confidence=0.98,
            flags=["hard_stop_code"],
        )

    # --- R2: explicit expiry signal ---
    if code == "card_expired" or expiry == "expired":
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="expired_card",
            observability="clear",
            confidence=0.95,
            flags=["expired_card_signal"],
        )

    # --- R3: auth signals ---
    if (
        code == "authentication_failed"
        or auth in {"attempted_failed", "mandate_auth_pending"}
        or (code == "mandate_revoked" and method in MANDATE_METHODS)
    ):
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="auth_required",
            observability="clear",
            confidence=0.92,
            flags=["auth_signal"],
        )

    # --- R4: mandate revoked but not a mandate method → non_recoverable ---
    if code == "mandate_revoked":
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="non_recoverable",
            observability="clear",
            confidence=0.85,
            flags=["mandate_revoked_non_mandate_method"],
        )

    # --- R5: clear funds signal ---
    if code == "insufficient_funds":
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="insufficient_funds",
            observability="clear",
            confidence=0.95,
            flags=["funds_signal"],
        )

    # --- R6: issuer_down → regional_degradation (investigated further by detector) ---
    if code == "issuer_down":
        flags.append("possible_degradation")
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="regional_degradation",
            observability="clear",
            confidence=0.82,
            flags=flags,
        )

    # --- R7: network_timeout → transient ---
    if code == "network_timeout":
        return InvestigatorResult(
            episode_id=eid,
            inferred_class="transient",
            observability="clear",
            confidence=0.80,
            flags=["network_timeout"],
        )

    # --- Ambiguous territory: do_not_honour, GATEWAY_ERROR, unknown_error ---
    # Apply supporting signals to narrow down before deciding whether to call LLM.
    inferred = _heuristic_ambiguous(code, observed)
    confidence = _ambiguous_confidence(code, observed)

    if confidence < 0.60 and llm_enabled:
        # LLM path — stub returns a structured result using failure_message.
        llm_class, llm_reason = _llm_classify_stub(observed)
        return InvestigatorResult(
            episode_id=eid,
            inferred_class=llm_class,
            observability="ambiguous",
            confidence=0.70,
            flags=["llm_path"] + flags,
            llm_used=True,
            llm_reasoning=llm_reason,
        )

    return InvestigatorResult(
        episode_id=eid,
        inferred_class=inferred,
        observability="ambiguous",
        confidence=confidence,
        flags=["ambiguous_code"] + flags,
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
