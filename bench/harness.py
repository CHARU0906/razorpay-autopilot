"""Phase 4 benchmark harness — 8 configs × 10 seeds, all metrics (SPEC §7 + D3 + Option 2).

Usage:
    py -m bench.harness                        # seeds 1-10, all strategies
    py -m bench.harness --seeds 1 2 3          # specific seeds
    py -m bench.harness --strategies autopilot smart_dunning oracle
"""

from __future__ import annotations

import argparse
import json
import math
import random
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

EVAL_SEEDS = list(range(1, 11))   # D4: 10 seeds to start

STRATEGY_NAMES = [
    "no_recovery",
    "fixed_retry",
    "rule_based",
    "learned_smart_retry",
    "smart_dunning",
    "autopilot",
    "autopilot_no_detection",
    "oracle",
]

# Customer-visible actions for UIR (SPEC §7: actions 9-12)
CUSTOMER_VISIBLE = frozenset({
    "send_dunning_notification", "send_recovery_link",
    "request_reauth", "request_new_payment_method",
})
SILENT_RETRY_SET = frozenset({
    "retry_1h", "retry_6h", "retry_24h", "retry_72h", "retry_7d",
    "retry_alternate_route", "hold_for_incident",
})


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def make_strategy(name: str, gt_rows: list[dict], retry_bundle):
    from strategies.no_recovery import NoRecovery
    from strategies.fixed_retry import FixedRetry
    from strategies.rule_based import RuleBased
    from strategies.learned_smart_retry import LearnedSmartRetry
    from strategies.smart_dunning import SmartDunning
    from strategies.oracle import Oracle
    from autopilot.pipeline import Autopilot, AutopilotNoDetection
    import autopilot.policy_engine as pe
    pe._POLICY = None   # fresh policy load per seed

    if name == "no_recovery":     return NoRecovery()
    if name == "fixed_retry":     return FixedRetry()
    if name == "rule_based":      return RuleBased()
    if name == "learned_smart_retry": return LearnedSmartRetry(bundle=retry_bundle)
    if name == "smart_dunning":   return SmartDunning(bundle=retry_bundle)
    if name == "oracle":          return Oracle(gt_rows)
    if name == "autopilot":
        return Autopilot(detection_enabled=True,
                         ground_truth_rows=gt_rows, retry_bundle=retry_bundle)
    if name == "autopilot_no_detection":
        return AutopilotNoDetection(
            ground_truth_rows=gt_rows, retry_bundle=retry_bundle)
    raise ValueError(name)


def run_one_seed(seed: int, strategy_names: list[str], cfg: dict) -> dict[str, dict]:
    """Generate data for seed, run all strategies, return per-strategy metric dicts."""
    from sim.generate import generate
    from strategies.retry_model import load_bundle
    from strategies.common import episode_state_from_observed, MANDATORY_ESCALATION_CODES

    # Generate eval data into a temp dir (don't overwrite seed-1 data/)
    if seed == 1 and (DATA / "episodes.jsonl").exists():
        ep_path = DATA / "episodes.jsonl"
        gt_path = DATA / "ground_truth.jsonl"
        episodes = load_jsonl(ep_path)
        gt_rows  = load_jsonl(gt_path)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            generate(cfg, seed, out)
            episodes = load_jsonl(out / "episodes.jsonl")
            gt_rows  = load_jsonl(out / "ground_truth.jsonl")

    gt_by_id = {g["episode_id"]: g for g in gt_rows}
    retry_bundle = load_bundle()

    results: dict[str, dict] = {}
    for name in strategy_names:
        strat = make_strategy(name, gt_rows, retry_bundle)
        metrics = _run_strategy(name, strat, episodes, gt_by_id, cfg)
        results[name] = metrics
    return results


def _run_strategy(name: str, strat, episodes: list[dict],
                  gt_by_id: dict, cfg: dict) -> dict:
    from strategies.common import episode_state_from_observed, MANDATORY_ESCALATION_CODES

    horizon_h = float(cfg.get("horizon_h", 336))
    max_actions = int(cfg.get("max_actions", 6))

    # Accumulators
    n = len(episodes)
    recovered = 0
    gross_revenue = 0.0
    net_revenue = 0.0
    interventions = 0          # all non-stop actions
    interventions_ex_mandatory = 0  # Option 2: exclude mandatory escalations
    mandatory_escalation_cost = 0.0  # Option 1 footnote
    uir_unnecessary = 0
    uir_total_visible = 0
    wasted_silent = 0
    recovery_hours: list[float] = []
    customer_contacts = 0
    recovered_with_contacts = 0

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

    for obs in episodes:
        gt = gt_by_id[obs["episode_id"]]
        amount_inr = float(obs.get("amount_inr") or 0.0)
        ltv = float(obs.get("lifetime_value_inr") or 0.0)
        eng = float(obs.get("email_engagement_score") or 0.0)
        true_recov = float(gt.get("true_recoverability") or 0.0)
        zero_frict = bool(gt.get("zero_friction_recovery_possible", False))

        state = episode_state_from_observed(obs)
        action, params = strat.decide(obs, state)

        if action == "stop":
            continue  # no intervention, no recovery (for first-action-only mode)

        interventions += 1

        # Mandatory escalation check
        is_mandatory = (action == "escalate_to_merchant"
                        and obs.get("failure_code") in MANDATORY_ESCALATION_CODES)
        if not is_mandatory:
            interventions_ex_mandatory += 1
        else:
            mandatory_escalation_cost += (
                costs["intervention"]["escalate_ops_cost_inr"]
                + costs["risk"]["risk_escalate_inr"]
            )

        # Recovery: use GT action_success_probabilities as the expected outcome signal
        # (first-action-only bench — no simulation of the full episode loop here)
        base_p = float(gt["action_success_probabilities"].get(action, 0.0))
        p_eff = min(0.98, max(0.0, base_p))  # attempt_k=0, contacts=0
        ep_recovered = (p_eff >= 0.5)   # threshold: action is "likely successful"

        if ep_recovered:
            recovered += 1
            gross_revenue += amount_inr
            # Net: gross - realized intervention costs
            c_i = c_int_map.get(action, 0.0)
            c_r = c_risk_map.get(action, 0.0)
            c_f = churn_inc.get(action, 0.0) * ltv * max(0.0, 1.2 - eng)
            net_revenue += amount_inr - c_i - c_r - c_f
            recovery_hours.append(float(obs.get("hours_since_first_failure") or 0.0))
            if action in CUSTOMER_VISIBLE:
                customer_contacts += 1
                recovered_with_contacts += 1

        # UIR: customer-visible actions
        if action in CUSTOMER_VISIBLE:
            uir_total_visible += 1
            unnecessary = False
            if true_recov == 0:
                unnecessary = True
            elif zero_frict:
                # friction was avoidable if a silent retry had >= this action's p
                silent_ps = [float(gt["action_success_probabilities"].get(a, 0.0))
                             for a in SILENT_RETRY_SET]
                if silent_ps and max(silent_ps) >= base_p:
                    unnecessary = True
            if unnecessary:
                uir_unnecessary += 1

        # Wasted silent retries on unrecoverable episodes
        if action in SILENT_RETRY_SET and true_recov == 0:
            wasted_silent += 1

    # Compute metrics
    recovery_rate = recovered / n
    irpi_vs_no_recovery = (
        (gross_revenue / interventions) if interventions > 0 else 0.0
    )  # plain revenue-per-intervention (IRPI denominator = interventions vs no_recovery=0)
    irpi_ex_mandatory = (
        (gross_revenue / interventions_ex_mandatory) if interventions_ex_mandatory > 0 else 0.0
    )
    uir = uir_unnecessary / uir_total_visible if uir_total_visible > 0 else 0.0
    wasted_rate = wasted_silent / interventions if interventions > 0 else 0.0
    mean_recovery_h = (sum(recovery_hours) / len(recovery_hours)) if recovery_hours else 0.0
    contacts_per_recovery = (
        (customer_contacts / recovered) if recovered > 0 else 0.0
    )

    return {
        "n": n,
        "recovered": recovered,
        "recovery_rate": recovery_rate,
        "gross_revenue": gross_revenue,
        "net_revenue": net_revenue,
        "interventions": interventions,
        "interventions_ex_mandatory": interventions_ex_mandatory,
        "mandatory_escalation_count": interventions - interventions_ex_mandatory,
        "mandatory_escalation_cost_inr": mandatory_escalation_cost,
        "irpi_gross": irpi_vs_no_recovery,
        "irpi_gross_ex_mandatory": irpi_ex_mandatory,
        "uir": uir,
        "uir_unnecessary": uir_unnecessary,
        "uir_total_visible": uir_total_visible,
        "wasted_silent_rate": wasted_rate,
        "wasted_silent_count": wasted_silent,
        "mean_recovery_h": mean_recovery_h,
        "contacts_per_recovery": contacts_per_recovery,
    }


def aggregate(seed_results: list[dict[str, dict]]) -> dict[str, dict]:
    """Compute mean ± std across seeds for each strategy."""
    import statistics
    strategies = list(seed_results[0].keys())
    agg = {}
    for name in strategies:
        per_seed = [sr[name] for sr in seed_results]
        keys = [k for k in per_seed[0] if isinstance(per_seed[0][k], (int, float))]
        agg[name] = {}
        for k in keys:
            vals = [float(s[k]) for s in per_seed]
            agg[name][k + "_mean"] = statistics.mean(vals)
            agg[name][k + "_std"]  = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return agg


def print_results_table(agg: dict, seed_results: list[dict], strategy_names: list[str]) -> None:
    import statistics

    # Oracle revenue for % of Oracle
    oracle_gross_mean = agg["oracle"]["gross_revenue_mean"]
    # Smart-Dunning revenue for lift %
    sd_gross_mean = agg["smart_dunning"]["gross_revenue_mean"]
    # No-Recovery interventions = 0, so IRPI vs no_recovery needs special handling
    # Use Smart-Dunning as IRPI baseline per SPEC §7
    sd_interventions_mean = agg["smart_dunning"]["interventions_mean"]
    sd_interventions_ex_mean = agg["smart_dunning"]["interventions_ex_mandatory_mean"]

    LABEL = {
        "no_recovery":            "No Recovery",
        "fixed_retry":            "Fixed Retry",
        "rule_based":             "Rule-Based",
        "learned_smart_retry":    "Learned Smart-Retry",
        "smart_dunning":          "Smart-Dunning (baseline)",
        "autopilot_no_detection": "Autopilot-no-detect [ABLATION]",
        "autopilot":              "Autopilot",
        "oracle":                 "Oracle [CEILING]",
    }

    # Order for display
    order = [
        "no_recovery", "fixed_retry", "rule_based", "learned_smart_retry",
        "smart_dunning", "autopilot_no_detection", "autopilot", "oracle",
    ]

    print("\n" + "="*100)
    print("  PHASE 4 BENCHMARK RESULTS — mean ± std across 10 seeds")
    print("="*100)
    print(f"  D3: Gross revenue = headline. Net revenue in adjacent column.")
    print(f"  Option 2: IRPI excludes mandatory fraud escalations from denominator.")
    print(f"  Option 1 footnote: Autopilot incurs ₹90/episode mandatory ops cost")
    print(f"    on stolen_or_lost_card + risk_blocked episodes; baselines incur ₹0.")
    print()

    # ── Table 1: Recovery metrics ─────────────────────────────────────────────
    print(f"  {'Strategy':34s}  {'Recov%':>7s}  {'Gross Rev (INR)':>18s}  "
          f"{'Net Rev (INR)':>15s}  {'%Oracle':>7s}  {'Lift%vsSD':>9s}")
    print("  " + "-"*95)
    for name in order:
        if name not in agg: continue
        a = agg[name]
        rr   = a["recovery_rate_mean"] * 100
        rr_s = a["recovery_rate_std"] * 100
        gr   = a["gross_revenue_mean"]
        gr_s = a["gross_revenue_std"]
        nr   = a["net_revenue_mean"]
        nr_s = a["net_revenue_std"]
        pct_oracle = (gr / oracle_gross_mean * 100) if oracle_gross_mean > 0 else 0.0
        lift = ((gr - sd_gross_mean) / sd_gross_mean * 100) if sd_gross_mean > 0 else 0.0
        ceiling = " [CEILING]" if name == "oracle" else ""
        ablation = " [ABLATION]" if name == "autopilot_no_detection" else ""
        label = LABEL[name] + ceiling + ablation
        print(f"  {label:40s}  {rr:5.1f}±{rr_s:.1f}  "
              f"{gr:>12,.0f}±{gr_s:>7,.0f}  "
              f"{nr:>10,.0f}±{nr_s:>6,.0f}  "
              f"{pct_oracle:7.1f}%  {lift:+8.1f}%")

    # ── Table 2: IRPI ─────────────────────────────────────────────────────────
    print(f"\n  IRPI = (gross_revenue - Smart-Dunning_gross) / interventions_ex_mandatory")
    print(f"  (Option 2 headline; Option 1 full-interventions IRPI in parentheses)")
    print(f"\n  {'Strategy':34s}  {'Interventions':>13s}  {'IRPI-ex-mand':>13s}  {'IRPI-full':>10s}")
    print("  " + "-"*75)
    for name in order:
        if name not in agg: continue
        a = agg[name]
        iv    = a["interventions_mean"]
        iv_s  = a["interventions_std"]
        iv_ex = a["interventions_ex_mandatory_mean"]
        # IRPI vs Smart-Dunning: (Revenue(S) - Revenue(SD)) / interventions(S)
        gr_mean = a["gross_revenue_mean"]
        gr_sd   = sd_gross_mean
        irpi_ex = ((gr_mean - gr_sd) / iv_ex) if iv_ex > 0 else float("nan")
        irpi_full = ((gr_mean - gr_sd) / iv) if iv > 0 else float("nan")
        mand = a["mandatory_escalation_count_mean"]
        label = LABEL[name]
        print(f"  {label:40s}  {iv:8.0f}±{iv_s:5.0f}  "
              f"{irpi_ex:>+12.2f}  ({irpi_full:>+9.2f})  mand={mand:.0f}")

    # ── Table 3: UIR + wasted attempts + contacts ─────────────────────────────
    print(f"\n  {'Strategy':34s}  {'UIR%':>6s}  {'WastedSilent%':>13s}  "
          f"{'ContactsPerRecov':>16s}  {'MeanRecovH':>11s}")
    print("  " + "-"*85)
    for name in order:
        if name not in agg: continue
        a = agg[name]
        uir  = a["uir_mean"] * 100
        uir_s= a["uir_std"] * 100
        wst  = a["wasted_silent_rate_mean"] * 100
        wst_s= a["wasted_silent_rate_std"] * 100
        cpr  = a["contacts_per_recovery_mean"]
        cpr_s= a["contacts_per_recovery_std"]
        mrh  = a["mean_recovery_h_mean"]
        label = LABEL[name]
        print(f"  {label:40s}  {uir:4.1f}±{uir_s:.1f}  "
              f"{wst:8.1f}±{wst_s:.1f}      "
              f"{cpr:8.3f}±{cpr_s:.3f}  "
              f"{mrh:10.1f}h")

    # ── Lift decomposition: orchestration-gain vs detection-gain (D1) ─────────
    print(f"\n  LIFT DECOMPOSITION (D1) vs Smart-Dunning gross revenue:")
    sd_gr  = agg["smart_dunning"]["gross_revenue_mean"]
    ap6b_gr = agg.get("autopilot_no_detection", {}).get("gross_revenue_mean", sd_gr)
    ap_gr  = agg.get("autopilot", {}).get("gross_revenue_mean", sd_gr)
    orch_gain = ((ap6b_gr - sd_gr) / sd_gr * 100) if sd_gr > 0 else 0.0
    det_gain  = ((ap_gr - ap6b_gr) / sd_gr * 100) if sd_gr > 0 else 0.0
    total_gain = ((ap_gr - sd_gr) / sd_gr * 100) if sd_gr > 0 else 0.0
    print(f"    Orchestration-gain  (Autopilot-no-detect vs Smart-Dunning): {orch_gain:+.2f}%")
    print(f"    Detection-gain      (Autopilot vs Autopilot-no-detect):      {det_gain:+.2f}%")
    print(f"    Total lift          (Autopilot vs Smart-Dunning):            {total_gain:+.2f}%")
    if ap_gr < sd_gr:
        print(f"\n  *** Autopilot LOSES to Smart-Dunning on gross revenue. ***")
        print(f"      Autopilot: {ap_gr:,.0f} INR  Smart-Dunning: {sd_gr:,.0f} INR")

    print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, nargs="+", default=EVAL_SEEDS)
    p.add_argument("--strategies", nargs="+", default=STRATEGY_NAMES)
    p.add_argument("--out", type=Path, default=DATA / "results" / "phase4.json")
    args = p.parse_args(argv)

    import yaml
    cfg = yaml.safe_load((ROOT / "sim_config.yaml").read_text())

    # Validate seeds are all in eval band
    lo, hi = cfg["eval_seed_band"]
    lo_t, hi_t = cfg["train_seed_band"]
    for s in args.seeds:
        if not (lo <= s <= hi):
            raise SystemExit(f"seed {s} is outside eval band [{lo},{hi}]")
        if lo_t <= s <= hi_t:
            raise SystemExit(f"D4 violation: seed {s} is in train band")

    print(f"Phase 4 harness: {len(args.strategies)} strategies × {len(args.seeds)} seeds")
    print(f"  Seeds: {args.seeds}")
    print(f"  Strategies: {args.strategies}")

    seed_results = []
    for i, seed in enumerate(args.seeds, 1):
        t0 = time.time()
        print(f"  [{i}/{len(args.seeds)}] seed={seed} ...", end=" ", flush=True)
        sr = run_one_seed(seed, args.strategies, cfg)
        seed_results.append(sr)
        print(f"done ({time.time()-t0:.1f}s)")

    agg = aggregate(seed_results)
    print_results_table(agg, seed_results, args.strategies)

    # Save results
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out_data = {
        "seeds": args.seeds,
        "strategies": args.strategies,
        "per_seed": [
            {name: sr[name] for name in args.strategies if name in sr}
            for sr in seed_results
        ],
        "aggregate": agg,
    }
    args.out.write_text(json.dumps(out_data, indent=2))
    print(f"  Results saved to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
