"""Train the retry-delay model on a training-band seed (D4). Never uses eval seeds 1–20."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sim.generate import assert_seed_bands, generate, load_config
from strategies.retry_model import train_and_save

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=1000)
    p.add_argument("--out", type=Path, default=ROOT / "data" / "train_seed1000")
    p.add_argument("--skip-generate", action="store_true", help="reuse existing jsonl in --out")
    args = p.parse_args(argv)
    cfg = load_config(ROOT / "sim_config.yaml")
    assert_seed_bands(args.seed, cfg)
    lo, hi = cfg["eval_seed_band"]
    if lo <= args.seed <= hi:
        raise SystemExit(f"D4 fairness: refuse to train on eval seed {args.seed}")
    ep_path = args.out / "episodes.jsonl"
    gt_path = args.out / "ground_truth.jsonl"
    if args.skip_generate and ep_path.exists() and gt_path.exists():
        print(f"reusing {args.out}")
    else:
        generate(cfg, args.seed, args.out)
    ep = _load(ep_path)
    gt = _load(gt_path)
    info = train_and_save(ep, gt)
    print("trained", json.dumps(info, sort_keys=True))
    return 0


def _load(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
