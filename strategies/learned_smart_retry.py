"""Learned Smart-Retry Baseline — retry timing only (SPEC §5 #4).

Uses the shared delay classifier fit on training seeds. Will not emit
customer-visible actions, hold_for_incident, or alternate routing.
"""

from __future__ import annotations

from strategies.common import RETRY_DELAYS, params_for, taken_action_ids
from strategies.retry_model import load_bundle, predict_retry_action

RETRY_CAP = 4


class LearnedSmartRetry:
    name = "learned_smart_retry"

    def __init__(self, bundle=None):
        self._bundle = bundle if bundle is not None else load_bundle()

    def decide(self, observed: dict, episode_state: dict) -> tuple[str, dict]:
        n_retry = sum(1 for a in taken_action_ids(episode_state) if a in RETRY_DELAYS)
        if n_retry >= RETRY_CAP:
            action = "stop"
        else:
            action = predict_retry_action(observed, episode_state, self._bundle)
        return action, params_for(action, observed)
