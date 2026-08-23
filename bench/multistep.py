"""
Multi-step episode simulator for Phase 4 investigation.

Runs full episodes (up to max_actions attempts) with outcome sampling from GT.
Applies the same p_eff formula used by the Autopilot Action Agent.
Baselines re-call decide() after each failure with updated episode_state,
exactly as a real harness would. Autopilot uses its own run_episode().
"""
from __future__ import annotations

import json
import math
import random
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CUSTOMER_VISIBLE = frozenset({
    "send_dunning_notification", "send_recovery_link",
    "request_reauth", "request_new_payment_method",
})
SILENT_RETRY_SET = frozenset({
    "retry_1h", "retry_6h", "retry_24h", "retry_72h", "retry_7d",
    "retry_alternate_route", "hold_for_incident",
})
ZERO_FRICTION = SILENT_RETRY_SET | {"stop"}


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ── p_eff (mirrors sim/generate.py and action_agent.py) ─────────────────────

def compute_p_eff(action: str, gt: dict, attempt_k: int, contacts: int) -> float:
    if action == "stop":
        return 0.0
    base_p = float(gt["action_success_probabilities"].get(action, 0.0))
    profile = gt.get("action_time_profile", {}).get(action, {})
    fatigue = float(gt.get("attempt_fatigue_factor", 0.87))
    delay_h  = float(profile.get("action_delay_h", 1.0))
    opt_h    = float(profile.get("optimal_delay_h", 1.0))
    lam      = float(profile.get("decay_lambda", 0.08))
    td       = math.exp(-lam * abs(delay_h - opt_h) / 24.0)
    inc_m    = float(gt.get("incident_multiplier", 1.0))
    fat      = fatigue ** attempt_k
    vis      = 1.0 if action in ZERO_FRICTION else (0.90 ** contacts)
    return max(0.0, min(0.98, base_p * td * inc_m * fat * vis))


# ── baseline multi-step runner ───────────────────────────────────────────────

def run_baseline_episode(strat, obs: dict, gt: dict, *,
                         max_actions: int = 6, rng: random.Random) -> dict:
    """Drive a baseline through multiple attempts, returning episode outcome."""
    from strategies.common import episode_state_from_observed, MANDATORY_ESCALATION_CODES

    state = episode_state_from_observed(obs)
    amount_inr = float(obs.get("amount_inr") or 0.0)
    actions_taken = []
    gross_revenue = 0.0
    n_contacts = 0
    mandatory_escalations = 0

    for attempt in range(max_actions):
        action, params = strat.decide(obs, state)

        if action == "stop":
            break

        is_mandatory = (action == "escalate_to_merchant"
                        and obs.get("failure_code") in MANDATORY_ESCALATION_CODES)
        if is_mandatory:
            mandatory_escalations += 1

        p = compute_p_eff(action, gt, attempt, n_contacts)
        success = rng.random() < p

        if action in CUSTOMER_VISIBLE:
            n_contacts += 1

        actions_taken.append({
            "action": action, "params": params,
            "outcome": "success" if success else "failure",
            "p_eff": round(p, 6),
            "attempt": attempt,
        })

        # Update state for next decide() call
        state = dict(state)
        state["attempt_index"] = attempt + 1
        state["actions_taken"] = list(actions_taken)
        state["last_action"] = action
        state["last_outcome"] = "success" if success else "failure"
        state["customer_contacts_sent"] = n_contacts

        if success:
            gross_revenue = amount_inr
            break

    return {
        "recovered": gross_revenue > 0,
        "gross_revenue": gross_revenue,
        "n_actions": len(actions_taken),
        "actions": actions_taken,
        "mandatory_escalations": mandatory_escalations,
        "n_contacts": n_contacts,
    }


# ── Autopilot multi-step runner ──────────────────────────────────────────────

def run_autopilot_episode(ap, obs: dict, gt: dict, *, rng: random.Random) -> dict:
    from strategies.common import MANDATORY_ESCALATION_CODES
    from strategies.common import episode_state_from_observed

    state = episode_state_from_observed(obs)
    trace = ap.run_episode(obs, state, gt)
    gross_revenue = float(obs.get("amount_inr") or 0.0) if trace.success else 0.0
    return {
        "recovered": trace.success,
        "gross_revenue": gross_revenue,
        "n_actions": trace.n_actions,
        "mandatory_escalations": trace.mandatory_escalation_count,
        "n_contacts": sum(1 for s in trace.stages
                         if s.stage == "ActionAgent"
                         and s.detail.get("action_id") in CUSTOMER_VISIBLE),
    }


# ── Run one seed ─────────────────────────────────────────────────────────────

def run_seed_multistep(seed: int, strategy_names: list[str],
                       cfg: dict, master_rng_seed: int = 0) -> dict[str, dict]:
    import autopilot.policy_engine as pe
    pe._POLICY = None
    from strategies.retry_model import load_bundle
    from strategies.common import MANDATORY_ESCALATION_CODES

    if seed == 1 and (DATA / "episodes.jsonl").exists():
        episodes = load_jsonl(DATA / "episodes.jsonl")
        gt_rows  = load_jsonl(DATA / "ground_truth.jsonl")
    else:
        from sim.generate import generate
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            generate(cfg, seed, out)
            episodes = load_jsonl(out / "episodes.jsonl")
            gt_rows  = load_jsonl(out / "ground_truth.jsonl")

    gt_by_id = {g["episode_id"]: g for g in gt_rows}
    bundle = load_bundle()

    from strategies.rule_based import RuleBased
    from strategies.smart_dunning import SmartDunning
    from autopilot.pipeline import Autopilot, AutopilotNoDetection

    strats = {}
    for name in strategy_names:
        if name == "rule_based":
            strats[name] = RuleBased()
        elif name == "smart_dunning":
            strats[name] = SmartDunning(bundle=bundle)
        elif name == "autopilot":
            strats[name] = Autopilot(
                detection_enabled=True, ground_truth_rows=gt_rows,
                retry_bundle=bundle, rng=random.Random(master_rng_seed + seed * 7))
        elif name == "autopilot_no_detection":
            strats[name] = AutopilotNoDetection(
                ground_truth_rows=gt_rows, retry_bundle=bundle,
                rng=random.Random(master_rng_seed + seed * 13))

    results = {name: {"recovered": 0, "gross": 0.0, "net": 0.0,
                      "interventions": 0, "interventions_ex": 0,
                      "mandatory": 0, "contacts": 0}
               for name in strategy_names}

    import yaml
    with open(ROOT / "costs.yaml") as f:
        costs = yaml.safe_load(f)
    c_int_map = {
        "retry_1h": costs["intervention"]["gateway_retry_fee_inr"],
        "retry_6h": costs["intervention"]["gateway_retry_fee_inr"],
        "retry_24h": costs["intervention"]["gateway_retry_fee_inr"],
        "retry_72h": costs["intervention"]["gateway_retry_fee_inr"],
        "retry_7d": costs["intervention"]["gateway_retry_fee_inr"],
        "retry_alternate_route": costs["intervention"]["alternate_route_fee_inr"],
        "hold_for_incident": costs["intervention"]["hold_fee_inr"],
        "send_dunning_notification": costs["intervention"]["dunning_unit_cost_inr"],
        "send_recovery_link": costs["intervention"]["link_unit_cost_inr"],
        "request_reauth": costs["intervention"]["link_unit_cost_inr"],
        "request_new_payment_method": costs["intervention"]["link_unit_cost_inr"],
        "escalate_to_merchant": costs["intervention"]["escalate_ops_cost_inr"],
    }
    c_risk_map = {a: costs["risk"]["risk_silent_inr"] for a in SILENT_RETRY_SET}
    c_risk_map.update({a: costs["risk"]["risk_visible_inr"] for a in CUSTOMER_VISIBLE})
    c_risk_map["escalate_to_merchant"] = costs["risk"]["risk_escalate_inr"]
    churn_inc = costs["churn_increment"]
    rho = costs["revenue"]["rho_daily"]

    max_actions = int(cfg.get("max_actions", 6))

    for ep_idx, obs in enumerate(episodes):
        gt = gt_by_id[obs["episode_id"]]
        amount = float(obs.get("amount_inr") or 0.0)
        ltv    = float(obs.get("lifetime_value_inr") or 0.0)
        eng    = float(obs.get("email_engagement_score") or 0.0)

        for name in strategy_names:
            ep_rng = random.Random(master_rng_seed + seed * 31337 + ep_idx)
            if name in ("autopilot", "autopilot_no_detection"):
                res = run_autopilot_episode(strats[name], obs, gt, rng=ep_rng)
            else:
                res = run_baseline_episode(strats[name], obs, gt,
                                           max_actions=max_actions, rng=ep_rng)
            r = results[name]
            if res["recovered"]:
                r["recovered"] += 1
                r["gross"] += amount
                # compute net for recovered episode's actions
                total_cost = 0.0
                for act_rec in res.get("actions", []):
                    a = act_rec["action"]
                    total_cost += c_int_map.get(a, 0.0)
                    total_cost += c_risk_map.get(a, 0.0)
                    total_cost += churn_inc.get(a, 0.0) * ltv * max(0.0, 1.2 - eng)
                r["net"] += amount - total_cost
            r["interventions"] += res["n_actions"]
            r["mandatory"] += res["mandatory_escalations"]
            r["interventions_ex"] += res["n_actions"] - res["mandatory_escalations"]
            r["contacts"] += res["n_contacts"]

    n = len(episodes)
    out = {}
    for name in strategy_names:
        r = results[name]
        iv = r["interventions"]
        iv_ex = r["interventions_ex"]
        out[name] = {
            "n": n,
            "recovered": r["recovered"],
            "recovery_rate": r["recovered"] / n,
            "gross_revenue": r["gross"],
            "net_revenue": r["net"],
            "interventions": iv,
            "interventions_ex_mandatory": iv_ex,
            "mandatory_escalation_count": r["mandatory"],
        }
    return out


def main():
    import yaml, statistics
    cfg = yaml.safe_load((ROOT / "sim_config.yaml").read_text())
    SEEDS = list(range(1, 11))
    STRATS = ["rule_based", "smart_dunning", "autopilot_no_detection", "autopilot"]
    LABEL = {
        "rule_based":             "Rule-Based",
        "smart_dunning":          "Smart-Dunning",
        "autopilot_no_detection": "Autopilot-no-detect [ABLATION]",
        "autopilot":              "Autopilot",
    }

    print(f"Multi-step simulation: {len(STRATS)} strategies × {len(SEEDS)} seeds")
    seed_results = []
    for i, seed in enumerate(SEEDS, 1):
        t0 = time.time()
        print(f"  [{i}/{len(SEEDS)}] seed={seed} ...", end=" ", flush=True)
        sr = run_seed_multistep(seed, STRATS, cfg)
        seed_results.append(sr)
        print(f"done ({time.time()-t0:.1f}s)")

    # Aggregate
    agg = {}
    for name in STRATS:
        per = [sr[name] for sr in seed_results]
        keys = [k for k in per[0] if isinstance(per[0][k], (int, float))]
        agg[name] = {k+"_mean": statistics.mean(float(s[k]) for s in per)
                     for k in keys}
        for k in keys:
            vals = [float(s[k]) for s in per]
            agg[name][k+"_std"] = statistics.stdev(vals) if len(vals) > 1 else 0.0

    sd_gr = agg["smart_dunning"]["gross_revenue_mean"]

    print(f"\n=== MULTI-STEP RESULTS (mean ± std, 10 seeds) ===")
    print(f"\n  {'Strategy':36s}  {'Recov%':>7s}  {'Gross Rev INR':>18s}  "
          f"{'Lift%vsSD':>10s}  {'Interventions':>13s}")
    print("  " + "-"*90)
    for name in STRATS:
        a = agg[name]
        rr  = a["recovery_rate_mean"]*100
        rrs = a["recovery_rate_std"]*100
        gr  = a["gross_revenue_mean"]
        grs = a["gross_revenue_std"]
        iv  = a["interventions_mean"]
        ivs = a["interventions_std"]
        lift= (gr - sd_gr)/sd_gr*100 if sd_gr>0 else 0.0
        print(f"  {LABEL[name]:36s}  {rr:5.1f}±{rrs:.1f}  "
              f"{gr:>12,.0f}±{grs:>7,.0f}  {lift:>+9.1f}%  {iv:>8.0f}±{ivs:.0f}")

    print(f"\n  LIFT DECOMPOSITION:")
    sd_gr  = agg["smart_dunning"]["gross_revenue_mean"]
    ap6b   = agg["autopilot_no_detection"]["gross_revenue_mean"]
    ap     = agg["autopilot"]["gross_revenue_mean"]
    orch   = (ap6b - sd_gr)/sd_gr*100 if sd_gr>0 else 0.0
    det    = (ap   - ap6b)/sd_gr*100  if sd_gr>0 else 0.0
    total  = (ap   - sd_gr)/sd_gr*100 if sd_gr>0 else 0.0
    print(f"    Orchestration-gain (6b vs Smart-Dunning) : {orch:+.2f}%")
    print(f"    Detection-gain     (Autopilot vs 6b)     : {det:+.2f}%")
    print(f"    Total lift         (Autopilot vs SD)     : {total:+.2f}%")
    if ap < sd_gr:
        print(f"\n  *** Autopilot LOSES to Smart-Dunning in multi-step. ***")
        print(f"      Autopilot: {ap:,.0f}  Smart-Dunning: {sd_gr:,.0f}")


if __name__ == "__main__":
    main()
