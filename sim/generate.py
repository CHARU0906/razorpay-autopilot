"""Phase 1 generator: observed episodes.jsonl + hidden ground_truth.jsonl.

Conforms to SPEC.md §2–§4, D2 (mix + manifest), D3 (gross/net columns), D4 (seed bands).
Does not implement strategies, tools, or the benchmark harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. pip install -r requirements.txt") from exc

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "sim_config.yaml"
DEFAULT_OUT = ROOT / "data"

# SPEC §1 — canonical action_id strings, in spec order.
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

ACTION_DELAY_H = {
    "stop": 0.0,
    "retry_1h": 1.0,
    "retry_6h": 6.0,
    "retry_24h": 24.0,
    "retry_72h": 72.0,
    "retry_7d": 168.0,
    "retry_alternate_route": 0.25,
    "hold_for_incident": None,  # derived from remaining incident window
    "send_dunning_notification": 4.0,
    "send_recovery_link": 8.0,
    "request_reauth": 6.0,
    "request_new_payment_method": 12.0,
    "escalate_to_merchant": 2.0,
}

ZERO_FRICTION = {
    "stop",
    "retry_1h",
    "retry_6h",
    "retry_24h",
    "retry_72h",
    "retry_7d",
    "retry_alternate_route",
    "hold_for_incident",
}

POPULATIONS = [
    "insufficient_funds",
    "transient",
    "non_recoverable",
    "auth_required",
    "expired_card",
    "regional_degradation",
    "ambiguous",
]

TRUE_CLASSES = [
    "transient",
    "insufficient_funds",
    "auth_required",
    "expired_card",
    "regional_degradation",
    "non_recoverable",
]

# Hidden fields that must never appear on episodes.jsonl.
GT_ONLY_FIELDS = {
    "population",
    "true_failure_class",
    "observability",
    "true_recoverability",
    "valid_actions",
    "action_success_probabilities",
    "action_time_profile",
    "attempt_fatigue_factor",
    "customer_friction_cost",
    "incident_id",
    "incident_degradation_curve",
    "incident_multiplier",
    "optimal_action",
    "optimal_delay_h",
    "optimal_action_revenue_only",
    "true_max_expected_revenue_inr",
    "true_max_expected_net_revenue_inr",
    "zero_friction_recovery_possible",
    "eventual_recovery_without_intervention",
    "root_cause_label",
    "net_revenue_inr",
}

MERCHANTS = [
    ("merch_01", "saas", "5734"),
    ("merch_02", "saas", "5734"),
    ("merch_03", "edtech", "8299"),
    ("merch_04", "edtech", "8299"),
    ("merch_05", "dtc_subscription", "5968"),
    ("merch_06", "dtc_subscription", "5968"),
    ("merch_07", "lending_emi", "6012"),
    ("merch_08", "lending_emi", "6012"),
    ("merch_09", "insurance", "6300"),
    ("merch_10", "insurance", "6300"),
    ("merch_11", "utility", "4900"),
    ("merch_12", "utility", "4900"),
]

VERTICAL_AMOUNT = {
    "saas": (499.0, 4999.0),
    "edtech": (299.0, 2499.0),
    "dtc_subscription": (199.0, 1999.0),
    "lending_emi": (1500.0, 25000.0),
    "insurance": (800.0, 12000.0),
    "utility": (150.0, 3500.0),
}

COUNTRY_CURRENCY = {"IN": "INR", "US": "USD", "AE": "AED", "SG": "SGD", "GB": "USD"}
IN_STATES = ["MH", "KA", "DL", "TN", "GJ", "TG", "WB", "RJ", "UP", "KL"]

FAILURE_MESSAGES = {
    "insufficient_funds": "Issuer declined: insufficient funds",
    "card_expired": "Card expired. Please update payment method",
    "authentication_failed": "Authentication failed or was not completed",
    "mandate_revoked": "UPI AutoPay / mandate is revoked",
    "issuer_down": "Issuer unavailable. Please try again later",
    "network_timeout": "Network timeout while contacting issuer",
    "do_not_honour": "Do not honour",
    "GATEWAY_ERROR": "GATEWAY_ERROR: upstream request failed",
    "payment_method_restricted": "Payment method restricted by issuer",
    "risk_blocked": "Transaction blocked by risk engine",
    "stolen_or_lost_card": "Card reported stolen or lost",
    "unknown_error": "Unknown error. Refusing to classify",
}


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def counts_from_mix(n: int, mix: dict[str, float]) -> dict[str, int]:
    """Largest-remainder allocation so shares sum exactly to n."""
    raw = {k: mix[k] * n for k in POPULATIONS}
    floors = {k: int(math.floor(v)) for k, v in raw.items()}
    leftover = n - sum(floors.values())
    order = sorted(POPULATIONS, key=lambda k: (raw[k] - floors[k], k), reverse=True)
    for k in order[:leftover]:
        floors[k] += 1
    if sum(floors.values()) != n:
        raise RuntimeError("population allocation does not sum to n")
    return floors


def assert_seed_bands(seed: int, cfg: dict) -> None:
    lo_e, hi_e = cfg["eval_seed_band"]
    lo_t, hi_t = cfg["train_seed_band"]
    if lo_t <= hi_e and lo_e <= hi_t:
        # Overlap of closed integer intervals.
        if max(lo_e, lo_t) <= min(hi_e, hi_t):
            raise RuntimeError("D4 violation: train and eval seed bands overlap")
    if lo_e <= seed <= hi_e:
        return
    if lo_t <= seed <= hi_t:
        return
    raise RuntimeError(
        f"seed {seed} is outside eval {cfg['eval_seed_band']} and train {cfg['train_seed_band']}"
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def round_f(x: float, nd: int = 6) -> float:
    return float(round(x, nd))


def incident_rate(inc: dict, sim_hour: float) -> float:
    start = float(inc["start_sim_hour"])
    window = float(inc["window_h"])
    t = sim_hour - start
    if t < 0 or t >= window:
        return 1.0
    traj = inc["trajectory"]
    for i, pt in enumerate(traj):
        nxt = traj[i + 1]["offset_h"] if i + 1 < len(traj) else window
        if pt["offset_h"] <= t < nxt:
            return float(pt["success_rate"])
    return float(traj[-1]["success_rate"])


def step_index(inc: dict, sim_hour: float) -> int:
    start = float(inc["start_sim_hour"])
    window = float(inc["window_h"])
    t = sim_hour - start
    traj = inc["trajectory"]
    for i, pt in enumerate(traj):
        nxt = traj[i + 1]["offset_h"] if i + 1 < len(traj) else window
        if pt["offset_h"] <= t < nxt:
            return i
    return len(traj) - 1


def curve_ref(incident_id: str, inc: dict) -> dict:
    return {
        "incident_id": incident_id,
        "window_h": inc["window_h"],
        "start_sim_hour": inc["start_sim_hour"],
        "cohort": inc["cohort"],
        "points": [
            {"offset_h": float(p["offset_h"]), "success_rate": float(p["success_rate"])}
            for p in inc["trajectory"]
        ],
        "right_answer": inc["right_answer"],
    }


def time_profile(
    true_class: str,
    incident_id: str | None,
    remaining_h: float,
    *,
    regime: str = "homogeneous",
    cust: dict | None = None,
    rec: dict | None = None,
    inst: dict | None = None,
    geo: dict | None = None,
) -> dict:
    class_peak = {
        "transient": 1.0,
        "insufficient_funds": 72.0,
        "auth_required": 6.0,
        "expired_card": 12.0,
        "regional_degradation": 0.25 if incident_id == "INC-2" else 1.0,
        "non_recoverable": 0.0,
    }[true_class]
    lam = {
        "transient": 0.35,
        "insufficient_funds": 0.18,
        "auth_required": 0.25,
        "expired_card": 0.20,
        "regional_degradation": 0.08,
        "non_recoverable": 0.40,
    }[true_class]

    # Regime B: heterogeneous optimal timing conditioned on customer context
    if regime in {"heterogeneous", "B", "regime_b"}:
        if true_class == "insufficient_funds":
            if rec and (rec.get("billing_cycle") == "monthly" or (cust and cust.get("avg_days_between_txns", 30.0) >= 20.0)):
                class_peak = 168.0  # Monthly salary cycle needs ~7d (168h) delay
            elif cust and float(cust.get("email_engagement_score", 0.0)) >= 0.75:
                class_peak = 4.0    # Responsive dunning link
            else:
                class_peak = 72.0   # Mid-cycle short funds blip
        elif true_class == "expired_card":
            if (cust and cust.get("has_alternate_instrument_on_file")) or (inst and inst.get("token_type") == "network_token"):
                class_peak = 0.25   # Immediate alternate route or token refresh
            elif cust and float(cust.get("email_engagement_score", 0.0)) >= 0.60:
                class_peak = 8.0    # Fast recovery link
            else:
                class_peak = 12.0   # Manual update prompt
        elif true_class == "transient":
            if geo and (geo.get("is_cross_border") or geo.get("acquirer_route_id") == "route_c"):
                class_peak = 0.25   # Alternate route
            else:
                class_peak = 1.0

    out = {}
    for a in ACTIONS:
        delay = ACTION_DELAY_H[a]
        if delay is None:
            delay = max(0.5, remaining_h)
        peak = class_peak
        if true_class == "regional_degradation" and a == "hold_for_incident":
            peak = max(0.5, remaining_h)
        elif true_class == "auth_required" and a == "request_reauth":
            peak = 6.0
        elif true_class == "expired_card" and a == "request_new_payment_method":
            peak = 12.0
        out[a] = {
            "optimal_delay_h": round_f(peak),
            "decay_lambda": lam,
            "action_delay_h": round_f(float(delay)),
        }
    return out


def time_decay(delay_h: float, optimal_delay_h: float, lam: float) -> float:
    return math.exp(-lam * abs(delay_h - optimal_delay_h) / 24.0)


def jitter_p(rng: random.Random, lo: float, hi: float) -> float:
    return max(0.0, min(0.98, rng.uniform(lo, hi)))


def base_success_probs(
    true_class: str,
    incident_id: str | None,
    rng: random.Random,
    *,
    regime: str = "homogeneous",
    cust: dict | None = None,
    rec: dict | None = None,
    inst: dict | None = None,
    geo: dict | None = None,
) -> dict[str, float]:
    p = {a: 0.0 for a in ACTIONS}
    if true_class == "transient":
        if regime in {"heterogeneous", "B", "regime_b"} and geo and (geo.get("is_cross_border") or geo.get("acquirer_route_id") == "route_c"):
            p.update(
                {
                    "retry_1h": jitter_p(rng, 0.35, 0.50),
                    "retry_6h": jitter_p(rng, 0.30, 0.45),
                    "retry_24h": jitter_p(rng, 0.20, 0.35),
                    "retry_72h": jitter_p(rng, 0.10, 0.20),
                    "retry_7d": jitter_p(rng, 0.05, 0.15),
                    "retry_alternate_route": jitter_p(rng, 0.72, 0.88),
                    "hold_for_incident": jitter_p(rng, 0.08, 0.18),
                    "send_dunning_notification": jitter_p(rng, 0.15, 0.28),
                    "send_recovery_link": jitter_p(rng, 0.20, 0.35),
                    "request_reauth": jitter_p(rng, 0.04, 0.10),
                    "request_new_payment_method": jitter_p(rng, 0.12, 0.24),
                    "escalate_to_merchant": jitter_p(rng, 0.25, 0.40),
                }
            )
        else:
            p.update(
                {
                    "retry_1h": jitter_p(rng, 0.58, 0.78),
                    "retry_6h": jitter_p(rng, 0.50, 0.70),
                    "retry_24h": jitter_p(rng, 0.28, 0.44),
                    "retry_72h": jitter_p(rng, 0.14, 0.28),
                    "retry_7d": jitter_p(rng, 0.08, 0.18),
                    "retry_alternate_route": jitter_p(rng, 0.42, 0.62),
                    "hold_for_incident": jitter_p(rng, 0.08, 0.18),
                    "send_dunning_notification": jitter_p(rng, 0.18, 0.32),
                    "send_recovery_link": jitter_p(rng, 0.22, 0.38),
                    "request_reauth": jitter_p(rng, 0.04, 0.10),
                    "request_new_payment_method": jitter_p(rng, 0.14, 0.26),
                    "escalate_to_merchant": jitter_p(rng, 0.25, 0.40),
                }
            )
    elif true_class == "insufficient_funds":
        if regime in {"heterogeneous", "B", "regime_b"}:
            if rec and (rec.get("billing_cycle") == "monthly" or (cust and cust.get("avg_days_between_txns", 30.0) >= 20.0)):
                # Monthly salary timing sub-cohort: 7d retry is dominant optimal
                p.update(
                    {
                        "retry_1h": jitter_p(rng, 0.04, 0.10),
                        "retry_6h": jitter_p(rng, 0.06, 0.12),
                        "retry_24h": jitter_p(rng, 0.12, 0.20),
                        "retry_72h": jitter_p(rng, 0.20, 0.32),
                        "retry_7d": jitter_p(rng, 0.72, 0.88),
                        "retry_alternate_route": jitter_p(rng, 0.06, 0.14),
                        "hold_for_incident": jitter_p(rng, 0.04, 0.10),
                        "send_dunning_notification": jitter_p(rng, 0.35, 0.50),
                        "send_recovery_link": jitter_p(rng, 0.40, 0.58),
                        "request_reauth": jitter_p(rng, 0.04, 0.10),
                        "request_new_payment_method": jitter_p(rng, 0.20, 0.36),
                        "escalate_to_merchant": jitter_p(rng, 0.15, 0.28),
                    }
                )
            elif cust and float(cust.get("email_engagement_score", 0.0)) >= 0.75:
                # High digital engagement: direct link/nudge optimal
                p.update(
                    {
                        "retry_1h": jitter_p(rng, 0.08, 0.16),
                        "retry_6h": jitter_p(rng, 0.14, 0.24),
                        "retry_24h": jitter_p(rng, 0.30, 0.45),
                        "retry_72h": jitter_p(rng, 0.45, 0.60),
                        "retry_7d": jitter_p(rng, 0.48, 0.64),
                        "retry_alternate_route": jitter_p(rng, 0.10, 0.20),
                        "hold_for_incident": jitter_p(rng, 0.06, 0.14),
                        "send_dunning_notification": jitter_p(rng, 0.58, 0.74),
                        "send_recovery_link": jitter_p(rng, 0.68, 0.84),
                        "request_reauth": jitter_p(rng, 0.04, 0.10),
                        "request_new_payment_method": jitter_p(rng, 0.30, 0.48),
                        "escalate_to_merchant": jitter_p(rng, 0.18, 0.32),
                    }
                )
            else:
                # Mid-cycle weekly timing: 72h retry optimal
                p.update(
                    {
                        "retry_1h": jitter_p(rng, 0.08, 0.16),
                        "retry_6h": jitter_p(rng, 0.14, 0.24),
                        "retry_24h": jitter_p(rng, 0.38, 0.54),
                        "retry_72h": jitter_p(rng, 0.65, 0.80),
                        "retry_7d": jitter_p(rng, 0.35, 0.48),
                        "retry_alternate_route": jitter_p(rng, 0.08, 0.16),
                        "hold_for_incident": jitter_p(rng, 0.06, 0.14),
                        "send_dunning_notification": jitter_p(rng, 0.38, 0.52),
                        "send_recovery_link": jitter_p(rng, 0.44, 0.60),
                        "request_reauth": jitter_p(rng, 0.04, 0.10),
                        "request_new_payment_method": jitter_p(rng, 0.28, 0.44),
                        "escalate_to_merchant": jitter_p(rng, 0.18, 0.32),
                    }
                )
        else:
            p.update(
                {
                    "retry_1h": jitter_p(rng, 0.08, 0.16),
                    "retry_6h": jitter_p(rng, 0.12, 0.22),
                    "retry_24h": jitter_p(rng, 0.34, 0.50),
                    "retry_72h": jitter_p(rng, 0.48, 0.64),
                    "retry_7d": jitter_p(rng, 0.52, 0.70),
                    "retry_alternate_route": jitter_p(rng, 0.08, 0.16),
                    "hold_for_incident": jitter_p(rng, 0.06, 0.14),
                    "send_dunning_notification": jitter_p(rng, 0.38, 0.54),
                    "send_recovery_link": jitter_p(rng, 0.44, 0.62),
                    "request_reauth": jitter_p(rng, 0.04, 0.10),
                    "request_new_payment_method": jitter_p(rng, 0.28, 0.46),
                    "escalate_to_merchant": jitter_p(rng, 0.18, 0.32),
                }
            )
    elif true_class == "auth_required":
        p.update(
            {
                "retry_1h": jitter_p(rng, 0.02, 0.08),
                "retry_6h": jitter_p(rng, 0.03, 0.10),
                "retry_24h": jitter_p(rng, 0.04, 0.12),
                "retry_72h": jitter_p(rng, 0.03, 0.10),
                "retry_7d": jitter_p(rng, 0.02, 0.08),
                "retry_alternate_route": jitter_p(rng, 0.04, 0.12),
                "hold_for_incident": jitter_p(rng, 0.03, 0.08),
                "send_dunning_notification": jitter_p(rng, 0.10, 0.22),
                "send_recovery_link": jitter_p(rng, 0.38, 0.55),
                "request_reauth": jitter_p(rng, 0.64, 0.84),
                "request_new_payment_method": jitter_p(rng, 0.30, 0.48),
                "escalate_to_merchant": jitter_p(rng, 0.12, 0.24),
            }
        )
    elif true_class == "expired_card":
        if regime in {"heterogeneous", "B", "regime_b"}:
            if (cust and cust.get("has_alternate_instrument_on_file")) or (inst and inst.get("token_type") == "network_token"):
                # Zero-friction alternate instrument / token refresh optimal
                p.update(
                    {
                        "retry_1h": jitter_p(rng, 0.02, 0.06),
                        "retry_6h": jitter_p(rng, 0.02, 0.06),
                        "retry_24h": jitter_p(rng, 0.02, 0.06),
                        "retry_72h": jitter_p(rng, 0.02, 0.06),
                        "retry_7d": jitter_p(rng, 0.02, 0.06),
                        "retry_alternate_route": jitter_p(rng, 0.82, 0.94),
                        "hold_for_incident": jitter_p(rng, 0.00, 0.04),
                        "send_dunning_notification": jitter_p(rng, 0.15, 0.28),
                        "send_recovery_link": jitter_p(rng, 0.45, 0.60),
                        "request_reauth": jitter_p(rng, 0.06, 0.16),
                        "request_new_payment_method": jitter_p(rng, 0.52, 0.72),
                        "escalate_to_merchant": jitter_p(rng, 0.10, 0.22),
                    }
                )
            elif cust and float(cust.get("email_engagement_score", 0.0)) >= 0.60:
                p.update(
                    {
                        "retry_1h": jitter_p(rng, 0.00, 0.04),
                        "retry_6h": jitter_p(rng, 0.00, 0.04),
                        "retry_24h": jitter_p(rng, 0.00, 0.05),
                        "retry_72h": jitter_p(rng, 0.00, 0.05),
                        "retry_7d": jitter_p(rng, 0.00, 0.06),
                        "retry_alternate_route": jitter_p(rng, 0.02, 0.08),
                        "hold_for_incident": jitter_p(rng, 0.00, 0.04),
                        "send_dunning_notification": jitter_p(rng, 0.20, 0.35),
                        "send_recovery_link": jitter_p(rng, 0.70, 0.86),
                        "request_reauth": jitter_p(rng, 0.04, 0.12),
                        "request_new_payment_method": jitter_p(rng, 0.58, 0.76),
                        "escalate_to_merchant": jitter_p(rng, 0.10, 0.22),
                    }
                )
            else:
                p.update(
                    {
                        "retry_1h": jitter_p(rng, 0.00, 0.04),
                        "retry_6h": jitter_p(rng, 0.00, 0.04),
                        "retry_24h": jitter_p(rng, 0.00, 0.05),
                        "retry_72h": jitter_p(rng, 0.00, 0.05),
                        "retry_7d": jitter_p(rng, 0.00, 0.06),
                        "retry_alternate_route": jitter_p(rng, 0.00, 0.05),
                        "hold_for_incident": jitter_p(rng, 0.00, 0.04),
                        "send_dunning_notification": jitter_p(rng, 0.12, 0.24),
                        "send_recovery_link": jitter_p(rng, 0.32, 0.50),
                        "request_reauth": jitter_p(rng, 0.04, 0.12),
                        "request_new_payment_method": jitter_p(rng, 0.65, 0.84),
                        "escalate_to_merchant": jitter_p(rng, 0.10, 0.22),
                    }
                )
        else:
            p.update(
                {
                    "retry_1h": jitter_p(rng, 0.00, 0.04),
                    "retry_6h": jitter_p(rng, 0.00, 0.04),
                    "retry_24h": jitter_p(rng, 0.00, 0.05),
                    "retry_72h": jitter_p(rng, 0.00, 0.05),
                    "retry_7d": jitter_p(rng, 0.00, 0.06),
                    "retry_alternate_route": jitter_p(rng, 0.00, 0.05),
                    "hold_for_incident": jitter_p(rng, 0.00, 0.04),
                    "send_dunning_notification": jitter_p(rng, 0.12, 0.24),
                    "send_recovery_link": jitter_p(rng, 0.32, 0.50),
                    "request_reauth": jitter_p(rng, 0.04, 0.12),
                    "request_new_payment_method": jitter_p(rng, 0.56, 0.80),
                    "escalate_to_merchant": jitter_p(rng, 0.10, 0.22),
                }
            )
    elif true_class == "regional_degradation":
        p.update(
            {
                "retry_1h": jitter_p(rng, 0.42, 0.58),
                "retry_6h": jitter_p(rng, 0.40, 0.56),
                "retry_24h": jitter_p(rng, 0.36, 0.52),
                "retry_72h": jitter_p(rng, 0.22, 0.36),
                "retry_7d": jitter_p(rng, 0.12, 0.22),
                "retry_alternate_route": jitter_p(rng, 0.50, 0.68),
                "hold_for_incident": jitter_p(rng, 0.74, 0.90),
                "send_dunning_notification": jitter_p(rng, 0.10, 0.20),
                "send_recovery_link": jitter_p(rng, 0.14, 0.26),
                "request_reauth": jitter_p(rng, 0.04, 0.10),
                "request_new_payment_method": jitter_p(rng, 0.10, 0.20),
                "escalate_to_merchant": jitter_p(rng, 0.20, 0.34),
            }
        )
        if incident_id == "INC-1":
            p["hold_for_incident"] = jitter_p(rng, 0.82, 0.92)
            p["retry_alternate_route"] = jitter_p(rng, 0.40, 0.55)
            # Tight same-route bases so the cluster's empirical rate tracks 94→82.
            p["retry_1h"] = jitter_p(rng, 0.495, 0.505)
            p["retry_6h"] = jitter_p(rng, 0.475, 0.485)
            p["retry_24h"] = jitter_p(rng, 0.445, 0.455)
        elif incident_id == "INC-2":
            p["retry_alternate_route"] = jitter_p(rng, 0.80, 0.92)
            p["hold_for_incident"] = jitter_p(rng, 0.48, 0.62)
        elif incident_id == "INC-3":
            p["hold_for_incident"] = jitter_p(rng, 0.78, 0.90)
            p["retry_alternate_route"] = jitter_p(rng, 0.28, 0.42)
    elif true_class == "non_recoverable":
        p.update(
            {
                "retry_1h": jitter_p(rng, 0.00, 0.02),
                "retry_6h": jitter_p(rng, 0.00, 0.02),
                "retry_24h": jitter_p(rng, 0.00, 0.02),
                "retry_72h": jitter_p(rng, 0.00, 0.02),
                "retry_7d": jitter_p(rng, 0.00, 0.02),
                "retry_alternate_route": jitter_p(rng, 0.00, 0.03),
                "hold_for_incident": jitter_p(rng, 0.00, 0.02),
                "send_dunning_notification": jitter_p(rng, 0.00, 0.03),
                "send_recovery_link": jitter_p(rng, 0.01, 0.05),
                "request_reauth": jitter_p(rng, 0.00, 0.03),
                "request_new_payment_method": jitter_p(rng, 0.01, 0.04),
                "escalate_to_merchant": jitter_p(rng, 0.01, 0.04),
            }
        )
    else:
        raise ValueError(true_class)
    return {a: round_f(p[a]) for a in ACTIONS}


def hold_delay_h(incident_id: str | None, incidents: dict, sim_hour: float) -> float:
    if incident_id is None:
        return 6.0
    inc = incidents[incident_id]
    remaining = float(inc["start_sim_hour"]) + float(inc["window_h"]) - sim_hour
    return max(0.5, remaining)


def p_eff(
    action: str,
    base_p: dict[str, float],
    profile: dict,
    *,
    sim_hour: float,
    attempt_k: int,
    contacts: int,
    fatigue: float,
    incident_id: str | None,
    incidents: dict,
) -> float:
    """SPEC §3 effective success probability. Clamped to [0, 0.98]."""
    if action == "stop":
        return 0.0
    delay = ACTION_DELAY_H[action]
    if delay is None:
        delay = hold_delay_h(incident_id, incidents, sim_hour)
    td = time_decay(delay, profile[action]["optimal_delay_h"], profile[action]["decay_lambda"])
    # Hold / post-window retry is scored at scheduled execution time.
    t_exec = sim_hour + float(delay)
    if incident_id is None:
        inc_m = 1.0
    else:
        inc_m = incident_rate(incidents[incident_id], t_exec)
        # After the window, INC-1/2 recover to 1.0; INC-3 ends at last trajectory point
        # (partial self-heal) which incident_rate already returns as 1.0 outside window.
        # For hold, t_exec is the window end → just outside, multiplier 1.0. Good for INC-1/2.
        # INC-3 right answer is still hold; last in-window rate is 0.88. Snap hold to
        # the last trajectory rate if execution lands exactly on the boundary.
        inc = incidents[incident_id]
        end = float(inc["start_sim_hour"]) + float(inc["window_h"])
        if incident_id == "INC-3" and t_exec >= end - 1e-9:
            inc_m = float(inc["trajectory"][-1]["success_rate"])
    fat = fatigue ** attempt_k
    vis = 1.0 if action in ZERO_FRICTION else (0.90 ** contacts)
    raw = base_p[action] * td * inc_m * fat * vis
    return max(0.0, min(0.98, raw))


def intervention_cost(action: str, oracle: dict) -> float:
    if action == "stop":
        return 0.0
    if action in {"retry_1h", "retry_6h", "retry_24h", "retry_72h", "retry_7d"}:
        return float(oracle["gateway_retry_fee_inr"])
    if action == "retry_alternate_route":
        return float(oracle["alternate_route_fee_inr"])
    if action == "hold_for_incident":
        return float(oracle["hold_fee_inr"])
    if action == "send_dunning_notification":
        return float(oracle["dunning_unit_cost_inr"])
    if action in {"send_recovery_link", "request_reauth", "request_new_payment_method"}:
        return float(oracle["link_unit_cost_inr"])
    if action == "escalate_to_merchant":
        return float(oracle["escalate_ops_cost_inr"])
    return 0.0


def risk_cost(action: str, oracle: dict) -> float:
    if action == "stop":
        return 0.0
    if action == "escalate_to_merchant":
        return float(oracle["risk_escalate_inr"])
    if action in ZERO_FRICTION:
        return float(oracle["risk_silent_inr"])
    return float(oracle["risk_visible_inr"])


def friction_cost(
    action: str, ltv: float, engagement: str | float, oracle: dict
) -> float:
    # engagement is 0–1; unused contacts at generation = 0
    churn = float(oracle["churn_increment"][action])
    eng = float(engagement)
    return churn * ltv * (1.2 - eng)


def expected_utility(
    action: str,
    *,
    amount_inr: float,
    base_p: dict,
    profile: dict,
    sim_hour: float,
    fatigue: float,
    incident_id: str | None,
    incidents: dict,
    ltv: float,
    engagement: float,
    oracle: dict,
) -> tuple[float, float, float]:
    """Returns (EU, expected_gross, delay_h)."""
    delay = ACTION_DELAY_H[action]
    if delay is None:
        delay = hold_delay_h(incident_id, incidents, sim_hour)
    p = p_eff(
        action,
        base_p,
        profile,
        sim_hour=sim_hour,
        attempt_k=0,
        contacts=0,
        fatigue=fatigue,
        incident_id=incident_id,
        incidents=incidents,
    )
    days = float(delay) / 24.0
    revenue = amount_inr * ((1.0 - float(oracle["rho_daily"])) ** days)
    expected_gross = p * revenue
    eu = (
        expected_gross
        - friction_cost(action, ltv, engagement, oracle)
        - risk_cost(action, oracle)
        - intervention_cost(action, oracle)
    )
    return eu, expected_gross, float(delay)


def oracle_actions(
    amount_inr: float,
    base_p: dict,
    profile: dict,
    sim_hour: float,
    fatigue: float,
    incident_id: str | None,
    incidents: dict,
    ltv: float,
    engagement: float,
    oracle: dict,
) -> tuple[str, float, str, float, float]:
    best_eu = -1e18
    best_a = "stop"
    best_delay = 0.0
    best_gross = 0.0
    best_rev_only = "stop"
    best_rev = -1.0
    for a in ACTIONS:
        eu, eg, delay = expected_utility(
            a,
            amount_inr=amount_inr,
            base_p=base_p,
            profile=profile,
            sim_hour=sim_hour,
            fatigue=fatigue,
            incident_id=incident_id,
            incidents=incidents,
            ltv=ltv,
            engagement=engagement,
            oracle=oracle,
        )
        if eu > best_eu:
            best_eu, best_a, best_delay, best_gross = eu, a, delay, eg
        if eg > best_rev:
            best_rev, best_rev_only = eg, a
    if best_eu <= 0:
        return "stop", 0.0, best_rev_only if best_rev > 0 else "stop", 0.0, 0.0
    net = best_eu  # expected gross minus expected costs of the winning action
    return best_a, best_delay, best_rev_only, best_gross, net


def pick_true_class_for_ambiguous(rng: random.Random, mix: dict) -> str:
    others = [k for k in POPULATIONS if k != "ambiguous"]
    weights = [mix[k] for k in others]
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for k, w in zip(others, weights):
        acc += w
        if r <= acc:
            return k
    return others[-1]


def failure_for_class(
    true_class: str, observability: str, rng: random.Random
) -> tuple[str, str, str]:
    """Returns failure_code, failure_source, auth_state extra hint."""
    if observability == "ambiguous":
        code = rng.choice(
            [
                "unknown_error",
                "do_not_honour",
                "GATEWAY_ERROR",
                "issuer_down",
                "network_timeout",
            ]
        )
        source = rng.choice(["issuer", "network", "gateway"])
        return code, source, "not_attempted"

    table = {
        "insufficient_funds": ("insufficient_funds", "issuer", "not_required"),
        "expired_card": ("card_expired", "issuer", "not_required"),
        "auth_required": ("authentication_failed", "issuer", "attempted_failed"),
        "transient": ("network_timeout", "network", "not_attempted"),
        "regional_degradation": ("issuer_down", "issuer", "not_attempted"),
        "non_recoverable": rng.choice(
            [
                ("stolen_or_lost_card", "issuer", "not_required"),
                ("risk_blocked", "risk_engine", "not_required"),
                ("payment_method_restricted", "issuer", "not_required"),
            ]
        ),
    }
    if true_class == "non_recoverable":
        return table["non_recoverable"]
    return table[true_class]


def root_cause(true_class: str, incident_id: str | None, observability: str) -> str:
    labels = {
        "transient": "Transient issuer/gateway blip; short silent retry is sufficient",
        "insufficient_funds": "Soft decline on funds; delay into salary/top-up cycle",
        "auth_required": "SCA / mandate re-auth required before any retry will clear",
        "expired_card": "Stored credential expired; needs a new payment method",
        "regional_degradation": "Correlated route/issuer degradation",
        "non_recoverable": "Hard decline; recovery EV is at or below zero",
    }
    s = labels[true_class]
    if incident_id:
        s = f"{s} ({incident_id})"
    if observability == "ambiguous":
        s = "Ambiguous observed code. True class: " + s
    return s


def sample_geography(rng: random.Random, incident_id: str | None, incidents: dict) -> dict:
    if incident_id == "INC-1":
        cohort = incidents["INC-1"]["cohort"]
        return {
            "country": cohort["country"],
            "region_state": rng.choice(IN_STATES),
            "acquirer_route_id": rng.choice(["route_a", "route_b", "route_c"]),
            "is_cross_border": False,
            "card_network": cohort["card_network"],
            "issuer_bank_code": cohort["issuer_bank_code"],
        }
    if incident_id == "INC-2":
        cohort = incidents["INC-2"]["cohort"]
        country = rng.choice(["US", "GB", "AE", "SG"])
        return {
            "country": country,
            "region_state": None,
            "acquirer_route_id": cohort["acquirer_route_id"],
            "is_cross_border": True,
            "card_network": rng.choice(["visa", "mastercard"]),
            "issuer_bank_code": rng.choice(["INTL", "HDFC", "ICICI"]),
        }
    if incident_id == "INC-3":
        return {
            "country": "IN",
            "region_state": rng.choice(IN_STATES),
            "acquirer_route_id": rng.choice(["route_a", "route_b", "route_c"]),
            "is_cross_border": False,
            "card_network": None,
            "issuer_bank_code": incidents["INC-3"]["cohort"]["issuer_bank_code"],
        }
    country = rng.choices(["IN", "US", "AE", "SG", "GB"], weights=[0.62, 0.16, 0.08, 0.08, 0.06])[0]
    return {
        "country": country,
        "region_state": rng.choice(IN_STATES) if country == "IN" else None,
        "acquirer_route_id": rng.choice(["route_a", "route_b", "route_c"]),
        "is_cross_border": country != "IN" and rng.random() < 0.45,
        "card_network": None,  # filled with instrument
        "issuer_bank_code": rng.choice(["HDFC", "ICICI", "SBIN", "AXIS", "KKBK", "PAYTM", "INTL"]),
    }


def sample_instrument(
    rng: random.Random,
    true_class: str,
    incident_id: str | None,
    geo: dict,
) -> dict:
    if incident_id == "INC-1":
        method = "card"
        network = geo["card_network"]
        funding = rng.choice(["debit", "credit"])
        expiry = rng.choice(["valid", "valid", "unknown"])
        token = rng.choice(["network_token", "raw_stored"])
        issuer = geo["issuer_bank_code"]
    elif incident_id == "INC-3":
        method = "upi_autopay"
        network = None
        funding = None
        expiry = "unknown"
        token = "mandate"
        issuer = geo["issuer_bank_code"]
    elif true_class == "expired_card":
        method = rng.choice(["card", "card", "international_card"])
        network = rng.choice(["visa", "mastercard", "rupay", "amex"])
        funding = rng.choice(["credit", "debit"])
        expiry = "expired"
        token = rng.choice(["raw_stored", "network_token"])
        issuer = geo["issuer_bank_code"]
    elif true_class == "auth_required":
        method = rng.choice(["card", "upi_autopay", "emandate_nach"])
        if method == "card":
            network = rng.choice(["visa", "mastercard", "rupay"])
            funding = rng.choice(["credit", "debit"])
            expiry = rng.choice(["valid", "unknown"])
            token = rng.choice(["network_token", "raw_stored"])
        else:
            network = None
            funding = None
            expiry = "unknown"
            token = "mandate"
        issuer = geo["issuer_bank_code"]
    elif true_class == "insufficient_funds" or true_class == "transient":
        method = rng.choices(
            ["card", "upi_collect", "upi_autopay", "netbanking", "wallet", "emandate_nach"],
            weights=[0.42, 0.16, 0.14, 0.12, 0.08, 0.08],
        )[0]
        if method in {"card", "international_card"}:
            network = rng.choice(["visa", "mastercard", "rupay"])
            funding = rng.choice(["credit", "debit", "prepaid"])
            expiry = rng.choice(["valid", "expiring_soon", "unknown"])
            token = rng.choice(["network_token", "raw_stored"])
        else:
            network = None
            funding = None
            expiry = "unknown"
            token = "mandate" if method in {"upi_autopay", "emandate_nach"} else "none"
        issuer = geo["issuer_bank_code"]
    else:
        method = rng.choice(
            ["card", "upi_collect", "netbanking", "wallet", "international_card", "emandate_nach"]
        )
        if "card" in method:
            network = rng.choice(["visa", "mastercard", "rupay", "amex"])
            funding = rng.choice(["credit", "debit", "prepaid"])
            expiry = rng.choice(["valid", "unknown", "expired"])
            token = rng.choice(["network_token", "raw_stored", "none"])
        else:
            network = None
            funding = None
            expiry = "unknown"
            token = rng.choice(["mandate", "none"])
        issuer = geo["issuer_bank_code"]

    if incident_id == "INC-2" and network is None:
        # Cross-border route incident still needs a card-shaped instrument often.
        method = rng.choice(["card", "international_card"])
        network = rng.choice(["visa", "mastercard"])
        funding = rng.choice(["credit", "debit"])
        expiry = "valid"
        token = "network_token"

    return {
        "payment_method": method,
        "card_network": network,
        "card_funding": funding,
        "card_expiry_state": expiry,
        "issuer_bank_code": issuer,
        "token_type": token,
    }


def sample_recurring(rng: random.Random, method: str, true_class: str) -> dict:
    is_recurring = rng.random() < (0.82 if method in {"upi_autopay", "emandate_nach"} else 0.55)
    if not is_recurring:
        return {
            "is_recurring": False,
            "subscription_id": None,
            "billing_cycle": None,
            "cycle_index": 0,
            "mandate_status": "none",
            "days_until_service_suspension": None,
            "is_first_charge_on_instrument": rng.random() < 0.18,
        }
    mandate = "active"
    if true_class == "auth_required" and method in {"upi_autopay", "emandate_nach"}:
        mandate = rng.choice(["expired", "revoked"])
    if true_class == "non_recoverable" and rng.random() < 0.25:
        mandate = "revoked"
    return {
        "is_recurring": True,
        "subscription_id": f"sub_{rng.randint(10000, 99999)}",
        "billing_cycle": rng.choice(["weekly", "monthly", "monthly", "annual"]),
        "cycle_index": rng.randint(1, 36),
        "mandate_status": mandate,
        "days_until_service_suspension": rng.randint(1, 14),
        "is_first_charge_on_instrument": rng.random() < 0.08,
    }


def build_customers(rng: random.Random, n: int = 700) -> list[dict]:
    customers = []
    for i in range(n):
        tenure = rng.randint(5, 2200)
        ok = rng.randint(0, 80)
        fail = rng.randint(0, 18)
        ltv = round_f(rng.uniform(200.0, 85000.0), 2)
        customers.append(
            {
                "customer_id": f"cust_{i:04d}",
                "customer_tenure_days": tenure,
                "lifetime_successful_txns": ok,
                "lifetime_failed_txns": fail,
                "lifetime_value_inr": ltv,
                "prior_recovery_attempts": rng.randint(0, 6),
                "prior_recovery_successes": rng.randint(0, 4),
                "avg_days_between_txns": round_f(rng.uniform(7.0, 45.0), 2),
                "email_engagement_score": round_f(rng.uniform(0.05, 0.95), 4),
                "engagement_recency_days": rng.randint(0, 90),
                "has_alternate_instrument_on_file": rng.random() < 0.28,
                "prior_payment_method_update_count": rng.randint(0, 4),
            }
        )
    return customers


def assign_sim_hour(
    rng: random.Random,
    incident_id: str | None,
    incidents: dict,
    slot: int | None,
) -> float:
    """Non-incident episodes scatter over 0–480h. Incident episodes sit in window steps."""
    if incident_id is None:
        return round_f(rng.uniform(0.0, 480.0), 4)
    inc = incidents[incident_id]
    traj = inc["trajectory"]
    n_steps = len(traj)
    n_ep = int(inc["n_episodes"])
    per = n_ep // n_steps
    rem = n_ep - per * n_steps
    # slot is 0..n_ep-1 within this incident
    assert slot is not None
    boundaries = []
    acc = 0
    for i in range(n_steps):
        size = per + (1 if i < rem else 0)
        boundaries.append((acc, acc + size, i))
        acc += size
    step_i = 0
    for lo, hi, i in boundaries:
        if lo <= slot < hi:
            step_i = i
            break
    start = float(inc["start_sim_hour"])
    off = float(traj[step_i]["offset_h"])
    nxt = float(traj[step_i + 1]["offset_h"]) if step_i + 1 < n_steps else float(inc["window_h"])
    # Stay strictly inside the step so the curve is a clean step function.
    span = max(0.05, nxt - off - 0.05)
    return round_f(start + off + rng.uniform(0.0, span), 4)


def iso_ts(epoch: datetime, sim_hour: float) -> str:
    t = epoch + timedelta(hours=float(sim_hour))
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_episode(
    *,
    index: int,
    seed: int,
    population: str,
    incident_id: str | None,
    incident_slot: int | None,
    cfg: dict,
    rng: random.Random,
    customers: list[dict],
    cust_weights: list[float],
    run_stamp: dict,
) -> tuple[dict, dict]:
    incidents = cfg["incidents"]
    mix = cfg["population_mix"]
    observability = "ambiguous" if population == "ambiguous" else "clear"
    if population == "ambiguous":
        true_class = pick_true_class_for_ambiguous(rng, mix)
    elif population == "regional_degradation":
        true_class = "regional_degradation"
    else:
        true_class = population

    sim_hour = assign_sim_hour(rng, incident_id, incidents, incident_slot)
    geo = sample_geography(rng, incident_id, incidents)
    inst = sample_instrument(rng, true_class, incident_id, geo)
    # INC-1 cohort lock: country + card_network (+ issuer).
    if incident_id == "INC-1":
        assert inst["card_network"] == "rupay"
        assert inst["issuer_bank_code"] == "HDFC"
        assert geo["country"] == "IN"

    merchant_id, vertical, mcc = rng.choice(MERCHANTS)
    lo, hi = VERTICAL_AMOUNT[vertical]
    currency = COUNTRY_CURRENCY[geo["country"]]
    amount = round_f(rng.uniform(lo, hi), 2)
    fx = float(cfg["fx_to_inr"][currency])
    amount_inr = round_f(amount * fx, 2)

    rec = sample_recurring(rng, inst["payment_method"], true_class)
    code, source, auth_default = failure_for_class(true_class, observability, rng)
    auth_state = auth_default
    if true_class == "auth_required" and inst["payment_method"] in {"upi_autopay", "emandate_nach"}:
        auth_state = "mandate_auth_pending"
    if true_class != "auth_required" and rng.random() < 0.08:
        auth_state = rng.choice(["not_required", "not_attempted", "authenticated"])

    cust = rng.choices(customers, weights=cust_weights, k=1)[0]
    epoch = datetime.strptime(cfg["sim_epoch"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    remaining = 6.0
    if incident_id:
        inc = incidents[incident_id]
        remaining = float(inc["start_sim_hour"]) + float(inc["window_h"]) - sim_hour

    regime = cfg.get("regime", run_stamp.get("regime", "homogeneous"))
    base_p = base_success_probs(
        true_class, incident_id, rng, regime=regime, cust=cust, rec=rec, inst=inst, geo=geo
    )
    profile = time_profile(
        true_class, incident_id, remaining, regime=regime, cust=cust, rec=rec, inst=inst, geo=geo
    )
    fatigue = round_f(rng.uniform(0.82, 0.94), 4)
    ltv = cust["lifetime_value_inr"]
    eng = cust["email_engagement_score"]
    friction = {
        a: round_f(friction_cost(a, ltv, eng, cfg["oracle"]), 4) for a in ACTIONS
    }

    opt_a, opt_delay, opt_rev_only, exp_gross, exp_net = oracle_actions(
        amount_inr,
        base_p,
        profile,
        sim_hour,
        fatigue,
        incident_id,
        incidents,
        ltv,
        eng,
        cfg["oracle"],
    )

    max_now = max(
        p_eff(
            a,
            base_p,
            profile,
            sim_hour=sim_hour,
            attempt_k=0,
            contacts=0,
            fatigue=fatigue,
            incident_id=incident_id,
            incidents=incidents,
        )
        for a in ACTIONS
    )
    # "Ever recoverable under best policy" — slightly above single-shot p.
    if true_class == "non_recoverable":
        true_rec = round_f(min(0.12, max_now * 1.4), 4)
    else:
        true_rec = round_f(min(0.98, 1.0 - (1.0 - max_now) ** 3), 4)

    zf_possible = any(
        a in ZERO_FRICTION
        and a != "stop"
        and p_eff(
            a,
            base_p,
            profile,
            sim_hour=sim_hour,
            attempt_k=0,
            contacts=0,
            fatigue=fatigue,
            incident_id=incident_id,
            incidents=incidents,
        )
        >= 0.15
        for a in ACTIONS
    )

    self_heal_p = {
        "transient": 0.12,
        "insufficient_funds": 0.04,
        "auth_required": 0.01,
        "expired_card": 0.0,
        "regional_degradation": 0.03,
        "non_recoverable": 0.0,
    }[true_class]
    self_heal = rng.random() < self_heal_p

    valid = ["stop"] + [a for a in ACTIONS if a != "stop" and base_p[a] > 0]

    inc_mult = 1.0 if incident_id is None else incident_rate(incidents[incident_id], sim_hour)
    curve = None if incident_id is None else curve_ref(incident_id, incidents[incident_id])

    episode_id = f"ep_{seed}_{index}"
    observed = {
        "episode_id": episode_id,
        "merchant_id": merchant_id,
        "merchant_vertical": vertical,
        "customer_id": cust["customer_id"],
        "first_failure_at": iso_ts(epoch, sim_hour),
        "sim_hour": sim_hour,
        "amount": amount,
        "currency": currency,
        "amount_inr": amount_inr,
        "mcc": mcc,
        "payment_method": inst["payment_method"],
        "card_network": inst["card_network"],
        "card_funding": inst["card_funding"],
        "card_expiry_state": inst["card_expiry_state"],
        "issuer_bank_code": inst["issuer_bank_code"],
        "token_type": inst["token_type"],
        "country": geo["country"],
        "region_state": geo["region_state"],
        "acquirer_route_id": geo["acquirer_route_id"],
        "is_cross_border": geo["is_cross_border"],
        "is_recurring": rec["is_recurring"],
        "subscription_id": rec["subscription_id"],
        "billing_cycle": rec["billing_cycle"],
        "cycle_index": rec["cycle_index"],
        "mandate_status": rec["mandate_status"],
        "days_until_service_suspension": rec["days_until_service_suspension"],
        "is_first_charge_on_instrument": rec["is_first_charge_on_instrument"],
        "failure_code": code,
        "failure_message": FAILURE_MESSAGES[code],
        "failure_source": source,
        "auth_state": auth_state,
        "risk_score_gateway": round_f(rng.uniform(0.02, 0.92), 4),
        "prior_soft_declines_on_instrument_30d": rng.randint(0, 7),
        "customer_tenure_days": cust["customer_tenure_days"],
        "lifetime_successful_txns": cust["lifetime_successful_txns"],
        "lifetime_failed_txns": cust["lifetime_failed_txns"],
        "lifetime_value_inr": ltv,
        "prior_recovery_attempts": cust["prior_recovery_attempts"],
        "prior_recovery_successes": cust["prior_recovery_successes"],
        "avg_days_between_txns": cust["avg_days_between_txns"],
        "email_engagement_score": eng,
        "engagement_recency_days": cust["engagement_recency_days"],
        "has_alternate_instrument_on_file": cust["has_alternate_instrument_on_file"],
        "prior_payment_method_update_count": cust["prior_payment_method_update_count"],
        "attempt_index": 0,
        "hours_since_first_failure": 0.0,
        "actions_taken": [],
        "customer_contacts_sent": 0,
        "last_action": None,
        "last_outcome": None,
        "replan_count": 0,
        # D2/D3 stamp — not a strategy feature; strategies must ignore `run`.
        "run": run_stamp,
        # D3: gross column on the observed row equals recoverable amount (same as amount_inr).
        # Realized net is unknown until a strategy executes; left null here so it cannot leak GT.
        "gross_revenue_inr": amount_inr,
        "net_revenue_inr": None,
    }

    gt = {
        "episode_id": episode_id,
        "population": population,
        "true_failure_class": true_class,
        "observability": observability,
        "true_recoverability": true_rec,
        "valid_actions": valid,
        "action_success_probabilities": base_p,
        "action_time_profile": profile,
        "attempt_fatigue_factor": fatigue,
        "customer_friction_cost": friction,
        "incident_id": incident_id,
        "incident_degradation_curve": curve,
        "incident_multiplier": round_f(inc_mult, 4),
        "optimal_action": opt_a,
        "optimal_delay_h": round_f(opt_delay, 4),
        "optimal_action_revenue_only": opt_rev_only,
        "true_max_expected_revenue_inr": round_f(exp_gross, 4),
        "true_max_expected_net_revenue_inr": round_f(exp_net, 4),
        "gross_revenue_inr": amount_inr,
        "net_revenue_inr": round_f(exp_net, 4),
        "zero_friction_recovery_possible": zf_possible,
        "eventual_recovery_without_intervention": self_heal,
        "root_cause_label": root_cause(true_class, incident_id, observability),
        "run": run_stamp,
    }
    return observed, gt


def allocate_labels(n: int, mix: dict, incidents: dict, rng: random.Random) -> list[tuple]:
    """List of (population, incident_id, incident_slot) length n."""
    counts = counts_from_mix(n, mix)
    wanted_inc = sum(int(incidents[i]["n_episodes"]) for i in incidents)
    if counts["regional_degradation"] != wanted_inc:
        raise RuntimeError(
            f"regional_degradation n={counts['regional_degradation']} "
            f"!= incident total {wanted_inc}"
        )
    labels: list[tuple] = []
    for pop, c in counts.items():
        if pop != "regional_degradation":
            labels.extend([(pop, None, None)] * c)
    # Partition regional into incidents in spec order.
    for iid, inc in incidents.items():
        n_i = int(inc["n_episodes"])
        for slot in range(n_i):
            labels.append(("regional_degradation", iid, slot))
    if len(labels) != n:
        raise RuntimeError(f"label list {len(labels)} != n {n}")
    rng.shuffle(labels)
    return labels


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def validate(
    observed: list[dict],
    gt: list[dict],
    cfg: dict,
    seed: int,
) -> dict:
    n = len(observed)
    assert n == len(gt) == cfg["n_episodes"]
    assert_seed_bands(seed, cfg)
    pops = Counter(g["population"] for g in gt)
    expected = counts_from_mix(n, cfg["population_mix"])
    if dict(pops) != expected:
        raise RuntimeError(f"population counts {dict(pops)} != {expected}")
    ids_o = [e["episode_id"] for e in observed]
    ids_g = [g["episode_id"] for g in gt]
    if ids_o != ids_g:
        raise RuntimeError("episode_id mismatch between observed and ground truth")
    if len(set(ids_o)) != n:
        raise RuntimeError("duplicate episode_id")

    for e, g in zip(observed, gt):
        leak = GT_ONLY_FIELDS.intersection(e.keys()) - {"net_revenue_inr"}
        # net_revenue_inr is present on observed but must be null (no GT leak).
        if e.get("net_revenue_inr") is not None:
            raise RuntimeError(f"{e['episode_id']} observed net_revenue_inr is not null")
        if leak:
            raise RuntimeError(f"ground-truth field leaked onto observed: {leak}")
        probs = g["action_success_probabilities"]
        if not isinstance(probs, dict) or set(probs) != set(ACTIONS):
            raise RuntimeError("action_success_probabilities must be a per-action dict")
        if isinstance(probs, (int, float)):
            raise RuntimeError("action_success_probabilities is a scalar")
        if e["gross_revenue_inr"] != e["amount_inr"]:
            raise RuntimeError("D3 gross_revenue_inr must equal amount_inr")
        if "net_revenue_inr" not in g or "gross_revenue_inr" not in g:
            raise RuntimeError("D3 gross/net columns missing on ground truth")
        if g["run"]["mix"] != cfg["population_mix"]:
            raise RuntimeError("D2 mix missing from run stamp")

    inc1 = [g for g in gt if g["incident_id"] == "INC-1"]
    if len(inc1) != cfg["incidents"]["INC-1"]["n_episodes"]:
        raise RuntimeError("INC-1 episode count")
    by_step: dict[int, list] = defaultdict(list)
    inc_cfg = cfg["incidents"]["INC-1"]
    obs_by_id = {e["episode_id"]: e for e in observed}
    countries = set()
    networks = set()
    issuers = set()
    for g in inc1:
        e = obs_by_id[g["episode_id"]]
        countries.add(e["country"])
        networks.add(e["card_network"])
        issuers.add(e["issuer_bank_code"])
        if e["country"] != "IN" or e["card_network"] != "rupay" or e["issuer_bank_code"] != "HDFC":
            raise RuntimeError("INC-1 cohort violation")
        si = step_index(inc_cfg, e["sim_hour"])
        by_step[si].append((e, g))
    if countries != {"IN"} or networks != {"rupay"} or issuers != {"HDFC"}:
        raise RuntimeError("INC-1 is not a single country/network/issuer cluster")

    means = []
    same_route_means = []
    for si in range(len(inc_cfg["trajectory"])):
        rows = by_step[si]
        if not rows:
            raise RuntimeError(f"INC-1 step {si} is empty")
        m = sum(g["incident_multiplier"] for _, g in rows) / len(rows)
        means.append(m)
        same_route_means.append(
            sum(
                g["action_success_probabilities"]["retry_1h"] * g["incident_multiplier"]
                for _, g in rows
            )
            / len(rows)
        )
    for a, b in zip(means, means[1:]):
        if not (b < a - 1e-6):
            raise RuntimeError(f"INC-1 multipliers are not strictly declining: {means}")
    for a, b in zip(same_route_means, same_route_means[1:]):
        if not (b < a - 1e-9):
            raise RuntimeError(
                f"INC-1 same-route success is not strictly declining: {same_route_means}"
            )

    return {"populations": dict(pops), "inc1_step_mean_multiplier": means}


def inc1_curve_report(observed: list[dict], gt: list[dict], cfg: dict) -> list[dict]:
    inc_cfg = cfg["incidents"]["INC-1"]
    obs_by_id = {e["episode_id"]: e for e in observed}
    inc1 = [g for g in gt if g["incident_id"] == "INC-1"]
    incidents = cfg["incidents"]
    steps = []
    for si, pt in enumerate(inc_cfg["trajectory"]):
        nxt = (
            inc_cfg["trajectory"][si + 1]["offset_h"]
            if si + 1 < len(inc_cfg["trajectory"])
            else inc_cfg["window_h"]
        )
        rows = []
        for g in inc1:
            e = obs_by_id[g["episode_id"]]
            if step_index(inc_cfg, e["sim_hour"]) == si:
                rows.append((e, g))
        def mean_peff(action: str) -> float:
            vals = []
            for e, g in rows:
                vals.append(
                    p_eff(
                        action,
                        g["action_success_probabilities"],
                        g["action_time_profile"],
                        sim_hour=e["sim_hour"],
                        attempt_k=0,
                        contacts=0,
                        fatigue=g["attempt_fatigue_factor"],
                        incident_id="INC-1",
                        incidents=incidents,
                    )
                )
            return sum(vals) / len(vals)

        # Same-route retry scored at *current* t (delay 0 analogue): base_p × current multiplier.
        same_route = []
        for e, g in rows:
            same_route.append(
                g["action_success_probabilities"]["retry_1h"] * g["incident_multiplier"]
            )
        hours = [e["sim_hour"] for e, _ in rows]
        steps.append(
            {
                "step": si + 1,
                "offset_h": [pt["offset_h"], nxt],
                "sim_hour_range": [round(min(hours), 4), round(max(hours), 4)],
                "n": len(rows),
                "designed_success_rate": pt["success_rate"],
                "mean_incident_multiplier": round(sum(g["incident_multiplier"] for _, g in rows) / len(rows), 6),
                "mean_same_route_retry_1h_base_x_multiplier": round(sum(same_route) / len(same_route), 6),
                "mean_p_eff_retry_1h_at_scheduled_delay": round(mean_peff("retry_1h"), 6),
                "mean_p_eff_hold_for_incident": round(mean_peff("hold_for_incident"), 6),
            }
        )
    return steps


def sample_from_each_pop(observed: list[dict], gt: list[dict]) -> dict[str, dict]:
    obs_by_id = {e["episode_id"]: e for e in observed}
    out = {}
    for pop in POPULATIONS:
        candidates = [x for x in gt if x["population"] == pop]
        if pop == "regional_degradation":
            chosen = next(x for x in candidates if x["incident_id"] == "INC-1")
        elif pop == "auth_required":
            chosen = next(
                (x for x in candidates if x["optimal_action"] == "request_reauth"),
                candidates[0],
            )
        elif pop == "non_recoverable":
            chosen = next(
                (x for x in candidates if x["optimal_action"] == "stop"),
                candidates[0],
            )
        else:
            chosen = candidates[0]
        out[pop] = {"observed": obs_by_id[chosen["episode_id"]], "ground_truth": chosen}
    return out


def generate(cfg: dict, seed: int, out_dir: Path, regime: str = "homogeneous") -> dict:
    assert_seed_bands(seed, cfg)
    n = int(cfg["n_episodes"])
    rng = random.Random(seed)
    customers = build_customers(rng)
    weights = [1.0 / math.sqrt(i + 1) for i in range(len(customers))]
    labels = allocate_labels(n, cfg["population_mix"], cfg["incidents"], rng)

    run_id = f"run_seed{seed}_{hashlib.sha256(json.dumps(cfg['population_mix'], sort_keys=True).encode()).hexdigest()[:12]}"
    run_stamp = {
        "run_id": run_id,
        "seed": seed,
        "n_episodes": n,
        "mix": cfg["population_mix"],
        "spec_version": cfg.get("spec_version"),
        "horizon_h": cfg["horizon_h"],
        "max_actions": cfg["max_actions"],
        "eval_seed_band": cfg["eval_seed_band"],
        "train_seed_band": cfg["train_seed_band"],
        "revenue": cfg["revenue"],
        "regime": regime,
        "decisions": ["D1", "D2", "D3", "D4"],
    }

    observed, gt = [], []
    for i, (pop, iid, slot) in enumerate(labels):
        o, g = build_episode(
            index=i,
            seed=seed,
            population=pop,
            incident_id=iid,
            incident_slot=slot,
            cfg=cfg,
            rng=rng,
            customers=customers,
            cust_weights=weights,
            run_stamp=run_stamp,
        )
        observed.append(o)
        gt.append(g)

    stats = validate(observed, gt, cfg, seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    ep_path = out_dir / "episodes.jsonl"
    gt_path = out_dir / "ground_truth.jsonl"
    write_jsonl(ep_path, observed)
    write_jsonl(gt_path, gt)

    manifest = {
        "run_id": run_id,
        "seed": seed,
        "n_episodes": n,
        "mix": cfg["population_mix"],
        "population_counts": stats["populations"],
        "spec_version": cfg.get("spec_version"),
        "horizon_h": cfg["horizon_h"],
        "max_actions": cfg["max_actions"],
        "eval_seed_band": cfg["eval_seed_band"],
        "train_seed_band": cfg["train_seed_band"],
        "revenue": cfg["revenue"],
        "regime": regime,
        "decisions": ["D1", "D2", "D3", "D4"],
        "incidents": {
            iid: {
                "n": sum(1 for g in gt if g["incident_id"] == iid),
                "window_h": inc["window_h"],
                "start_sim_hour": inc["start_sim_hour"],
                "trajectory": inc["trajectory"],
                "cohort": inc["cohort"],
            }
            for iid, inc in cfg["incidents"].items()
        },
        "fx_to_inr": cfg["fx_to_inr"],
        "episodes_sha256": sha256_file(ep_path),
        "ground_truth_sha256": sha256_file(gt_path),
        "config_sha256": hashlib.sha256(
            (DEFAULT_CONFIG.read_bytes() if DEFAULT_CONFIG.exists() else b"")
        ).hexdigest(),
        "content_hash": None,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    blob = (manifest["episodes_sha256"] + ":" + manifest["ground_truth_sha256"]).encode()
    manifest["content_hash"] = hashlib.sha256(blob).hexdigest()
    man_path = out_dir / "manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    curve = inc1_curve_report(observed, gt, cfg)
    samples = sample_from_each_pop(observed, gt)
    return {
        "manifest": manifest,
        "inc1_curve": curve,
        "samples": samples,
        "paths": {"episodes": str(ep_path), "ground_truth": str(gt_path), "manifest": str(man_path)},
    }


def _print_sample(pop: str, pair: dict) -> None:
    e, g = pair["observed"], pair["ground_truth"]
    print(f"\n=== {pop} ({e['episode_id']}) ===")
    print(
        f"  observed: failure_code={e['failure_code']!r} country={e['country']} "
        f"method={e['payment_method']} network={e['card_network']} issuer={e['issuer_bank_code']} "
        f"amount_inr={e['amount_inr']} sim_hour={e['sim_hour']} "
        f"gross_revenue_inr={e['gross_revenue_inr']} net_revenue_inr={e['net_revenue_inr']}"
    )
    print(
        f"  hidden: true_class={g['true_failure_class']} observability={g['observability']} "
        f"incident_id={g['incident_id']} optimal_action={g['optimal_action']} "
        f"true_recoverability={g['true_recoverability']} "
        f"gross_revenue_inr={g['gross_revenue_inr']} net_revenue_inr={g['net_revenue_inr']}"
    )
    print(f"  action_success_probabilities: {g['action_success_probabilities']}")
    print(f"  root_cause: {g['root_cause_label']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 1 simulator + ground truth")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--n", type=int, default=None, help="override n_episodes (default from yaml)")
    p.add_argument("--regime", choices=["homogeneous", "heterogeneous", "A", "B"], default="homogeneous",
                   help="GT regime: homogeneous (Regime A) or heterogeneous (Regime B)")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    if args.n is not None:
        cfg["n_episodes"] = args.n
    regime = "heterogeneous" if args.regime in {"heterogeneous", "B"} else "homogeneous"
    result = generate(cfg, args.seed, args.out, regime=regime)
    print("Wrote:")
    for k, v in result["paths"].items():
        print(f"  {k}: {v}")
    print("\nPopulation counts:", result["manifest"]["population_counts"])
    print("content_hash:", result["manifest"]["content_hash"])
    print("\nINC-1 degradation curve (actual numbers):")
    for row in result["inc1_curve"]:
        print(json.dumps(row, sort_keys=True))
    for pop in POPULATIONS:
        _print_sample(pop, result["samples"][pop])
    return 0


if __name__ == "__main__":
    sys.exit(main())
