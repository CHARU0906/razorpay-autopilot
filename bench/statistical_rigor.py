"""Statistical Rigor Pass — Paired Bootstrap CIs & Hypothesis Tests.

Computes:
1. Paired bootstrap 95% confidence intervals (2,000 resamples) for headline lift % and gross revenue.
2. Paired Student's t-test and Wilcoxon signed-rank test comparing:
   - Autopilot vs Smart-Dunning (p-value, t-stat, W-stat)
   - Autopilot vs Rule-Based (p-value, t-stat, W-stat)

Usage:
    py -m bench.statistical_rigor
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def paired_bootstrap_ci(
    sample_a: list[float],
    sample_b: list[float],
    n_resamples: int = 2000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Compute mean paired percentage lift and [lower, upper] bootstrap CI."""
    rng = np.random.default_rng(seed)
    a = np.array(sample_a, dtype=np.float64)
    b = np.array(sample_b, dtype=np.float64)
    n = len(a)
    point_lift = float(np.mean((a - b) / b) * 100.0)
    boot_lifts = []
    for _ in range(n_resamples):
        indices = rng.choice(n, size=n, replace=True)
        boot_a = a[indices]
        boot_b = b[indices]
        mean_a = np.mean(boot_a)
        mean_b = np.mean(boot_b)
        lift = ((mean_a - mean_b) / mean_b) * 100.0 if mean_b > 0 else 0.0
        boot_lifts.append(lift)
    alpha = (1.0 - ci) / 2.0
    lo = float(np.percentile(boot_lifts, alpha * 100.0))
    hi = float(np.percentile(boot_lifts, (1.0 - alpha) * 100.0))
    return point_lift, lo, hi


def run_statistical_analysis(seed_data: list[dict], regime_name: str = "Regime A"):
    ap_gross = [sr["autopilot"]["gross_revenue"] for sr in seed_data]
    sd_gross = [sr["smart_dunning"]["gross_revenue"] for sr in seed_data]
    rb_gross = [sr["rule_based"]["gross_revenue"] for sr in seed_data]

    lift_ap_sd, lo_ap_sd, hi_ap_sd = paired_bootstrap_ci(ap_gross, sd_gross)
    lift_ap_rb, lo_ap_rb, hi_ap_rb = paired_bootstrap_ci(ap_gross, rb_gross)

    t_ap_sd, p_t_ap_sd = stats.ttest_rel(ap_gross, sd_gross)
    t_ap_rb, p_t_ap_rb = stats.ttest_rel(ap_gross, rb_gross)

    w_ap_sd, p_w_ap_sd = stats.wilcoxon(ap_gross, sd_gross)
    w_ap_rb, p_w_ap_rb = stats.wilcoxon(ap_gross, rb_gross)

    print(f"\n{'='*80}")
    print(f"  STATISTICAL RIGOR REPORT -- {regime_name} (across {len(seed_data)} seeds)")
    print(f"{'='*80}")
    print(f"\n1. Paired Bootstrap 95% Confidence Intervals (2,000 resamples):")
    print(f"   Autopilot vs Smart-Dunning Gross Lift: {lift_ap_sd:+.2f}%  [95% CI: {lo_ap_sd:+.2f}%, {hi_ap_sd:+.2f}%]")
    print(f"   Autopilot vs Rule-Based Gross Lift   : {lift_ap_rb:+.2f}%  [95% CI: {lo_ap_rb:+.2f}%, {hi_ap_rb:+.2f}%]")

    print(f"\n2. Hypothesis Testing (Autopilot vs Smart-Dunning):")
    print(f"   Paired t-test       : t = {t_ap_sd:+.4f}, p = {p_t_ap_sd:.4e}")
    print(f"   Wilcoxon signed-rank: W = {w_ap_sd:.1f},  p = {p_w_ap_sd:.4e}")

    print(f"\n3. Hypothesis Testing (Autopilot vs Rule-Based):")
    print(f"   Paired t-test       : t = {t_ap_rb:+.4f}, p = {p_t_ap_rb:.4e}")
    print(f"   Wilcoxon signed-rank: W = {w_ap_rb:.1f},  p = {p_w_ap_rb:.4e}")
    print(f"{'='*80}\n")

    return {
        "regime": regime_name,
        "n_seeds": len(seed_data),
        "lift_vs_sd": {
            "mean_lift_pct": round(lift_ap_sd, 2),
            "ci_95_lo": round(lo_ap_sd, 2),
            "ci_95_hi": round(hi_ap_sd, 2),
            "paired_t_test": {"t_stat": round(float(t_ap_sd), 4), "p_value": float(p_t_ap_sd)},
            "wilcoxon_signed_rank": {"w_stat": round(float(w_ap_sd), 1), "p_value": float(p_w_ap_sd)},
        },
        "lift_vs_rb": {
            "mean_lift_pct": round(lift_ap_rb, 2),
            "ci_95_lo": round(lo_ap_rb, 2),
            "ci_95_hi": round(hi_ap_rb, 2),
            "paired_t_test": {"t_stat": round(float(t_ap_rb), 4), "p_value": float(p_t_ap_rb)},
            "wilcoxon_signed_rank": {"w_stat": round(float(w_ap_rb), 1), "p_value": float(p_w_ap_rb)},
        }
    }


def main():
    import yaml
    from bench.multistep import run_seed, EVAL_SEEDS
    cfg = yaml.safe_load((ROOT / "sim_config.yaml").read_text())
    strats = ["smart_dunning", "rule_based", "autopilot", "oracle"]
    print("Running statistical analysis across seeds...")
    results_a = [run_seed(s, strats, cfg, regime="homogeneous") for s in EVAL_SEEDS]
    stats_a = run_statistical_analysis(results_a, "Regime A (Homogeneous GT)")
    results_b = [run_seed(s, strats, cfg, regime="heterogeneous") for s in EVAL_SEEDS]
    stats_b = run_statistical_analysis(results_b, "Regime B (Heterogeneous Multi-Modal GT)")

    out = {"regime_a": stats_a, "regime_b": stats_b}
    out_file = DATA / "results" / "statistical_rigor.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(out, indent=2))
    print(f"Saved to {out_file}")


if __name__ == "__main__":
    main()

