"""Fit / load the shared retry-delay classifier (train seeds only)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import joblib
from sklearn.linear_model import LogisticRegression

from strategies.common import RETRY_DELAYS
from strategies.featurize import CATEGORICAL, NUMERIC, row_to_raw

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "data" / "models" / "retry_delay_logreg.joblib"
LABELS = RETRY_DELAYS + ["stop"]


def label_from_ground_truth(gt: dict) -> str:
    """Best delay among the retry-timing subset, or stop if none are viable."""
    probs = gt["action_success_probabilities"]
    best_a = "stop"
    best_p = 0.08
    for a in RETRY_DELAYS:
        p = float(probs.get(a) or 0.0)
        if p > best_p:
            best_p = p
            best_a = a
    return best_a


def encode_rows(raw_rows: list[dict], vocab: dict[str, list[str]] | None = None):
    import numpy as np

    if vocab is None:
        vocab = {col: sorted({str(r[col]) for r in raw_rows}) for col in CATEGORICAL}
    parts = []
    for col in CATEGORICAL:
        cats = vocab[col]
        index = {c: i for i, c in enumerate(cats)}
        mat = np.zeros((len(raw_rows), len(cats)), dtype=float)
        for i, r in enumerate(raw_rows):
            j = index.get(str(r[col]))
            if j is not None:
                mat[i, j] = 1.0
        parts.append(mat)
    num = np.array([[float(r[c]) for c in NUMERIC] for r in raw_rows], dtype=float)
    parts.append(num)
    X = np.concatenate(parts, axis=1)
    return X, vocab


def train_and_save(episodes: list[dict], gt_rows: list[dict], path: Path = MODEL_PATH) -> dict:
    gt_by = {g["episode_id"]: g for g in gt_rows}
    raw, y = [], []
    for obs in episodes:
        g = gt_by[obs["episode_id"]]
        state = {
            "attempt_index": obs.get("attempt_index", 0),
            "hours_since_first_failure": obs.get("hours_since_first_failure", 0.0),
        }
        raw.append(row_to_raw(obs, state))
        y.append(label_from_ground_truth(g))
    X, vocab = encode_rows(raw)
    clf = LogisticRegression(max_iter=800, solver="lbfgs")
    clf.fit(X, y)
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {"clf": clf, "vocab": vocab, "labels": list(clf.classes_)}
    joblib.dump(bundle, path)
    meta = {
        "n": len(y),
        "label_counts": dict(Counter(y)),
        "classes": list(clf.classes_),
        "train_note": "Fit on training-band seeds only. Labels = argmax retry delay in GT p(a).",
    }
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return {"n": len(y), "path": str(path), "classes": list(clf.classes_), "label_counts": meta["label_counts"]}


def load_bundle(path: Path = MODEL_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"retry model missing at {path}. Train on a train-band seed first "
            "(python -m strategies.train_retry_model --seed 1000)."
        )
    return joblib.load(path)


def predict_retry_action(observed: dict, episode_state: dict, bundle: dict) -> str:
    raw = [row_to_raw(observed, episode_state)]
    X, _ = encode_rows(raw, vocab=bundle["vocab"])
    pred = bundle["clf"].predict(X)[0]
    if pred not in LABELS:
        return "retry_24h"
    return str(pred)
