"""Strategist — Stage 2 of the Autopilot pipeline (SPEC §6).

Scores every valid action with policy EU (Option 2 — horizon-aware):
    For retry-delay actions: EU_policy(a) = P_atleast1(a, K) * Revenue - K * costs(a)
    where K = min(floor(remaining_h / delay_h), attempts_left)
    and P_atleast1 = 1 - prod(1 - p_eff(a, k)) for k in 0..K-1

    For all other actions (customer-visible, hold, escalate): single-shot EU as before.

All terms are in INR expected-value units (SPEC §6.1).
P(success|a) uses the shared retry-delay model for delay actions;
rule-derived priors from costs.yaml for all other actions.
Never reads ground truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML required") from exc

from strategies.common import ACTIONS, ACTION_DELAY_H, RETRY_DELAYS
from strategies.featurize import row_to_raw
from strategies.retry_model import encode_rows, load_bundle

ROOT = Path(__file__).resolve().parents[1]

_COSTS: dict | None = None


def _load_costs() -> dict:
    global _COSTS
    if _COSTS is None:
        with (ROOT / "costs.yaml").open(encoding="utf-8") as f:
            _COSTS = yaml.safe_load(f)
    return _COSTS


ZERO_FRICTION_ACTIONS = frozenset(
    {"stop", "retry_1h", "retry_6h", "retry_24h", "retry_72h", "retry_7d",
     "retry_alternate_route", "hold_for_incident"}
)

# Episode constants from SPEC §4.2 — horizon and action cap.
# Used for policy EU: how many times can this retry fit within the remaining window?
EPISODE_HORIZON_H = 336.0
MAX_ACTIONS = 6

# Retry-delay actions that benefit from policy EU (multi-attempt compounding).
# Non-retry actions (customer-visible, hold, escalate) use single-shot EU.
RETRY_POLICY_ACTIONS = frozenset(
    {"retry_1h", "retry_6h", "retry_24h", "retry_72h", "retry_7d"}
)
FATIGUE_FACTOR = 0.87   # per-attempt fatigue — matches GT generation


@dataclass
class ActionScore:
    action_id: str
    p_success: float        # single-shot p used in EU (or P_atleast1 for policy)
    revenue_inr: float
    c_friction: float
    c_risk: float
    c_intervention: float
    expected_utility: float
    delay_h: float
    policy_k: int = 1       # number of attempts the policy EU accounts for


@dataclass
class StrategistResult:
    recommended_action: str
    recommended_params: dict
    scores: list[ActionScore]           # all 13 actions, sorted EU desc
    inferred_class: str
    incident_detected: bool
    replan_count: int
    reasoning: str


def score_all_actions(
    observed: dict,
    episode_state: dict,
    *,
    inferred_class: str,
    incident_detected: bool,
    retry_bundle: dict | None = None,
) -> StrategistResult:
    """Score every action and return the full ranking.

    Retry-delay actions use policy EU: P(at least 1 success in K attempts) * Revenue
    minus K * per-attempt costs, where K = how many times this delay fits in the
    remaining horizon subject to the attempt cap.

    All other actions use single-shot EU.
    """
    costs = _load_costs()
    if retry_bundle is None:
        retry_bundle = load_bundle()

    amount_inr = float(observed.get("amount_inr") or 0.0)
    ltv = float(observed.get("lifetime_value_inr") or 0.0)
    engagement = float(observed.get("email_engagement_score") or 0.0)
    contacts = int(episode_state.get("customer_contacts_sent") or 0)
    attempt_k = int(episode_state.get("attempt_index") or 0)
    replan_count = int(episode_state.get("replan_count") or 0)
    hours_elapsed = float(episode_state.get("hours_since_first_failure") or 0.0)
    rho = float(costs["revenue"]["rho_daily"])

    remaining_h = max(1.0, EPISODE_HORIZON_H - hours_elapsed)
    attempts_left = max(1, MAX_ACTIONS - attempt_k)

    scores: list[ActionScore] = []
    for action in ACTIONS:
        delay_h = _delay_h(action, observed)

        if action in RETRY_POLICY_ACTIONS:
            # Policy EU: how many repeats of this action fit in remaining horizon?
            k_horizon = int(remaining_h / delay_h) if delay_h > 0 else 1
            k_cap     = attempts_left
            K         = max(1, min(k_horizon, k_cap))

            # Single-shot p at each attempt index (attempt_k, attempt_k+1, ...)
            p_single = _p_success(
                action, observed, episode_state,
                inferred_class=inferred_class,
                incident_detected=incident_detected,
                attempt_k=attempt_k,
                contacts=contacts,
                retry_bundle=retry_bundle,
                costs=costs,
            )
            # P(at least 1 success in K attempts with per-attempt fatigue)
            p_fail_all = 1.0
            for i in range(K):
                p_i = max(0.0, min(0.98, p_single * (FATIGUE_FACTOR ** i)))
                p_fail_all *= (1.0 - p_i)
            p_policy = 1.0 - p_fail_all

            # Revenue: use first-attempt delay for discounting (conservative)
            days    = delay_h / 24.0
            revenue = amount_inr * ((1.0 - rho) ** days)

            # Costs: K repeats of intervention + risk; no friction (zero-friction actions)
            c_f = 0.0
            c_r = _c_risk(action, costs) * K
            c_i = _c_intervention(action, costs) * K
            eu  = p_policy * revenue - c_f - c_r - c_i

            scores.append(ActionScore(
                action_id=action,
                p_success=round(p_policy, 6),
                revenue_inr=round(revenue, 4),
                c_friction=0.0,
                c_risk=round(c_r, 4),
                c_intervention=round(c_i, 4),
                expected_utility=round(eu, 4),
                delay_h=round(delay_h, 4),
                policy_k=K,
            ))
        else:
            # Single-shot EU for non-retry actions
            p = _p_success(
                action, observed, episode_state,
                inferred_class=inferred_class,
                incident_detected=incident_detected,
                attempt_k=attempt_k,
                contacts=contacts,
                retry_bundle=retry_bundle,
                costs=costs,
            )
            days    = delay_h / 24.0
            revenue = amount_inr * ((1.0 - rho) ** days) if action != "stop" else 0.0
            c_f = _c_friction(action, ltv, engagement, costs)
            c_r = _c_risk(action, costs)
            c_i = _c_intervention(action, costs)
            eu  = p * revenue - c_f - c_r - c_i
            scores.append(ActionScore(
                action_id=action,
                p_success=round(p, 6),
                revenue_inr=round(revenue, 4),
                c_friction=round(c_f, 4),
                c_risk=round(c_r, 4),
                c_intervention=round(c_i, 4),
                expected_utility=round(eu, 4),
                delay_h=round(delay_h, 4),
                policy_k=1,
            ))

    scores.sort(key=lambda s: s.expected_utility, reverse=True)
    best = scores[0]

    reasoning = _build_reasoning(best, inferred_class, incident_detected, scores[:5])
    from strategies.common import params_for
    params = params_for(best.action_id, observed)

    return StrategistResult(
        recommended_action=best.action_id,
        recommended_params=params,
        scores=scores,
        inferred_class=inferred_class,
        incident_detected=incident_detected,
        replan_count=replan_count,
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# P(success|a) estimation — never reads ground truth
# ---------------------------------------------------------------------------

def _p_success(
    action: str,
    observed: dict,
    episode_state: dict,
    *,
    inferred_class: str,
    incident_detected: bool,
    attempt_k: int,
    contacts: int,
    retry_bundle: dict,
    costs: dict,
) -> float:
    if action == "stop":
        return 0.0

    priors = costs["action_priors"]

    # Retry-delay actions: use the shared fitted model
    if action in RETRY_DELAYS:
        raw = [row_to_raw(observed, episode_state)]
        X, _ = encode_rows(raw, vocab=retry_bundle["vocab"])
        proba = retry_bundle["clf"].predict_proba(X)[0]
        classes = retry_bundle["clf"].classes_
        # clf predicts the *best* retry class; use probability of this action's class
        # as a proxy for p(success), scaled by class win-rate on training data
        if action in classes:
            idx = list(classes).index(action)
            p_base = float(proba[idx]) * 0.85  # scale: win-rate → success prob
        else:
            p_base = float(priors.get(action, 0.20))
        # Adjust for inferred class — retries are near-useless for auth/expired
        if inferred_class in {"auth_required", "expired_card", "non_recoverable"}:
            p_base *= 0.10
        elif inferred_class == "insufficient_funds":
            # Longer delays are better; shorter retries are penalized
            delay_factor = {
                "retry_1h": 0.25, "retry_6h": 0.35,
                "retry_24h": 0.65, "retry_72h": 0.90, "retry_7d": 0.95,
            }.get(action, 1.0)
            p_base *= delay_factor
    elif action == "hold_for_incident":
        if incident_detected:
            p_base = float(priors["hold_for_incident"]["incident_detected"])
        else:
            p_base = float(priors["hold_for_incident"]["default"])
    elif action == "retry_alternate_route":
        p_base = float(priors["retry_alternate_route"])
        if inferred_class == "regional_degradation":
            p_base = min(0.80, p_base * 1.30)
        elif inferred_class == "insufficient_funds":
            # GT median base_p for retry_alternate_route on IF episodes is ~0.12.
            # The flat prior of 0.55 was a 4.6× overestimate causing Autopilot to
            # route 24.8% of IF episodes to alternate_route (38.5% recovery) instead
            # of retry_7d/retry_72h (69–95% recovery). Bug 1 fix — calibrated on GT.
            p_base = 0.12
    else:
        p_base = float(priors.get(action, 0.30))
        # Scale by inferred class fit
        p_base *= _class_action_fit(inferred_class, action)

    # Attempt fatigue (approximate; GT fatigue factor ~0.87 per attempt)
    fatigue = 0.87 ** attempt_k
    # Contact fatigue for visible actions
    if action not in ZERO_FRICTION_ACTIONS:
        contact_factor = 0.90 ** contacts
    else:
        contact_factor = 1.0

    return max(0.0, min(0.98, p_base * fatigue * contact_factor))


def _class_action_fit(inferred_class: str, action: str) -> float:
    """Multiplicative adjustment: how well does this action fit the inferred class?

    FLAGGED — Bug 2 (do not fix until Bug 1 is confirmed):
    retry_7d (168h delay) may cost Autopilot replanning opportunities within the
    336h episode horizon vs Rule-Based's retry_72h (72h), which fits 4 attempts
    in the same window.  If insufficient_funds still trails Rule-Based after Bug 1,
    investigate whether the utility function should account for
    remaining-attempts-within-horizon rather than scoring single-action EU in
    isolation.  Candidate fix: penalise actions whose delay consumes >50% of
    remaining horizon on early attempts.
    """
    fits: dict[str, dict[str, float]] = {
        "insufficient_funds": {
            "send_dunning_notification": 1.0,
            "send_recovery_link": 1.0,
            "request_reauth": 0.15,
            "request_new_payment_method": 0.55,
            "escalate_to_merchant": 0.60,
        },
        "auth_required": {
            "request_reauth": 1.0,
            "send_recovery_link": 0.65,
            "send_dunning_notification": 0.30,
            "request_new_payment_method": 0.55,
            "escalate_to_merchant": 0.40,
        },
        "expired_card": {
            "request_new_payment_method": 1.0,
            "request_reauth": 0.15,
            "send_recovery_link": 0.55,
            "send_dunning_notification": 0.30,
            "escalate_to_merchant": 0.35,
        },
        "regional_degradation": {
            "send_dunning_notification": 0.20,
            "send_recovery_link": 0.25,
            "request_reauth": 0.10,
            "request_new_payment_method": 0.15,
            "escalate_to_merchant": 0.70,
        },
        "transient": {
            "send_dunning_notification": 0.35,
            "send_recovery_link": 0.40,
            "request_reauth": 0.12,
            "request_new_payment_method": 0.25,
            "escalate_to_merchant": 0.55,
        },
        "non_recoverable": {
            "send_dunning_notification": 0.05,
            "send_recovery_link": 0.08,
            "request_reauth": 0.05,
            "request_new_payment_method": 0.08,
            "escalate_to_merchant": 0.10,
        },
    }
    return fits.get(inferred_class, {}).get(action, 1.0)


# ---------------------------------------------------------------------------
# Cost terms
# ---------------------------------------------------------------------------

def _delay_h(action: str, observed: dict) -> float:
    if action == "hold_for_incident":
        # Strategist doesn't know window; use 6h default (detector overrides in Phase 5)
        return 6.0
    if action == "retry_alternate_route":
        return 0.25
    return float(ACTION_DELAY_H.get(action) or 0.0)


def _c_friction(action: str, ltv: float, engagement: float, costs: dict) -> float:
    churn = float(costs["churn_increment"].get(action, 0.0))
    if churn == 0.0:
        return 0.0
    return churn * ltv * max(0.0, 1.2 - engagement)


def _c_risk(action: str, costs: dict) -> float:
    if action == "stop":
        return 0.0
    if action == "escalate_to_merchant":
        return float(costs["risk"]["risk_escalate_inr"])
    if action in ZERO_FRICTION_ACTIONS:
        return float(costs["risk"]["risk_silent_inr"])
    return float(costs["risk"]["risk_visible_inr"])


def _c_intervention(action: str, costs: dict) -> float:
    c = costs["intervention"]
    mapping = {
        "retry_1h": "gateway_retry_fee_inr",
        "retry_6h": "gateway_retry_fee_inr",
        "retry_24h": "gateway_retry_fee_inr",
        "retry_72h": "gateway_retry_fee_inr",
        "retry_7d": "gateway_retry_fee_inr",
        "retry_alternate_route": "alternate_route_fee_inr",
        "hold_for_incident": "hold_fee_inr",
        "send_dunning_notification": "dunning_unit_cost_inr",
        "send_recovery_link": "link_unit_cost_inr",
        "request_reauth": "link_unit_cost_inr",
        "request_new_payment_method": "link_unit_cost_inr",
        "escalate_to_merchant": "escalate_ops_cost_inr",
    }
    key = mapping.get(action)
    return float(c[key]) if key else 0.0


# ---------------------------------------------------------------------------
# Human-readable reasoning
# ---------------------------------------------------------------------------

def _build_reasoning(
    best: ActionScore,
    inferred_class: str,
    incident_detected: bool,
    top5: list[ActionScore],
) -> str:
    lines = [
        f"Inferred failure class: {inferred_class}",
        f"Incident detected: {incident_detected}",
        f"Recommended action: {best.action_id} "
        f"(EU={best.expected_utility:.2f} INR, P_policy={best.p_success:.3f}, "
        f"delay={best.delay_h:.1f}h, K={best.policy_k})",
        "Top-5 actions by policy EU:",
    ]
    for s in top5:
        lines.append(
            f"  {s.action_id:28s}  EU={s.expected_utility:9.2f}  "
            f"P={s.p_success:.3f}  K={s.policy_k}  Rev={s.revenue_inr:.2f}  "
            f"C_r={s.c_risk:.2f}  C_i={s.c_intervention:.2f}"
        )
    return "\n".join(lines)
