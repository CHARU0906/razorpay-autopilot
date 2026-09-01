"""Master Reproducibility Script — Regenerates every benchmark, test, and table in one shot.

Executes:
1. Feature Leakage & Provenance Audit (bench.leakage_audit)
2. Promise-to-Pay Test Suite (bench.test_promise_tracker)
3. Statistical Rigor Pass across 10 Seeds (bench.statistical_rigor)
4. Cost Constant Sensitivity Sweep (bench.sensitivity)
5. Component Ablation Study (bench.ablation)

Usage:
    py -m bench.reproduce_all
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]

from bench.leakage_audit import main as run_leakage
from bench.test_promise_tracker import main as run_p2p
from bench.statistical_rigor import main as run_stats
from bench.sensitivity import main as run_sensitivity
from bench.ablation import main as run_ablation


def main():
    t0 = time.time()
    print("=" * 95)
    print("  RAZORPAY AUTOPILOT — MASTER END-TO-END REPRODUCIBILITY SUITE")
    print("=" * 95)

    print("\n[1/5] Running Feature Provenance & Leakage Audit...")
    run_leakage()

    print("\n[2/5] Running Promise-to-Pay (P2P) Verification Suite...")
    run_p2p()

    print("\n[3/5] Running Cost Constant Sensitivity Analysis (±20% perturbation)...")
    run_sensitivity()

    print("\n[4/5] Running Component Ablation Study across Evaluation Seeds...")
    run_ablation()

    print("\n[5/5] Running 10-Seed Statistical Rigor & Hypothesis Testing (Regime A + B)...")
    run_stats()

    elapsed = time.time() - t0
    print("\n" + "=" * 95)
    print(f"  ALL BENCHMARKS & TESTS SUCCESSFULLY REPRODUCED in {elapsed:.1f}s")
    print("=" * 95)


if __name__ == "__main__":
    main()

