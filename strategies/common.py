"""Shared strategy contract (SPEC §5)."""

from __future__ import annotations

from typing import Any, Protocol

ACTIONS = [
    "stop",
    "retry_1h",
    "retry_6h",
    "retry_24h",
    "retry_72h",
    "retry_7d",
    "retry_alternate_route",
    "hold_for_incident",
    "send_dunning_notification",
    "send_recovery_link",
    "request_reauth",
    "request_new_payment_method",
    "escalate_to_merchant",
]

RETRY_DELAYS = ["retry_1h", "retry_6h", "retry_24h", "retry_72h", "retry_7d"]
SILENT_RETRIES = RETRY_DELAYS + ["retry_alternate_route", "hold_for_incident"]

# Failure codes that mandate escalation regardless of EU optimisation.
# Used by Oracle (compliance constraint), Autopilot policy_engine, and the
# Phase 4 scorer (Option 2: exclude mandatory-fraud escalations from IRPI
# denominator; disclose as footnote per Option 1 with exact INR cost).
MANDATORY_ESCALATION_CODES = frozenset({"stolen_or_lost_card", "risk_blocked"})

ACTION_DELAY_H = {
    "stop": 0.0,
    "retry_1h": 1.0,
    "retry_6h": 6.0,
    "retry_24h": 24.0,
    "retry_72h": 72.0,
    "retry_7d": 168.0,
    "retry_alternate_route": 0.25,
    "hold_for_incident": 6.0,
    "send_dunning_notification": 4.0,
    "send_recovery_link": 8.0,
    "request_reauth": 6.0,
    "request_new_payment_method": 12.0,
    "escalate_to_merchant": 2.0,
}


class Strategy(Protocol):
    name: str

    def decide(self, observed: dict, episode_state: dict) -> tuple[str, dict]:
        ...


def episode_state_from_observed(observed: dict) -> dict:
    return {
        "attempt_index": observed.get("attempt_index", 0),
        "hours_since_first_failure": observed.get("hours_since_first_failure", 0.0),
        "actions_taken": list(observed.get("actions_taken") or []),
        "customer_contacts_sent": observed.get("customer_contacts_sent", 0),
        "last_action": observed.get("last_action"),
        "last_outcome": observed.get("last_outcome"),
        "replan_count": observed.get("replan_count", 0),
    }


def params_for(action_id: str, observed: dict | None = None) -> dict[str, Any]:
    if action_id not in ACTIONS:
        raise ValueError(f"illegal action_id {action_id!r}")
    if action_id == "stop":
        return {}
    if action_id in RETRY_DELAYS:
        return {"delay_h": ACTION_DELAY_H[action_id]}
    if action_id == "retry_alternate_route":
        current = (observed or {}).get("acquirer_route_id") or "route_a"
        alt = {"route_a": "route_c", "route_b": "route_a", "route_c": "route_b"}[current]
        return {"delay_h": 0.25, "route_id": alt}
    if action_id == "hold_for_incident":
        return {"until_h": 6.0}
    if action_id == "send_dunning_notification":
        return {"channel": "email", "template": "payment_failed_nudge"}
    if action_id == "send_recovery_link":
        return {"channel": "email", "expiry_h": 48.0}
    if action_id == "request_reauth":
        method = (observed or {}).get("payment_method")
        auth_type = "upi_mandate" if method in {"upi_autopay", "emandate_nach"} else "3ds"
        return {"channel": "email", "auth_type": auth_type}
    if action_id == "request_new_payment_method":
        return {"channel": "email", "deadline_h": 72.0}
    if action_id == "escalate_to_merchant":
        return {"queue": "recovery_ops", "note": "high_value_or_exhausted"}
    return {}


def taken_action_ids(episode_state: dict) -> list[str]:
    out = []
    for row in episode_state.get("actions_taken") or []:
        if isinstance(row, dict):
            out.append(row.get("action") or row.get("action_id"))
        else:
            out.append(row)
    return [a for a in out if a]
