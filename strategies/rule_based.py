"""Rule-Based Recovery — explicit if/else on observed failure_code and auth_state.

Rules (first matching wins). These are the Phase 2 rules, not a learned policy.

R1  Hard-decline codes → stop. Never silent-retry.
    stolen_or_lost_card, risk_blocked, payment_method_restricted
R2  card_expired OR card_expiry_state == expired → request_new_payment_method
R3  authentication_failed OR auth_state in {attempted_failed, mandate_auth_pending}
    OR (mandate_revoked on a mandate instrument) → request_reauth
R4  mandate_revoked otherwise → stop
R5  insufficient_funds → retry_72h
R6  issuer_down → retry_alternate_route (treat as possible route/issuer outage)
R7  network_timeout, GATEWAY_ERROR → retry_6h
R8  do_not_honour → retry_24h (often NSF-like, sometimes hard)
R9  unknown_error or anything else → send_recovery_link
"""

from __future__ import annotations

from strategies.common import params_for, taken_action_ids

HARD_STOP_CODES = frozenset(
    {
        "stolen_or_lost_card",
        "risk_blocked",
        "payment_method_restricted",
    }
)
MANDATE_METHODS = frozenset({"upi_autopay", "emandate_nach"})


class RuleBased:
    name = "rule_based"

    def decide(self, observed: dict, episode_state: dict) -> tuple[str, dict]:
        if int(episode_state.get("attempt_index") or 0) >= 5:
            return "stop", params_for("stop", observed)
        taken = taken_action_ids(episode_state)
        code = observed.get("failure_code")
        auth = observed.get("auth_state")
        expiry = observed.get("card_expiry_state")
        method = observed.get("payment_method")

        if code in HARD_STOP_CODES:
            action = "stop"
        elif code == "card_expired" or expiry == "expired":
            action = "request_new_payment_method"
        elif (
            code == "authentication_failed"
            or auth in {"attempted_failed", "mandate_auth_pending"}
            or (code == "mandate_revoked" and method in MANDATE_METHODS)
        ):
            action = "request_reauth"
        elif code == "mandate_revoked":
            action = "stop"
        elif code == "insufficient_funds":
            action = "retry_72h"
        elif code == "issuer_down":
            action = "retry_alternate_route"
        elif code in {"network_timeout", "GATEWAY_ERROR"}:
            action = "retry_6h"
        elif code == "do_not_honour":
            action = "retry_24h"
        else:
            action = "send_recovery_link"
        return action, params_for(action, observed)
