"""Single-episode end-to-end trace for Phase 3 verification.

Usage:
    py -m autopilot.trace_episode --episode ep_1_34
    py -m autopilot.trace_episode --episode ep_1_34 --no-detection
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from strategies.common import episode_state_from_observed

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def print_trace(trace, *, variant_label: str) -> None:
    print(f"\n{'='*72}")
    print(f"  AUTOPILOT EPISODE TRACE -- {variant_label}")
    print(f"  episode_id : {trace.episode_id}")
    print(f"  outcome    : {'SUCCESS [OK]' if trace.success else 'FAILURE [FAIL]'}")
    print(f"  n_actions  : {trace.n_actions}")
    print(f"  final_action: {trace.final_action}")
    print(f"  replan_count: {trace.replan_count}")
    print(f"{'='*72}\n")

    step = 0
    for log in trace.stages:
        if log.stage == "Investigator":
            step += 1
            print(f"  -- ATTEMPT {step} --------------------------------------------------\n")

        prefix = f"  [{log.stage}]"
        # Multi-line stages (Strategist reasoning)
        if "\n" in log.summary:
            print(f"{prefix}")
            for line in log.summary.splitlines():
                print(f"    {line}")
        else:
            print(f"{prefix} {log.summary}")
        print()

    print(f"{'='*72}\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--episode", default="ep_1_34")
    p.add_argument("--episodes", type=Path, default=DATA / "episodes.jsonl")
    p.add_argument("--gt", type=Path, default=DATA / "ground_truth.jsonl")
    p.add_argument("--no-detection", action="store_true",
                   help="Run 6b ablation (detection disabled)")
    p.add_argument("--both", action="store_true",
                   help="Run both variants side-by-side (default for ep_1_34)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    episodes = load_jsonl(args.episodes)
    gt_rows = load_jsonl(args.gt)

    obs = next((e for e in episodes if e["episode_id"] == args.episode), None)
    gt = next((g for g in gt_rows if g["episode_id"] == args.episode), None)
    if obs is None or gt is None:
        raise SystemExit(f"episode {args.episode!r} not found")

    print(f"\n{'='*72}")
    print(f"  PRE-TRACE CONTEXT — {args.episode}")
    print(f"{'='*72}")
    print(f"  failure_code      : {obs.get('failure_code')}")
    print(f"  failure_message   : {obs.get('failure_message')}")
    print(f"  failure_source    : {obs.get('failure_source')}")
    print(f"  amount_inr        : {obs.get('amount_inr')}")
    print(f"  sim_hour          : {obs.get('sim_hour'):.2f}")
    print(f"  country/network   : {obs.get('country')}/{obs.get('card_network')}")
    print(f"  issuer_bank_code  : {obs.get('issuer_bank_code')}")
    print(f"  risk_score_gateway: {obs.get('risk_score_gateway')}")
    print(f"  lifetime_value_inr: {obs.get('lifetime_value_inr')}")
    print(f"  --- GROUND TRUTH (hidden from pipeline) ---")
    print(f"  population        : {gt.get('population')}")
    print(f"  incident_id       : {gt.get('incident_id')}")
    print(f"  optimal_action    : {gt.get('optimal_action')}")
    print(f"  incident_multiplier: {gt.get('incident_multiplier')}")
    print()

    import random
    from autopilot.pipeline import Autopilot, AutopilotNoDetection

    run_both = args.both or (args.episode == "ep_1_34" and not args.no_detection)

    state = episode_state_from_observed(obs)

    if run_both or not args.no_detection:
        ap = Autopilot(
            detection_enabled=True,
            ground_truth_rows=gt_rows,
            rng=random.Random(args.seed),
        )
        trace_on = ap.run_episode(obs, state, gt)
        print_trace(trace_on, variant_label="AUTOPILOT (6) — detection ON")

    if run_both or args.no_detection:
        ap6b = AutopilotNoDetection(
            ground_truth_rows=gt_rows,
            rng=random.Random(args.seed),
        )
        state6b = episode_state_from_observed(obs)
        trace_off = ap6b.run_episode(obs, state6b, gt)
        print_trace(trace_off, variant_label="AUTOPILOT-NO-DETECTION (6b) — detection OFF")

    if run_both:
        print(f"  DIVERGENCE SUMMARY")
        print(f"  {'':28s}  Detection ON (6)        Detection OFF (6b)")
        print(f"  {'final_action':28s}  {trace_on.final_action:22s}  {trace_off.final_action}")
        print(f"  {'success':28s}  {str(trace_on.success):22s}  {trace_off.success}")
        print(f"  {'n_actions':28s}  {trace_on.n_actions:<22d}  {trace_off.n_actions}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
