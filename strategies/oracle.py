"""Oracle [CEILING] — true multi-step EU-argmax with perfect GT knowledge (SPEC §5).

Phase 4 amendment (Option 3): at each attempt Oracle recomputes EU using the
actual attempt_k, contacts, and sim_hour rather than replaying the static
gt.optimal_action field.  This makes it a genuine multi-step ceiling instead
of a repeated snapshot of the attempt-0 argmax.

Compliance constraint (Phase 3): stolen_or_lost_card / risk_blocked → escalate
regardless of EU, matching the constraint every other strategy operates under.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML required") from exc

from strategies.common import ACTIONS, ACTION_DELAY_H, MANDATORY_ESCALATION_CODES, params_for

# Alias kept for any external imports that reference this directly.
COMPLIANCE_ESCALATE_CODES = MANDATORY_ESCALATION_CODES

ROOT = Path(__file__).resolve().parents[1]

ZERO_FRICTION = frozenset({
    "stop", "retry_1h", "retry_6h", "retry_24h", "retry_72h", "retry_7d",
    "retry_alternate_route", "hold_for_incident",
})

_SIM_CFG: dict | None = None


def _load_sim_cfg() -> dict:
    global _SIM_CFG
    if _SIM_CFG is None:
        with (ROOT / "sim_config.yaml").open(encoding="utf-8") as f:
            _SIM_CFG = yaml.safe_load(f)
    return _SIM_CFG


def _incident_rate(inc: dict, t_exec: float) -> float:
    """Interpolate success-rate multiplier from trajectory at sim time t_exec."""
    start  = float(inc["start_sim_hour"])
    window = float(inc["window_h"])
    t = t_exec - start
    if t < 0 or t >= window:
        return 1.0
    traj = inc["trajectory"]
    for i, pt in enumerate(traj):
        nxt = traj[i + 1]["offset_h"] if i + 1 < len(traj) else window
        if float(pt["offset_h"]) <= t < nxt:
            return float(pt["success_rate"])
    return float(traj[-1]["success_rate"])


def _hold_delay_h(incident_id: Optional[str], incidents: dict, sim_hour: float) -> float:
    if incident_id is None:
        return 6.0
    inc = incidents[incident_id]
    remaining = float(inc["start_sim_hour"]) + float(inc["window_h"]) - sim_hour
    return max(0.5, remaining)


def _p_eff_oracle(
    action: str,
    gt: dict,
    *,
    sim_hour: float,
    attempt_k: int,
    contacts: int,
    incidents: dict,
) -> float:
    """Exact p_eff replication of sim/generate.py using GT base_p and profile."""
    if action == "stop":
        return 0.0
    base_p  = float(gt["action_success_probabilities"].get(action, 0.0))
    profile = gt.get("action_time_profile", {}).get(action, {})
    fatigue = float(gt.get("attempt_fatigue_factor", 0.87))
    inc_id  = gt.get("incident_id")

    delay_h  = ACTION_DELAY_H.get(action)
    if delay_h is None:
        delay_h = _hold_delay_h(inc_id, incidents, sim_hour)

    opt_h = float(profile.get("optimal_delay_h", delay_h))
    lam   = float(profile.get("decay_lambda", 0.08))
    td    = math.exp(-lam * abs(delay_h - opt_h) / 24.0)

    t_exec = sim_hour + float(delay_h)
    if inc_id is None:
        inc_m = 1.0
    else:
        inc = incidents[inc_id]
        inc_m = _incident_rate(inc, t_exec)
        end = float(inc["start_sim_hour"]) + float(inc["window_h"])
        if inc_id == "INC-3" and t_exec >= end - 1e-9:
            inc_m = float(inc["trajectory"][-1]["success_rate"])

    fat = fatigue ** attempt_k
    vis = 1.0 if action in ZERO_FRICTION else (0.90 ** contacts)
    return max(0.0, min(0.98, base_p * td * inc_m * fat * vis))


def _eu_oracle(
    action: str,
    gt: dict,
    observed: dict,
    *,
    sim_hour: float,
    attempt_k: int,
    contacts: int,
    incidents: dict,
    oracle_cfg: dict,
) -> float:
    """Full EU with attempt-aware p_eff — the true multi-step ceiling."""
    if action == "stop":
        return 0.0
    p       = _p_eff_oracle(action, gt, sim_hour=sim_hour,
                            attempt_k=attempt_k, contacts=contacts, incidents=incidents)
    amount  = float(observed.get("amount_inr") or 0.0)
    ltv     = float(observed.get("lifetime_value_inr") or 0.0)
    eng     = float(observed.get("email_engagement_score") or 0.0)
    rho     = float(oracle_cfg.get("rho_daily", 0.002))

    inc_id  = gt.get("incident_id")
    delay_h = ACTION_DELAY_H.get(action)
    if delay_h is None:
        delay_h = _hold_delay_h(inc_id, {}, sim_hour)  # incidents not needed for delay calc
    days    = float(delay_h) / 24.0
    revenue = amount * ((1.0 - rho) ** days)

    # Costs mirror sim/generate.py
    churn   = float(oracle_cfg["churn_increment"].get(action, 0.0))
    c_f     = churn * ltv * max(0.0, 1.2 - eng)

    if action == "escalate_to_merchant":
        c_r = float(oracle_cfg.get("risk_escalate_inr", 5.0))
    elif action in ZERO_FRICTION:
        c_r = float(oracle_cfg.get("risk_silent_inr", 2.0))
    else:
        c_r = float(oracle_cfg.get("risk_visible_inr", 8.0))

    c_i_map = {
        "retry_1h":                 oracle_cfg.get("gateway_retry_fee_inr", 0.5),
        "retry_6h":                 oracle_cfg.get("gateway_retry_fee_inr", 0.5),
        "retry_24h":                oracle_cfg.get("gateway_retry_fee_inr", 0.5),
        "retry_72h":                oracle_cfg.get("gateway_retry_fee_inr", 0.5),
        "retry_7d":                 oracle_cfg.get("gateway_retry_fee_inr", 0.5),
        "retry_alternate_route":    oracle_cfg.get("alternate_route_fee_inr", 0.8),
        "hold_for_incident":        oracle_cfg.get("hold_fee_inr", 0.2),
        "send_dunning_notification":oracle_cfg.get("dunning_unit_cost_inr", 0.35),
        "send_recovery_link":       oracle_cfg.get("link_unit_cost_inr", 1.2),
        "request_reauth":           oracle_cfg.get("link_unit_cost_inr", 1.2),
        "request_new_payment_method": oracle_cfg.get("link_unit_cost_inr", 1.2),
        "escalate_to_merchant":     oracle_cfg.get("escalate_ops_cost_inr", 85.0),
    }
    c_i = float(c_i_map.get(action, 0.0))

    return p * revenue - c_f - c_r - c_i


class Oracle:
    """
    Multi-step Oracle: recomputes EU-argmax at every attempt using actual
    attempt_k, contacts, and sim_hour.  Reads GT base_p / profile directly.
    Subject to same compliance constraints as all other strategies.
    """
    name = "oracle"

    def __init__(self, ground_truth_rows: list[dict]):
        self._by_id = {row["episode_id"]: row for row in ground_truth_rows}
        cfg = _load_sim_cfg()
        self._oracle_cfg = cfg["oracle"]
        self._incidents  = cfg["incidents"]

    def decide(self, observed: dict, episode_state: dict) -> tuple[str, dict]:
        code = observed.get("failure_code") or ""
        # Compliance override — same as before
        if code in COMPLIANCE_ESCALATE_CODES:
            return "escalate_to_merchant", params_for("escalate_to_merchant", observed)

        gt       = self._by_id[observed["episode_id"]]
        sim_hour = float(observed.get("sim_hour") or 0.0)
        attempt_k = int(episode_state.get("attempt_index") or 0)
        contacts  = int(episode_state.get("customer_contacts_sent") or 0)

        best_eu   = -1e18
        best_act  = "stop"
        for action in ACTIONS:
            eu = _eu_oracle(
                action, gt, observed,
                sim_hour=sim_hour,
                attempt_k=attempt_k,
                contacts=contacts,
                incidents=self._incidents,
                oracle_cfg=self._oracle_cfg,
            )
            if eu > best_eu:
                best_eu  = eu
                best_act = action

        # If best EU ≤ 0, stop.
        if best_eu <= 0:
            best_act = "stop"

        return best_act, params_for(best_act, observed)
