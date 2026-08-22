"""Action Agent — Stage 4 of the Autopilot pipeline (SPEC §5).

Executes the policy-approved action against the mock tool layer.
Outcome (success/failure) is drawn from ground_truth.action_success_probabilities
multiplied by the p_eff modifiers — this is the ONLY place randomness is used.
The deciding logic (Investigator + Strategist) never sees ground truth.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional


@dataclass
class ActionResult:
    episode_id: str
    action_id: str
    params: dict
    success: bool
    p_eff: float        # effective probability used to draw the outcome
    tool_name: str      # which mock tool was called
    tool_response: dict


# ---------------------------------------------------------------------------
# Mock tool layer (Phase 3 stubs — real API calls not in scope yet)
# ---------------------------------------------------------------------------

def _mock_retry_api(action_id: str, params: dict, episode_id: str) -> dict:
    return {"tool": "MockRetryAPI", "action": action_id, "params": params,
            "status": "queued", "episode_id": episode_id}


def _mock_notification_api(action_id: str, params: dict, episode_id: str) -> dict:
    return {"tool": "MockNotificationAPI", "action": action_id, "params": params,
            "status": "sent", "episode_id": episode_id}


def _mock_recovery_link_api(action_id: str, params: dict, episode_id: str) -> dict:
    return {"tool": "MockRecoveryLinkAPI", "action": action_id, "params": params,
            "status": "link_generated", "episode_id": episode_id}


def _mock_ops_queue(action_id: str, params: dict, episode_id: str) -> dict:
    return {"tool": "MockOpsQueue", "action": action_id, "params": params,
            "status": "ticket_created", "episode_id": episode_id}


TOOL_MAP = {
    "stop": (lambda a, p, e: {"tool": "none", "status": "stopped"}, "none"),
    "retry_1h": (_mock_retry_api, "MockRetryAPI"),
    "retry_6h": (_mock_retry_api, "MockRetryAPI"),
    "retry_24h": (_mock_retry_api, "MockRetryAPI"),
    "retry_72h": (_mock_retry_api, "MockRetryAPI"),
    "retry_7d": (_mock_retry_api, "MockRetryAPI"),
    "retry_alternate_route": (_mock_retry_api, "MockRetryAPI"),
    "hold_for_incident": (_mock_retry_api, "MockRetryAPI"),
    "send_dunning_notification": (_mock_notification_api, "MockNotificationAPI"),
    "send_recovery_link": (_mock_recovery_link_api, "MockRecoveryLinkAPI"),
    "request_reauth": (_mock_recovery_link_api, "MockRecoveryLinkAPI"),
    "request_new_payment_method": (_mock_notification_api, "MockNotificationAPI"),
    "escalate_to_merchant": (_mock_ops_queue, "MockOpsQueue"),
}


# ---------------------------------------------------------------------------
# Effective probability computation (mirrors SPEC §3)
# Only called here; the deciding pipeline never touches it.
# ---------------------------------------------------------------------------

def _compute_p_eff(
    action_id: str,
    ground_truth: dict,
    sim_hour: float,
    attempt_k: int,
    contacts: int,
) -> float:
    if action_id == "stop":
        return 0.0

    base_p = float(ground_truth["action_success_probabilities"].get(action_id, 0.0))
    profile = ground_truth.get("action_time_profile", {}).get(action_id, {})
    fatigue = float(ground_truth.get("attempt_fatigue_factor", 0.87))

    # Time decay
    delay_h = float(profile.get("action_delay_h", 1.0))
    optimal_h = float(profile.get("optimal_delay_h", 1.0))
    lam = float(profile.get("decay_lambda", 0.08))
    td = math.exp(-lam * abs(delay_h - optimal_h) / 24.0)

    # Incident multiplier — use stored incident_multiplier if available
    # (this is the ONLY field from GT used here; it's used for outcome sampling only)
    inc_m = float(ground_truth.get("incident_multiplier", 1.0))

    # Attempt fatigue
    fat = fatigue ** attempt_k

    # Contact fatigue (customer-visible actions only)
    zero_friction = {"stop", "retry_1h", "retry_6h", "retry_24h", "retry_72h",
                     "retry_7d", "retry_alternate_route", "hold_for_incident"}
    vis = 1.0 if action_id in zero_friction else (0.90 ** contacts)

    raw = base_p * td * inc_m * fat * vis
    return max(0.0, min(0.98, raw))


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

def execute(
    action_id: str,
    params: dict,
    observed: dict,
    episode_state: dict,
    ground_truth: dict,
    *,
    rng: Optional[random.Random] = None,
) -> ActionResult:
    """Execute action against mock tool and sample outcome from ground truth."""
    if rng is None:
        rng = random.Random()

    eid = observed["episode_id"]
    sim_hour = float(observed.get("sim_hour") or 0.0)
    attempt_k = int(episode_state.get("attempt_index") or 0)
    contacts = int(episode_state.get("customer_contacts_sent") or 0)

    p = _compute_p_eff(action_id, ground_truth, sim_hour, attempt_k, contacts)
    success = (rng.random() < p) if action_id != "stop" else False

    fn, tool_name = TOOL_MAP.get(action_id, (_mock_ops_queue, "MockOpsQueue"))
    if action_id == "stop":
        resp = {"tool": "none", "status": "stopped"}
    else:
        resp = fn(action_id, params, eid)

    resp["outcome"] = "success" if success else "failure"
    resp["p_eff"] = round(p, 6)

    return ActionResult(
        episode_id=eid,
        action_id=action_id,
        params=params,
        success=success,
        p_eff=round(p, 6),
        tool_name=tool_name,
        tool_response=resp,
    )
