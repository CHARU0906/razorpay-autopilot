"""Smart-Dunning Baseline — learned retry timing + dunning + PM update + caps.

SPEC §5 #5. Uses the same fitted retry-delay model as Learned Smart-Retry.
Does not aggregate across episodes (no hold_for_incident / degradation detection).
"""

from __future__ import annotations

from strategies.common import RETRY_DELAYS, params_for, taken_action_ids
from strategies.retry_model import load_bundle, predict_retry_action

HARD_STOP_CODES = frozenset(
    {"stolen_or_lost_card", "risk_blocked", "payment_method_restricted"}
)
CUSTOMER_ACTIONS = frozenset(
    {
        "send_dunning_notification",
        "send_recovery_link",
        "request_reauth",
        "request_new_payment_method",
    }
)
RETRY_CAP = 4
CONTACT_CAP = 2


class SmartDunning:
    name = "smart_dunning"

    def __init__(self, bundle=None):
        self._bundle = bundle if bundle is not None else load_bundle()

    def decide(self, observed: dict, episode_state: dict) -> tuple[str, dict]:
        taken = taken_action_ids(episode_state)
        n_retry = sum(1 for a in taken if a in RETRY_DELAYS)
        n_contact = sum(1 for a in taken if a in CUSTOMER_ACTIONS)
        contacts = int(episode_state.get("customer_contacts_sent") or n_contact)

        code = observed.get("failure_code")
        auth = observed.get("auth_state")
        expiry = observed.get("card_expiry_state")

        if code in HARD_STOP_CODES:
            action = "stop"
        elif n_retry >= RETRY_CAP or contacts >= CONTACT_CAP:
            action = "stop"
        elif code == "card_expired" or expiry == "expired":
            action = (
                "stop"
                if "request_new_payment_method" in taken
                else "request_new_payment_method"
            )
        elif code == "authentication_failed" or auth in {
            "attempted_failed",
            "mandate_auth_pending",
        }:
            action = "stop" if "request_reauth" in taken else "request_reauth"
        elif code == "mandate_revoked":
            action = "stop"
        elif code == "insufficient_funds":
            if "send_dunning_notification" not in taken:
                action = "send_dunning_notification"
            else:
                action = predict_retry_action(observed, episode_state, self._bundle)
        elif code == "unknown_error":
            if "send_recovery_link" not in taken:
                action = "send_recovery_link"
            else:
                action = predict_retry_action(observed, episode_state, self._bundle)
        else:
            # transient / issuer_down / GATEWAY_ERROR / do_not_honour / network_timeout
            action = predict_retry_action(observed, episode_state, self._bundle)

        if action in RETRY_DELAYS and n_retry >= RETRY_CAP:
            action = "stop"
        return action, params_for(action, observed)
