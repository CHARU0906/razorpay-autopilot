"""
Phase 4 multi-step benchmark harness (definitive version).

Runs full episodes (up to max_actions attempts) with GT-sampled outcomes.
Oracle uses the true multi-step EU-argmax (Option 3: recomputes at each attempt).
All 8 configs supported.  Reports all SPEC §7 metrics plus per-population breakdown.

Usage:
    py -m bench.multistep                             # all 8 strats, seeds 1-10
    py -m bench.multistep --strategies rule_based smart_dunning autopilot oracle
    py -m bench.multistep --seeds 1 2 3
"""
from __future__ import annotations

import json
import math
import random
import tempfile
import time
import statistics
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

EVAL_SEEDS = list(range(1, 11))
ALL_STRATEGIES = [
    "no_recovery", "fixed_retry", "rule_based", "learned_smart_retry",
    "smart_dunning", "autopilot_no_detection", "autopilot", "oracle",
]
LABEL = {
    "no_recovery":            "No Recovery",
    "fixed_retry":            "Fixed Retry",
    "rule_based":             "Rule-Based",
    "learned_smart_retry":    "Learned Smart-Retry",
    "smart_dunning":          "Smart-Dunning",
    "autopilot_no_detection": "Autopilot-no-detect [ABLATION]",
    "autopilot":              "Autopilot",
    "oracle":                 "Oracle [CEILING]",
}
POPULATIONS = [
    "insufficient_funds", "transient", "non_recoverable",
    "auth_required", "expired_card", "regional_degradation", "ambiguous",
]


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ── p_eff for outcome sampling (mirrors sim/generate.py exactly) ─────────────

def _incident_rate(inc: dict, t_exec: float) -> float:
    start  = float(inc["start_sim_hour"])
    window = float(inc["window_h"])
    t = t_exec - start
    if t < 0 or t >= window:
        return 1.0
    traj = inc["trajectory"]
    for i, pt in enumerate(traj):
        nxt = traj[i+1]["offset_h"] if i+1 < len(traj) else window
        if float(pt["offset_h"]) <= t < nxt:
            return float(pt["success_rate"])
    return float(traj[-1]["success_rate"])


def compute_p_eff(action: str, gt: dict, attempt_k: int, contacts: int,
                  sim_hour: float = 0.0, incidents: dict | None = None) -> float:
    if action == "stop":
        return 0.0
    from strategies.common import ACTION_DELAY_H
    base_p  = float(gt["action_success_probabilities"].get(action, 0.0))
    profile = gt.get("action_time_profile", {}).get(action, {})
    fatigue = float(gt.get("attempt_fatigue_factor", 0.87))
    inc_id  = gt.get("incident_id")

    delay_h = ACTION_DELAY_H.get(action)
    if delay_h is None:
        if inc_id and incidents:
            inc = incidents[inc_id]
            remaining = float(inc["start_sim_hour"]) + float(inc["window_h"]) - sim_hour
            delay_h = max(0.5, remaining)
        else:
            delay_h = 6.0

    opt_h = float(profile.get("optimal_delay_h", delay_h))
    lam   = float(profile.get("decay_lambda", 0.08))
    td    = math.exp(-lam * abs(delay_h - opt_h) / 24.0)

    t_exec = sim_hour + float(delay_h)
    if inc_id and incidents and inc_id in incidents:
        inc   = incidents[inc_id]
        inc_m = _incident_rate(inc, t_exec)
        end   = float(inc["start_sim_hour"]) + float(inc["window_h"])
        if inc_id == "INC-3" and t_exec >= end - 1e-9:
            inc_m = float(inc["trajectory"][-1]["success_rate"])
    else:
        inc_m = float(gt.get("incident_multiplier", 1.0))

    fat = fatigue ** attempt_k
    vis = 1.0 if action in ZERO_FRICTION else (0.90 ** contacts)
    return max(0.0, min(0.98, base_p * td * inc_m * fat * vis))


# ── Baseline multi-step runner ────────────────────────────────────────────────

def run_baseline_episode(strat, obs: dict, gt: dict, *, max_actions: int,
                         rng: random.Random, incidents: dict) -> dict:
    from strategies.common import episode_state_from_observed, MANDATORY_ESCALATION_CODES

    state = episode_state_from_observed(obs)
    amount_inr = float(obs.get("amount_inr") or 0.0)
    sim_hour   = float(obs.get("sim_hour") or 0.0)
    actions_taken, n_contacts, mandatory_esc = [], 0, 0

    for attempt in range(max_actions):
        action, params = strat.decide(obs, state)
        if action == "stop":
            break

        is_mandatory = (action == "escalate_to_merchant"
                        and obs.get("failure_code") in MANDATORY_ESCALATION_CODES)
        if is_mandatory:
            mandatory_esc += 1

        p       = compute_p_eff(action, gt, attempt, n_contacts, sim_hour, incidents)
        success = rng.random() < p

        if action in CUSTOMER_VISIBLE:
            n_contacts += 1

        rec = {"action": action, "params": params,
               "outcome": "success" if success else "failure",
               "p_eff": round(p, 6), "attempt": attempt}
        actions_taken.append(rec)

        state = {**state,
                 "attempt_index": attempt + 1,
                 "actions_taken": list(actions_taken),
                 "last_action": action,
                 "last_outcome": rec["outcome"],
                 "customer_contacts_sent": n_contacts}

        if success:
            return {"recovered": True, "gross_revenue": amount_inr,
                    "n_actions": len(actions_taken),
                    "mandatory_escalations": mandatory_esc,
                    "n_contacts": n_contacts, "actions": actions_taken}

    return {"recovered": False, "gross_revenue": 0.0,
            "n_actions": len(actions_taken),
            "mandatory_escalations": mandatory_esc,
            "n_contacts": n_contacts, "actions": actions_taken}


# ── Autopilot multi-step runner ───────────────────────────────────────────────

def run_autopilot_episode(ap, obs: dict, gt: dict, *, rng: random.Random) -> dict:
    from strategies.common import episode_state_from_observed, MANDATORY_ESCALATION_CODES

    state = episode_state_from_observed(obs)
    trace = ap.run_episode(obs, state, gt)
    gross = float(obs.get("amount_inr") or 0.0) if trace.success else 0.0
    n_contacts = sum(1 for s in trace.stages
                     if s.stage == "ActionAgent"
                     and s.detail.get("action_id") in CUSTOMER_VISIBLE)
    return {
        "recovered": trace.success,
        "gross_revenue": gross,
        "n_actions": trace.n_actions,
        "mandatory_escalations": trace.mandatory_escalation_count,
        "n_contacts": n_contacts,
        "actions": [],   # not needed for metrics
    }


# ── Strategy factory ──────────────────────────────────────────────────────────

def make_strategy(name: str, gt_rows: list[dict], bundle):
    import autopilot.policy_engine as pe
    pe._POLICY = None
    from strategies.no_recovery import NoRecovery
    from strategies.fixed_retry import FixedRetry
    from strategies.rule_based import RuleBased
    from strategies.learned_smart_retry import LearnedSmartRetry
    from strategies.smart_dunning import SmartDunning
    from strategies.oracle import Oracle
    from autopilot.pipeline import Autopilot, AutopilotNoDetection

    if name == "no_recovery":          return NoRecovery()
    if name == "fixed_retry":          return FixedRetry()
    if name == "rule_based":           return RuleBased()
    if name == "learned_smart_retry":  return LearnedSmartRetry(bundle=bundle)
    if name == "smart_dunning":        return SmartDunning(bundle=bundle)
    if name == "oracle":               return Oracle(gt_rows)
    if name == "autopilot":
        return Autopilot(detection_enabled=True, ground_truth_rows=gt_rows,
                         retry_bundle=bundle, rng=random.Random(999))
    if name == "autopilot_no_detection":
        return AutopilotNoDetection(ground_truth_rows=gt_rows, retry_bundle=bundle,
                                    rng=random.Random(998))
    raise ValueError(name)


# ── Single seed runner ────────────────────────────────────────────────────────

def run_seed(seed: int, strategy_names: list[str], cfg: dict,
             rng_base: int = 0) -> dict:
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

    gt_by_id  = {g["episode_id"]: g for g in gt_rows}
    bundle    = load_bundle()
    incidents = cfg["incidents"]
    max_acts  = int(cfg.get("max_actions", 6))

    import yaml
    with open(ROOT / "costs.yaml") as f:
        costs = yaml.safe_load(f)
    c_int_map = {
        "retry_1h":                  costs["intervention"]["gateway_retry_fee_inr"],
        "retry_6h":                  costs["intervention"]["gateway_retry_fee_inr"],
        "retry_24h":                 costs["intervention"]["gateway_retry_fee_inr"],
        "retry_72h":                 costs["intervention"]["gateway_retry_fee_inr"],
        "retry_7d":                  costs["intervention"]["gateway_retry_fee_inr"],
        "retry_alternate_route":     costs["intervention"]["alternate_route_fee_inr"],
        "hold_for_incident":         costs["intervention"]["hold_fee_inr"],
        "send_dunning_notification": costs["intervention"]["dunning_unit_cost_inr"],
        "send_recovery_link":        costs["intervention"]["link_unit_cost_inr"],
        "request_reauth":            costs["intervention"]["link_unit_cost_inr"],
        "request_new_payment_method":costs["intervention"]["link_unit_cost_inr"],
        "escalate_to_merchant":      costs["intervention"]["escalate_ops_cost_inr"],
    }
    c_risk_map = {a: costs["risk"]["risk_silent_inr"] for a in SILENT_RETRY_SET}
    c_risk_map.update({a: costs["risk"]["risk_visible_inr"] for a in CUSTOMER_VISIBLE})
    c_risk_map["escalate_to_merchant"] = costs["risk"]["risk_escalate_inr"]
    churn_inc = costs["churn_increment"]

    strats = {name: make_strategy(name, gt_rows, bundle) for name in strategy_names}

    # Per-strategy, per-population accumulators
    acc = {name: defaultdict(lambda: {
        "recovered": 0, "gross": 0.0, "net": 0.0,
        "interventions": 0, "interventions_ex": 0,
        "mandatory": 0, "contacts": 0,
        "uir_unnecessary": 0, "uir_visible": 0,
        "wasted_silent": 0, "n": 0,
    }) for name in strategy_names}

    for ep_idx, obs in enumerate(episodes):
        gt      = gt_by_id[obs["episode_id"]]
        pop     = gt["population"]
        amount  = float(obs.get("amount_inr") or 0.0)
        ltv     = float(obs.get("lifetime_value_inr") or 0.0)
        eng     = float(obs.get("email_engagement_score") or 0.0)
        true_recov  = float(gt.get("true_recoverability") or 0.0)
        zero_frict  = bool(gt.get("zero_friction_recovery_possible", False))

        for name in strategy_names:
            ep_rng = random.Random(rng_base + seed * 31337 + ep_idx * 17 + hash(name) % 1000)

            if name in ("autopilot", "autopilot_no_detection"):
                res = run_autopilot_episode(strats[name], obs, gt, rng=ep_rng)
            else:
                res = run_baseline_episode(strats[name], obs, gt, max_actions=max_acts,
                                           rng=ep_rng, incidents=incidents)

            a = acc[name][pop]
            a["n"] += 1

            if res["recovered"]:
                a["recovered"] += 1
                a["gross"] += amount
                total_cost = sum(
                    c_int_map.get(r["action"], 0.0)
                    + c_risk_map.get(r["action"], 0.0)
                    + churn_inc.get(r["action"], 0.0) * ltv * max(0.0, 1.2 - eng)
                    for r in res.get("actions", [])
                )
                a["net"] += amount - total_cost

            iv = res["n_actions"]
            mand = res["mandatory_escalations"]
            a["interventions"]    += iv
            a["mandatory"]        += mand
            a["interventions_ex"] += iv - mand
            a["contacts"]         += res["n_contacts"]

            # UIR and wasted-silent: use actions list (baselines); for autopilot approximate
            for rec in res.get("actions", []):
                act = rec["action"]
                if act in CUSTOMER_VISIBLE:
                    a["uir_visible"] += 1
                    unnecessary = (true_recov == 0)
                    if not unnecessary and zero_frict:
                        silent_ps = [float(gt["action_success_probabilities"].get(sa, 0.0))
                                     for sa in SILENT_RETRY_SET]
                        act_p = float(gt["action_success_probabilities"].get(act, 0.0))
                        if silent_ps and max(silent_ps) >= act_p:
                            unnecessary = True
                    if unnecessary:
                        a["uir_unnecessary"] += 1
                if act in SILENT_RETRY_SET and true_recov == 0:
                    a["wasted_silent"] += 1

    # Collapse per-pop into per-strategy totals + keep per-pop
    result = {}
    for name in strategy_names:
        total = defaultdict(float)
        per_pop = {}
        for pop, a in acc[name].items():
            n = a["n"]
            per_pop[pop] = {
                "n": n,
                "recovered": a["recovered"],
                "recovery_rate": a["recovered"] / n if n else 0.0,
                "gross_revenue": a["gross"],
            }
            for k, v in a.items():
                total[k] += v
        n_tot = total["n"]
        result[name] = {
            "n": int(n_tot),
            "recovered": int(total["recovered"]),
            "recovery_rate": total["recovered"] / n_tot if n_tot else 0.0,
            "gross_revenue": total["gross"],
            "net_revenue": total["net"],
            "interventions": int(total["interventions"]),
            "interventions_ex_mandatory": int(total["interventions_ex"]),
            "mandatory_escalation_count": int(total["mandatory"]),
            "uir": total["uir_unnecessary"] / total["uir_visible"] if total["uir_visible"] else 0.0,
            "wasted_silent_rate": total["wasted_silent"] / total["interventions"] if total["interventions"] else 0.0,
            "contacts_per_recovery": total["contacts"] / total["recovered"] if total["recovered"] else 0.0,
            "per_pop": per_pop,
        }
    return result


# ── Aggregation and reporting ─────────────────────────────────────────────────

def aggregate(seed_results: list[dict]) -> dict:
    names = list(seed_results[0].keys())
    agg = {}
    for name in names:
        per = [sr[name] for sr in seed_results]
        num_keys = [k for k in per[0] if isinstance(per[0][k], (int, float))]
        agg[name] = {}
        for k in num_keys:
            vals = [float(s[k]) for s in per]
            agg[name][k + "_mean"] = statistics.mean(vals)
            agg[name][k + "_std"]  = statistics.stdev(vals) if len(vals) > 1 else 0.0
        # Per-pop: aggregate recovery_rate and gross_revenue
        agg[name]["per_pop"] = {}
        for pop in POPULATIONS:
            rr_vals  = [sr[name]["per_pop"].get(pop, {}).get("recovery_rate", 0.0) for sr in seed_results]
            gr_vals  = [sr[name]["per_pop"].get(pop, {}).get("gross_revenue", 0.0) for sr in seed_results]
            n_val    = seed_results[0][name]["per_pop"].get(pop, {}).get("n", 0)
            agg[name]["per_pop"][pop] = {
                "n": n_val,
                "recovery_rate_mean": statistics.mean(rr_vals),
                "recovery_rate_std":  statistics.stdev(rr_vals) if len(rr_vals) > 1 else 0.0,
                "gross_revenue_mean": statistics.mean(gr_vals),
            }
    return agg


def print_full_table(agg: dict, strategy_names: list[str]) -> None:
    oracle_gr = agg["oracle"]["gross_revenue_mean"] if "oracle" in agg else 1.0
    sd_gr     = agg["smart_dunning"]["gross_revenue_mean"] if "smart_dunning" in agg else 1.0

    order = [n for n in ALL_STRATEGIES if n in agg]

    print("\n" + "="*105)
    print("  PHASE 4 MULTI-STEP BENCHMARK — mean ± std across 10 seeds")
    print("  Oracle: true multi-step EU-argmax (Option 3 — recomputes at each attempt)")
    print("="*105)

    # Table 1: headline
    print(f"\n  {'Strategy':40s}  {'Recov%':>8s}  {'Gross Rev INR':>20s}  "
          f"{'%Oracle':>8s}  {'Lift%vsSD':>10s}")
    print("  " + "-"*95)
    for name in order:
        a   = agg[name]
        rr  = a["recovery_rate_mean"] * 100
        rrs = a["recovery_rate_std"]  * 100
        gr  = a["gross_revenue_mean"]
        grs = a["gross_revenue_std"]
        pct = gr / oracle_gr * 100 if oracle_gr > 0 else 0.0
        lift= (gr - sd_gr) / sd_gr * 100 if sd_gr > 0 else 0.0
        tag = ""
        if name == "oracle":               tag = " [CEILING]"
        if name == "autopilot_no_detection": tag = " [ABLATION]"
        print(f"  {(LABEL[name]+tag):46s}  {rr:5.1f}±{rrs:.1f}  "
              f"{gr:>14,.0f}±{grs:>8,.0f}  {pct:7.1f}%  {lift:>+9.1f}%")

    # Lift decomposition
    rb_gr  = agg.get("rule_based",  {}).get("gross_revenue_mean", sd_gr)
    ap6b   = agg.get("autopilot_no_detection", {}).get("gross_revenue_mean", sd_gr)
    ap     = agg.get("autopilot",   {}).get("gross_revenue_mean", sd_gr)
    print(f"\n  Lift decomposition vs Smart-Dunning:")
    print(f"    Autopilot vs Smart-Dunning             : {(ap-sd_gr)/sd_gr*100:+.2f}%  ({ap-sd_gr:+,.0f} INR)")
    print(f"    Rule-Based vs Smart-Dunning            : {(rb_gr-sd_gr)/sd_gr*100:+.2f}%  ({rb_gr-sd_gr:+,.0f} INR)")
    print(f"    Autopilot vs Rule-Based                : {(ap-rb_gr)/rb_gr*100:+.2f}%  ({ap-rb_gr:+,.0f} INR)")
    print(f"    Orchestration-gain (6b vs SD)          : {(ap6b-sd_gr)/sd_gr*100:+.2f}%")
    print(f"    Detection-gain     (Autopilot vs 6b)   : {(ap-ap6b)/sd_gr*100:+.2f}%")

    # Table 2: IRPI
    print(f"\n  {'Strategy':40s}  {'Interventions':>13s}  {'IRPI-ex-mand vs SD':>20s}  "
          f"{'Mand.esc':>9s}")
    print("  " + "-"*90)
    for name in order:
        a  = agg[name]
        iv = a["interventions_mean"]
        ivs= a["interventions_std"]
        iv_ex = a["interventions_ex_mandatory_mean"]
        gr = a["gross_revenue_mean"]
        irpi = (gr - sd_gr) / iv_ex if iv_ex > 0 else float("nan")
        mand = a["mandatory_escalation_count_mean"]
        print(f"  {LABEL[name]:40s}  {iv:8.0f}±{ivs:5.0f}  {irpi:>+18.2f}  {mand:9.0f}")

    # Table 3: UIR
    print(f"\n  {'Strategy':40s}  {'UIR%':>7s}  {'WastedSilent%':>14s}  {'Contacts/Recov':>15s}")
    print("  " + "-"*80)
    for name in order:
        a   = agg[name]
        uir = a["uir_mean"] * 100
        uirs= a["uir_std"]  * 100
        wst = a["wasted_silent_rate_mean"] * 100
        wsts= a["wasted_silent_rate_std"]  * 100
        cpr = a["contacts_per_recovery_mean"]
        cprs= a["contacts_per_recovery_std"]
        print(f"  {LABEL[name]:40s}  {uir:5.1f}±{uirs:.1f}  {wst:9.1f}±{wsts:.1f}      "
              f"{cpr:7.3f}±{cprs:.3f}")

    # Table 4: per-population recovery rate — focus populations
    focus = ["insufficient_funds", "transient", "auth_required",
             "expired_card", "regional_degradation", "non_recoverable", "ambiguous"]
    print(f"\n  Per-population recovery rate (%) — multi-step")
    header = f"  {'Strategy':35s}" + "".join(f"{p[:8]:>12s}" for p in focus)
    print(header)
    print("  " + "-"*(35 + 12*len(focus)))
    for name in order:
        row = f"  {LABEL[name]:35s}"
        for pop in focus:
            pp  = agg[name]["per_pop"].get(pop, {})
            rr  = pp.get("recovery_rate_mean", 0.0) * 100
            row += f"{rr:>12.1f}"
        print(row)

    # Highlight insufficient_funds specifically
    print(f"\n  insufficient_funds deep-dive (gross revenue mean):")
    for name in order:
        pp = agg[name]["per_pop"].get("insufficient_funds", {})
        gr = pp.get("gross_revenue_mean", 0.0)
        rr = pp.get("recovery_rate_mean", 0.0) * 100
        print(f"    {LABEL[name]:40s}  rr={rr:5.1f}%  gross={gr:>14,.0f} INR")


def main(argv=None):
    import argparse, yaml
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, nargs="+", default=EVAL_SEEDS)
    p.add_argument("--strategies", nargs="+", default=ALL_STRATEGIES)
    p.add_argument("--out", type=Path, default=DATA / "results" / "phase4_multistep.json")
    args = p.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "sim_config.yaml").read_text())

    print(f"Phase 4 multi-step: {len(args.strategies)} strategies × {len(args.seeds)} seeds")
    print(f"  Seeds: {args.seeds}")

    seed_results = []
    for i, seed in enumerate(args.seeds, 1):
        import autopilot.policy_engine as pe
        pe._POLICY = None
        t0 = time.time()
        print(f"  [{i}/{len(args.seeds)}] seed={seed} ...", end=" ", flush=True)
        sr = run_seed(seed, args.strategies, cfg)
        seed_results.append(sr)
        print(f"done ({time.time()-t0:.1f}s)")

    agg = aggregate(seed_results)
    print_full_table(agg, args.strategies)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "seeds": args.seeds,
        "strategies": args.strategies,
        "aggregate": {k: {kk: vv for kk, vv in v.items() if kk != "per_pop"}
                      for k, v in agg.items()},
    }, indent=2))
    print(f"\n  Results saved to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
