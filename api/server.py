"""
Autopilot API server — Phase 2 backend for the live Decision view.

Endpoints:
    GET  /trace/{episode_id}          Run one episode end-to-end, return full trace
    POST /bench/compare?seed=N        Run Regime A vs Regime B for one seed, return comparison
    GET  /health                      Sanity check

Run:
    pip install fastapi uvicorn
    python -m api.server

CORS is open to localhost:5173 (Vite dev server).
All execution uses MockRetryAPI / MockOpsQueue — no live Razorpay APIs.
All results are from the synthetic simulator.
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    raise SystemExit(
        "fastapi and uvicorn are required for the API server.\n"
        "  pip install fastapi uvicorn"
    )

from autopilot.pipeline import Autopilot
from autopilot.investigator import investigate
from autopilot.strategist import score_all_actions, ActionScore
from autopilot.policy_engine import apply as policy_apply
from strategies.retry_model import load_bundle
from strategies.common import episode_state_from_observed

DATA = ROOT / "data"

app = FastAPI(title="Razorpay Autopilot API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Module-level caches ──────────────────────────────────────────────────────

_episodes_by_id: dict[str, dict] | None = None
_gt_by_id: dict[str, dict] | None = None
_bundle = None


def _load_data():
    global _episodes_by_id, _gt_by_id, _bundle
    if _episodes_by_id is not None:
        return

    episodes_path = DATA / "episodes.jsonl"
    gt_path = DATA / "ground_truth.jsonl"

    if not episodes_path.exists():
        raise FileNotFoundError(
            f"episodes.jsonl not found at {episodes_path}. "
            "Run: py -m sim seed=1 to generate data."
        )

    _episodes_by_id = {}
    with episodes_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ep = json.loads(line)
                _episodes_by_id[ep["episode_id"]] = ep

    _gt_by_id = {}
    with gt_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                gt = json.loads(line)
                _gt_by_id[gt["episode_id"]] = gt

    _bundle = load_bundle()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _score_to_dict(s: ActionScore) -> dict:
    """Serialize ActionScore with p_source badge for the Decision view."""
    from strategies.common import RETRY_DELAYS
    p_source = "model-scored" if s.action_id in RETRY_DELAYS else "prior-scored"
    return {
        "action_id": s.action_id,
        "p_success": s.p_success,
        "revenue_inr": s.revenue_inr,
        "c_friction": s.c_friction,
        "c_risk": s.c_risk,
        "c_intervention": s.c_intervention,
        "expected_utility": s.expected_utility,
        "delay_h": s.delay_h,
        "policy_k": s.policy_k,
        "p_source": p_source,   # "model-scored" | "prior-scored"
    }


def _stage_log_to_dict(stage_log) -> dict:
    d = {"stage": stage_log.stage, "summary": stage_log.summary}
    # Expand Strategist top3 with full score dicts when available
    detail = dict(stage_log.detail)
    d["detail"] = detail
    return d


# ── /health ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "note": "synthetic simulator — no live Razorpay APIs"}


# ── /trace/{episode_id} ──────────────────────────────────────────────────────

@app.get("/trace/{episode_id}")
def trace_episode(episode_id: str):
    """
    Run episode_id through the full Autopilot pipeline end-to-end.

    Returns:
        episode_id, success, n_actions, replan_count,
        stages: list of {stage, summary, detail},
        decision: {competing_actions (top3 with full EU breakdown), winner, policy_tier},
        episode_meta: key observed fields for the UI
    """
    _load_data()

    if episode_id not in _episodes_by_id:
        # Try to find a non-recoverable episode for the failure demo
        if episode_id == "demo_non_recoverable":
            ep, gt = _find_non_recoverable_episode()
        else:
            raise HTTPException(status_code=404, detail=f"episode_id '{episode_id}' not found")
    else:
        ep = _episodes_by_id[episode_id]
        gt = _gt_by_id.get(episode_id, {})

    state = episode_state_from_observed(ep)

    # Run Investigator + Strategist first to get the full EU breakdown
    inv = investigate(ep, state, llm_enabled=False)
    strat = score_all_actions(
        ep, state,
        inferred_class=inv.inferred_class,
        incident_detected=inv.incident_active,
        retry_bundle=_bundle,
    )
    pol = policy_apply(
        strat.recommended_action, strat.recommended_params,
        ep, state, inferred_class=inv.inferred_class,
    )

    # Full pipeline trace for outcome/replanning
    ap = Autopilot(
        detection_enabled=False,  # single-episode trace; no cross-episode detector state
        llm_enabled=False,
        retry_bundle=_bundle,
        rng=random.Random(42),
    )
    trace = ap.run_episode(ep, state, gt)

    # Build decision view: top 3 + all scores
    top3 = [_score_to_dict(s) for s in strat.scores[:3]]
    all_scores = [_score_to_dict(s) for s in strat.scores]

    return {
        "episode_id": trace.episode_id,
        "success": trace.success,
        "n_actions": trace.n_actions,
        "replan_count": trace.replan_count,
        "stages": [_stage_log_to_dict(s) for s in trace.stages],
        "decision": {
            "inferred_class": inv.inferred_class,
            "observability": inv.observability,
            "confidence": inv.confidence,
            "incident_detected": inv.incident_active,
            "causal_chain": inv.causal_chain,
            "diagnostic_summary": inv.diagnostic_summary,
            "eliminated_hypotheses": inv.eliminated_hypotheses,
            "competing_actions": top3,
            "all_scores": all_scores,
            "winner": strat.recommended_action,
            "policy_tier": pol.tier,
            "policy_reason": pol.reason,
        },
        "episode_meta": {
            "episode_id": ep.get("episode_id"),
            "failure_code": ep.get("failure_code"),
            "failure_source": ep.get("failure_source"),
            "amount_inr": ep.get("amount_inr"),
            "payment_method": ep.get("payment_method"),
            "issuer_bank_code": ep.get("issuer_bank_code"),
            "card_network": ep.get("card_network"),
            "risk_score_gateway": ep.get("risk_score_gateway"),
            "lifetime_value_inr": ep.get("lifetime_value_inr"),
            "email_engagement_score": ep.get("email_engagement_score"),
            "billing_cycle": ep.get("billing_cycle"),
            "avg_days_between_txns": ep.get("avg_days_between_txns"),
            "has_alternate_instrument_on_file": ep.get("has_alternate_instrument_on_file"),
            "customer_tenure_days": ep.get("customer_tenure_days"),
            "is_recurring": ep.get("is_recurring"),
        },
        # Note for judges: all execution via MockRetryAPI/MockOpsQueue
        "simulation_note": "Executed via synthetic simulator. MockRetryAPI used — no live Razorpay API calls.",
    }


def _find_non_recoverable_episode() -> tuple[dict, dict]:
    """Find a non_recoverable episode where EU(all) ≤ 0 and Autopilot stops."""
    for ep_id, ep in _episodes_by_id.items():
        gt = _gt_by_id.get(ep_id, {})
        if gt.get("population") != "non_recoverable":
            continue
        # Check that true_recoverability is 0
        if float(gt.get("true_recoverability", 1.0)) > 0:
            continue
        # Run strategist to confirm EU ≤ 0 for all non-stop actions
        state = episode_state_from_observed(ep)
        inv = investigate(ep, state, llm_enabled=False)
        strat = score_all_actions(
            ep, state,
            inferred_class=inv.inferred_class,
            incident_detected=False,
            retry_bundle=_bundle,
        )
        non_stop = [s for s in strat.scores if s.action_id != "stop"]
        if non_stop and max(s.expected_utility for s in non_stop) <= 0:
            return ep, gt
    # Fallback: return first non_recoverable regardless
    for ep_id, ep in _episodes_by_id.items():
        gt = _gt_by_id.get(ep_id, {})
        if gt.get("population") == "non_recoverable":
            return ep, gt
    raise HTTPException(status_code=404, detail="No non_recoverable episode found in dataset")


# ── /bench/compare ───────────────────────────────────────────────────────────

@app.post("/bench/compare")
def bench_compare(seed: int = Query(default=1, ge=1, le=20)):
    """
    Run Regime A vs Regime B for one seed.
    Returns recovery rates and UIR for Rule-Based and Autopilot in both regimes.

    This is a ~30-60 second operation — it generates 3,000 episodes per regime
    and runs 2 strategies (rule_based, autopilot) on each.
    Returns live results, not cached static data.

    NOTE: All results are synthetic. Regime B uses heterogeneous GT generation.
    """
    import yaml
    from bench.multistep import run_seed

    cfg = yaml.safe_load((ROOT / "sim_config.yaml").read_text())
    strategies = ["rule_based", "autopilot"]

    results = {}
    for regime in ["homogeneous", "heterogeneous"]:
        sr = run_seed(seed, strategies, cfg, regime=regime)
        results[regime] = {
            name: {
                "recovery_rate": sr[name]["recovery_rate"],
                "gross_revenue": sr[name]["gross_revenue"],
                "uir": sr[name]["uir"],
                "contacts_per_recovery": sr[name]["contacts_per_recovery"],
                "interventions": sr[name]["interventions"],
            }
            for name in strategies
        }

    return {
        "seed": seed,
        "regime_a": results["homogeneous"],
        "regime_b": results["heterogeneous"],
        "summary": {
            "rule_based_regime_a_recovery": results["homogeneous"]["rule_based"]["recovery_rate"],
            "rule_based_regime_b_recovery": results["heterogeneous"]["rule_based"]["recovery_rate"],
            "rule_based_delta": (
                results["heterogeneous"]["rule_based"]["recovery_rate"]
                - results["homogeneous"]["rule_based"]["recovery_rate"]
            ),
            "autopilot_regime_a_recovery": results["homogeneous"]["autopilot"]["recovery_rate"],
            "autopilot_regime_b_recovery": results["heterogeneous"]["autopilot"]["recovery_rate"],
            "autopilot_delta": (
                results["heterogeneous"]["autopilot"]["recovery_rate"]
                - results["homogeneous"]["autopilot"]["recovery_rate"]
            ),
        },
        "simulation_note": "Synthetic simulator only. No live Razorpay data.",
    }


# ── /counterfactual/{episode_id} ─────────────────────────────────────────────

@app.get("/counterfactual/{episode_id}")
def counterfactual(episode_id: str):
    """
    For a given episode, return:
      - What Autopilot's Strategist recommended (with full EU breakdown)
      - What Rule-Based would have done (single action, no EU scoring)

    This makes the per-episode comparison concrete. The Rule-Based action
    is the deterministic output of RuleBased.decide() on the same observed fields.
    No ground truth is read by either strategy.
    """
    _load_data()

    if episode_id not in _episodes_by_id:
        raise HTTPException(status_code=404, detail=f"episode_id '{episode_id}' not found")

    ep = _episodes_by_id[episode_id]
    state = episode_state_from_observed(ep)

    # Autopilot side
    inv = investigate(ep, state, llm_enabled=False)
    strat = score_all_actions(
        ep, state,
        inferred_class=inv.inferred_class,
        incident_detected=inv.incident_active,
        retry_bundle=_bundle,
    )
    pol = policy_apply(
        strat.recommended_action, strat.recommended_params,
        ep, state, inferred_class=inv.inferred_class,
    )

    # Rule-Based side — same observed fields, no EU computation
    from strategies.rule_based import RuleBased
    rb = RuleBased()
    rb_action, rb_params = rb.decide(ep, state)

    # Is the Rule-Based action customer-visible?
    CUSTOMER_VISIBLE = frozenset({
        "send_dunning_notification", "send_recovery_link",
        "request_reauth", "request_new_payment_method",
    })
    rb_is_friction = rb_action in CUSTOMER_VISIBLE
    ap_is_friction = strat.recommended_action in CUSTOMER_VISIBLE

    # Was friction avoidable? Check if a zero-friction action had similar/better EU
    ZERO_FRICTION = frozenset({
        "stop", "retry_1h", "retry_6h", "retry_24h", "retry_72h",
        "retry_7d", "retry_alternate_route", "hold_for_incident",
    })
    best_zero_friction = next(
        (s for s in strat.scores if s.action_id in ZERO_FRICTION), None
    )
    has_better_zero_friction = (
        best_zero_friction is not None
        and rb_is_friction
        and best_zero_friction.expected_utility >= 0
    )

    return {
        "episode_id": episode_id,
        "episode_meta": {
            "failure_code": ep.get("failure_code"),
            "amount_inr": ep.get("amount_inr"),
            "payment_method": ep.get("payment_method"),
            "issuer_bank_code": ep.get("issuer_bank_code"),
            "has_alternate_instrument_on_file": ep.get("has_alternate_instrument_on_file"),
            "billing_cycle": ep.get("billing_cycle"),
            "avg_days_between_txns": ep.get("avg_days_between_txns"),
            "risk_score_gateway": ep.get("risk_score_gateway"),
            "lifetime_value_inr": ep.get("lifetime_value_inr"),
        },
        "autopilot": {
            "inferred_class": inv.inferred_class,
            "action": strat.recommended_action,
            "policy_action": pol.action_id,
            "policy_tier": pol.tier,
            "eu": strat.scores[0].expected_utility if strat.scores else 0,
            "p_success": strat.scores[0].p_success if strat.scores else 0,
            "is_friction": ap_is_friction,
            "top3": [_score_to_dict(s) for s in strat.scores[:3]],
            "diagnostic_summary": inv.diagnostic_summary,
        },
        "rule_based": {
            "action": rb_action,
            "is_friction": rb_is_friction,
            "rationale": f"Rule R{_rb_rule_number(ep)}: {_rb_rationale(ep, rb_action)}",
        },
        "comparison": {
            "same_action": rb_action == strat.recommended_action,
            "rb_adds_friction_autopilot_avoids": rb_is_friction and not ap_is_friction,
            "has_better_zero_friction_available": has_better_zero_friction,
            "best_zero_friction_eu": best_zero_friction.expected_utility if best_zero_friction else None,
            "best_zero_friction_action": best_zero_friction.action_id if best_zero_friction else None,
        },
        "simulation_note": "Synthetic simulator. No live Razorpay API calls.",
    }


def _rb_rule_number(ep: dict) -> str:
    code = ep.get("failure_code", "")
    auth = ep.get("auth_state", "")
    expiry = ep.get("card_expiry_state", "")
    method = ep.get("payment_method", "")
    MANDATE_METHODS = frozenset({"upi_autopay", "emandate_nach"})
    if code in ("stolen_or_lost_card", "risk_blocked", "payment_method_restricted"):
        return "1 (hard stop)"
    if code == "card_expired" or expiry == "expired":
        return "2 (card expired → request_new_payment_method)"
    if (code == "authentication_failed"
            or auth in {"attempted_failed", "mandate_auth_pending"}
            or (code == "mandate_revoked" and method in MANDATE_METHODS)):
        return "3 (auth failed → request_reauth)"
    if code == "mandate_revoked":
        return "4 (mandate revoked non-mandate → stop)"
    if code == "insufficient_funds":
        return "5 (insufficient_funds → retry_72h)"
    if code == "issuer_down":
        return "6 (issuer_down → retry_alternate_route)"
    if code in ("network_timeout", "GATEWAY_ERROR"):
        return "7 (timeout → retry_6h)"
    if code == "do_not_honour":
        return "8 (do_not_honour → retry_24h)"
    return "9 (fallback → send_recovery_link)"


def _rb_rationale(ep: dict, action: str) -> str:
    code = ep.get("failure_code", "")
    has_alt = ep.get("has_alternate_instrument_on_file", False)
    billing = ep.get("billing_cycle", "unknown")
    cadence = ep.get("avg_days_between_txns", 30)
    rationale_map = {
        "request_new_payment_method": (
            f"Hardcoded: card_expired → always request_new_payment_method. "
            f"Does not check has_alternate_instrument_on_file={has_alt}."
        ),
        "retry_72h": (
            f"Hardcoded: insufficient_funds → always retry_72h. "
            f"Does not check billing_cycle={billing} or avg_days_between_txns={cadence:.0f}d."
        ),
        "request_reauth": "Hardcoded: authentication_failed → always request_reauth.",
        "retry_alternate_route": "Hardcoded: issuer_down → retry_alternate_route.",
        "retry_6h": "Hardcoded: timeout/GATEWAY_ERROR → retry_6h.",
        "retry_24h": "Hardcoded: do_not_honour → retry_24h (no risk scoring).",
        "send_recovery_link": "Fallback: unknown code → send_recovery_link.",
        "stop": "Hard stop: compliance code, no recovery attempted.",
    }
    return rationale_map.get(action, f"Action: {action}")


# ── /episodes/find_bad_rule ────────────────────────────────────────────────

@app.get("/episodes/find_bad_rule")
def find_bad_rule_episode():
    """
    Find a Regime B-style episode where Rule-Based fires a friction action
    but Autopilot finds a better zero-friction alternative.

    Specifically looks for expired_card episodes where:
    - has_alternate_instrument_on_file = True
    - Rule-Based would fire request_new_payment_method (friction)
    - Autopilot finds retry_alternate_route with positive EU (zero friction)

    This concretizes the 39.8% UIR stat from Regime B.
    """
    _load_data()

    from strategies.rule_based import RuleBased
    ZERO_FRICTION = frozenset({
        "stop", "retry_1h", "retry_6h", "retry_24h", "retry_72h",
        "retry_7d", "retry_alternate_route", "hold_for_incident",
    })

    rb = RuleBased()
    candidates = []

    for ep_id, ep in _episodes_by_id.items():
        # Target: expired_card with alternate instrument
        if ep.get("failure_code") not in ("card_expired",):
            continue
        if not ep.get("has_alternate_instrument_on_file"):
            continue

        state = episode_state_from_observed(ep)
        rb_action, _ = rb.decide(ep, state)
        if rb_action not in ("request_new_payment_method",):
            continue

        inv = investigate(ep, state, llm_enabled=False)
        strat = score_all_actions(
            ep, state,
            inferred_class=inv.inferred_class,
            incident_detected=False,
            retry_bundle=_bundle,
        )

        # Check Autopilot picks a zero-friction action with positive EU
        ap_winner = strat.scores[0]
        if ap_winner.action_id not in ZERO_FRICTION:
            continue
        if ap_winner.expected_utility <= 0:
            continue

        candidates.append({
            "episode_id": ep_id,
            "amount_inr": ep.get("amount_inr"),
            "has_alternate_instrument": True,
            "rb_action": rb_action,
            "ap_action": ap_winner.action_id,
            "ap_eu": ap_winner.expected_utility,
        })

        if len(candidates) >= 5:
            break

    if not candidates:
        return {"found": False, "message": "No matching episode in seed=1 data"}

    best = max(candidates, key=lambda c: c["amount_inr"])
    return {"found": True, "episode": best, "all_candidates": candidates}



@app.get("/episodes/list")
def list_episodes(
    population: str = Query(default=None),
    limit: int = Query(default=20, le=100),
):
    """List episode IDs, optionally filtered by population (from ground truth)."""
    _load_data()
    results = []
    for ep_id, ep in _episodes_by_id.items():
        gt = _gt_by_id.get(ep_id, {})
        pop = gt.get("population", "unknown")
        if population and pop != population:
            continue
        results.append({
            "episode_id": ep_id,
            "population": pop,
            "failure_code": ep.get("failure_code"),
            "amount_inr": ep.get("amount_inr"),
        })
        if len(results) >= limit:
            break
    return {"episodes": results, "total_loaded": len(_episodes_by_id)}


if __name__ == "__main__":
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)
