"""Cost Constant Sensitivity Analysis (SPEC §6.1, Task 4).

Perturbs costs.yaml constants by ±20% across:
- C_friction (churn_increment)
- C_risk (risk_silent_inr, risk_visible_inr, risk_escalate_inr)
- C_intervention (retry fee, alternate route fee, link cost, dunning cost, ops cost)

Measures stability of Autopilot lift over Smart-Dunning and recovery rate.

Usage:
    py -m bench.sensitivity
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

import autopilot.strategist as strat_mod
from bench.multistep import run_seed, aggregate, EVAL_SEEDS


def perturb_costs(base_costs: dict, f_factor: float, r_factor: float, i_factor: float) -> dict:
    c = copy.deepcopy(base_costs)
    
    # 1. Friction perturbation
    for a in c.get("churn_increment", {}):
        c["churn_increment"][a] = round(c["churn_increment"][a] * f_factor, 6)
        
    # 2. Risk perturbation
    for k in c.get("risk", {}):
        c["risk"][k] = round(c["risk"][k] * r_factor, 4)
        
    # 3. Intervention perturbation
    for k in c.get("intervention", {}):
        c["intervention"][k] = round(c["intervention"][k] * i_factor, 4)
        
    return c


def evaluate_cost_perturbation(name: str, costs_override: dict, seeds: list[int], cfg: dict) -> dict:
    strat_mod._COSTS = costs_override
    
    strats = ["smart_dunning", "autopilot", "rule_based"]
    seed_results = [run_seed(s, strats, cfg, regime="homogeneous") for s in seeds]
    agg = aggregate(seed_results)
    
    ap_gr = agg["autopilot"]["gross_revenue_mean"]
    sd_gr = agg["smart_dunning"]["gross_revenue_mean"]
    rb_gr = agg["rule_based"]["gross_revenue_mean"]
    
    lift_sd = (ap_gr - sd_gr) / sd_gr * 100.0 if sd_gr else 0.0
    lift_rb = (ap_gr - rb_gr) / rb_gr * 100.0 if rb_gr else 0.0
    
    rec_ap = agg["autopilot"]["recovery_rate_mean"] * 100.0
    uir_ap = agg["autopilot"]["uir_mean"] * 100.0
    
    return {
        "perturbation": name,
        "autopilot_recovery_pct": round(rec_ap, 2),
        "autopilot_gross_inr": round(ap_gr, 0),
        "autopilot_uir_pct": round(uir_ap, 2),
        "lift_vs_smart_dunning_pct": round(lift_sd, 2),
        "lift_vs_rule_based_pct": round(lift_rb, 2),
    }


def main():
    cfg = yaml.safe_load((ROOT / "sim_config.yaml").read_text())
    base_costs = yaml.safe_load((ROOT / "costs.yaml").read_text())
    
    seeds = EVAL_SEEDS[:5] # fast evaluation across 5 seeds
    
    perturbations = [
        ("Nominal Baseline (0%)", 1.0, 1.0, 1.0),
        ("C_friction +20%", 1.2, 1.0, 1.0),
        ("C_friction -20%", 0.8, 1.0, 1.0),
        ("C_risk +20%", 1.0, 1.2, 1.0),
        ("C_risk -20%", 1.0, 0.8, 1.0),
        ("C_intervention +20%", 1.0, 1.0, 1.2),
        ("C_intervention -20%", 1.0, 1.0, 0.8),
        ("All Costs +20%", 1.2, 1.2, 1.2),
        ("All Costs -20%", 0.8, 0.8, 0.8),
    ]
    
    print(f"\n{'='*95}")
    print("  COST SENSITIVITY ANALYSIS -- Autopilot Stability Under +/-20% Cost Perturbation")
    print(f"{'='*95}")
    print(f"  {'Perturbation':28s}  {'Recov%':>8s}  {'Gross Rev INR':>18s}  {'UIR%':>6s}  {'Lift vs SD%':>12s}  {'Lift vs RB%':>12s}")
    print("  " + "-"*90)
    
    results = []
    for name, f_m, r_m, i_m in perturbations:
        c_pert = perturb_costs(base_costs, f_m, r_m, i_m)
        r = evaluate_cost_perturbation(name, c_pert, seeds, cfg)
        results.append(r)
        print(f"  {r['perturbation']:28s}  {r['autopilot_recovery_pct']:7.2f}%  {r['autopilot_gross_inr']:>17,.0f}  {r['autopilot_uir_pct']:5.1f}%  {r['lift_vs_smart_dunning_pct']:>+11.2f}%  {r['lift_vs_rule_based_pct']:>+11.2f}%")
        
    print(f"{'='*95}\n")
    
    # Restore nominal costs
    strat_mod._COSTS = base_costs
    
    out_file = DATA / "results" / "sensitivity_analysis.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2))
    print(f"Sensitivity results saved to {out_file}")


if __name__ == "__main__":
    main()

