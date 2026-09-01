"""Phase 2 first-action distributions on the frozen seed-1 set. Not the Phase 4 harness."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from strategies.common import ACTIONS, SILENT_RETRIES, episode_state_from_observed
from strategies.fixed_retry import FixedRetry
from strategies.learned_smart_retry import LearnedSmartRetry
from strategies.no_recovery import NoRecovery
from strategies.oracle import Oracle
from strategies.rule_based import RuleBased
from strategies.smart_dunning import SmartDunning

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

STRATEGIES = {
    "no_recovery": NoRecovery,
    "fixed_retry": FixedRetry,
    "rule_based": RuleBased,
    "learned_smart_retry": LearnedSmartRetry,
    "smart_dunning": SmartDunning,
    "oracle": Oracle,
}


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def get_strategy(name: str, gt_rows: list[dict] | None = None):
    if name not in STRATEGIES:
        raise SystemExit(f"unknown strategy {name!r}. known: {sorted(STRATEGIES)}")
    cls = STRATEGIES[name]
    if name == "oracle":
        return cls(gt_rows)
    return cls()


def run_first_actions(name: str, episodes: list[dict], gt_rows: list[dict]) -> list[dict]:
    strat = get_strategy(name, gt_rows)
    gt_by_id = {g["episode_id"]: g for g in gt_rows}
    rows = []
    for obs in episodes:
        state = episode_state_from_observed(obs)
        action, params = strat.decide(obs, state)
        if action not in ACTIONS:
            raise RuntimeError(f"{name} returned illegal action {action!r} on {obs['episode_id']}")
        g = gt_by_id[obs["episode_id"]]
        rows.append(
            {
                "episode_id": obs["episode_id"],
                "action": action,
                "params": params,
                "population": g["population"],
                "true_failure_class": g["true_failure_class"],
                "optimal_action": g["optimal_action"],
            }
        )
    return rows


def print_report(name: str, rows: list[dict], *, checks: list[str]) -> int:
    n = len(rows)
    overall = Counter(r["action"] for r in rows)
    print(f"\n=== {name} — first action on seed-1 (n={n}) ===")
    for action, c in overall.most_common():
        print(f"  {action:28s} {c:5d}  {100.0 * c / n:6.2f}%")

    used = [a for a in ACTIONS if overall[a]]
    print("\nBy population:")
    print("  " + f"{'population':22s}" + "".join(f"{a:>22s}" for a in used))
    pops = [
        "insufficient_funds",
        "transient",
        "non_recoverable",
        "auth_required",
        "expired_card",
        "regional_degradation",
        "ambiguous",
    ]
    for pop in pops:
        subset = [r for r in rows if r["population"] == pop]
        cnt = Counter(r["action"] for r in subset)
        cells = "".join(f"{cnt[a]:22d}" for a in used)
        print(f"  {pop:22s}{cells}")

    rc = 0
    if "no_retry_non_recoverable" in checks:
        n_nr = sum(1 for r in rows if r["population"] == "non_recoverable")
        bad = [
            r
            for r in rows
            if r["population"] == "non_recoverable" and r["action"] in SILENT_RETRIES
        ]
        print(
            f"\nCheck: Rule-Based never retries non_recoverable: "
            f"{len(bad)} violations / {n_nr} episodes"
        )
        if bad:
            print("  examples:", [b["episode_id"] + ":" + b["action"] for b in bad[:8]])
            rc = 1
    if "oracle_matches_gt" in checks:
        # Post Phase-3 amendment: Oracle applies COMPLIANCE_ESCALATE_CODES override.
        # Fraud episodes (stolen_or_lost_card, risk_blocked) are expected to deviate
        # from gt.optimal_action — that's the correction, not a bug.
        from strategies.oracle import COMPLIANCE_ESCALATE_CODES
        compliance_ids = {
            obs["episode_id"]
            for obs in load_jsonl(DATA / "episodes.jsonl")
            if obs.get("failure_code") in COMPLIANCE_ESCALATE_CODES
        }
        # Exclude compliance-override episodes from the match check
        check_rows = [r for r in rows if r["episode_id"] not in compliance_ids]
        mismatch = [r for r in check_rows if r["action"] != r["optimal_action"]]
        n_compliance = len(rows) - len(check_rows)
        print(f"\nCheck: Oracle == ground_truth.optimal_action "
              f"(excluding {n_compliance} compliance-override episodes): "
              f"{len(check_rows) - len(mismatch)}/{len(check_rows)}")
        if mismatch:
            print("  examples:", mismatch[:8])
            rc = 1
        # Also report compliance overrides separately
        compliance_rows = [r for r in rows if r["episode_id"] in compliance_ids]
        esc_cnt = sum(1 for r in compliance_rows if r["action"] == "escalate_to_merchant")
        print(f"  Compliance-override episodes: {n_compliance} → "
              f"{esc_cnt} escalated (expected: {n_compliance})")
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", required=True)
    p.add_argument("--episodes", type=Path, default=DATA / "episodes.jsonl")
    p.add_argument("--gt", type=Path, default=DATA / "ground_truth.jsonl")
    args = p.parse_args(argv)
    episodes = load_jsonl(args.episodes)
    gt_rows = load_jsonl(args.gt)
    if len(episodes) != len(gt_rows):
        raise SystemExit("episodes/gt length mismatch")
    rows = run_first_actions(args.strategy, episodes, gt_rows)
    checks = []
    if args.strategy == "rule_based":
        checks.append("no_retry_non_recoverable")
    if args.strategy == "oracle":
        checks.append("oracle_matches_gt")
    return print_report(args.strategy, rows, checks=checks)


if __name__ == "__main__":
    raise SystemExit(main())
