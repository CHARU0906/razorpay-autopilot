"""First-action distribution for Autopilot (6) and Autopilot-no-detection (6b).

Runs decide() only (no outcome sampling) — matches Phase 2 bench comparison style.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from strategies.common import ACTIONS, episode_state_from_observed
from autopilot.pipeline import Autopilot, AutopilotNoDetection

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

POPULATIONS = [
    "insufficient_funds", "transient", "non_recoverable", "auth_required",
    "expired_card", "regional_degradation", "ambiguous",
]


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def run_dist(name: str, strategy, episodes: list[dict], gt_by_id: dict) -> list[dict]:
    rows = []
    for obs in episodes:
        state = episode_state_from_observed(obs)
        action, params = strategy.decide(obs, state)
        if action not in ACTIONS:
            raise RuntimeError(f"{name} returned illegal action {action!r} on {obs['episode_id']}")
        gt = gt_by_id[obs["episode_id"]]
        rows.append({
            "episode_id": obs["episode_id"],
            "action": action,
            "population": gt["population"],
            "optimal_action": gt["optimal_action"],
        })
    return rows


def print_dist(name: str, rows: list[dict]) -> None:
    n = len(rows)
    overall = Counter(r["action"] for r in rows)
    print(f"\n=== {name} — first action on seed-1 (n={n}) ===")
    for action, c in overall.most_common():
        print(f"  {action:28s} {c:5d}  {100.0 * c / n:6.2f}%")

    used = [a for a in ACTIONS if overall[a]]
    print("\nBy population:")
    header = f"  {'population':22s}" + "".join(f"{a:>24s}" for a in used)
    print(header)
    for pop in POPULATIONS:
        subset = [r for r in rows if r["population"] == pop]
        cnt = Counter(r["action"] for r in subset)
        cells = "".join(f"{cnt[a]:24d}" for a in used)
        print(f"  {pop:22s}{cells}")


def main() -> None:
    episodes = load_jsonl(DATA / "episodes.jsonl")
    gt_rows = load_jsonl(DATA / "ground_truth.jsonl")
    gt_by_id = {g["episode_id"]: g for g in gt_rows}

    ap = Autopilot(detection_enabled=True, ground_truth_rows=gt_rows)
    ap6b = AutopilotNoDetection(ground_truth_rows=gt_rows)

    rows_on = run_dist("autopilot", ap, episodes, gt_by_id)
    rows_off = run_dist("autopilot_no_detection", ap6b, episodes, gt_by_id)

    print_dist("Autopilot (6) — detection ON", rows_on)
    print_dist("Autopilot-no-detection (6b) — detection OFF", rows_off)

    # Side-by-side delta for regional_degradation (where divergence eventually matters)
    print("\n=== DELTA: regional_degradation episodes only ===")
    on_rd = Counter(r["action"] for r in rows_on if r["population"] == "regional_degradation")
    off_rd = Counter(r["action"] for r in rows_off if r["population"] == "regional_degradation")
    all_rd_actions = sorted(set(on_rd) | set(off_rd))
    print(f"  {'action':28s}  {'det-ON':>10s}  {'det-OFF':>10s}  {'delta':>8s}")
    for a in all_rd_actions:
        delta = on_rd[a] - off_rd[a]
        print(f"  {a:28s}  {on_rd[a]:10d}  {off_rd[a]:10d}  {delta:+8d}")


if __name__ == "__main__":
    main()
