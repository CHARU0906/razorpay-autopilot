"""Fixed Retry — retry_1h → retry_6h → retry_24h → retry_72h → stop, ignoring failure type."""

from __future__ import annotations

from strategies.common import params_for, taken_action_ids

SEQUENCE = ["retry_1h", "retry_6h", "retry_24h", "retry_72h", "stop"]


class FixedRetry:
    name = "fixed_retry"

    def decide(self, observed: dict, episode_state: dict) -> tuple[str, dict]:
        taken = taken_action_ids(episode_state)
        step = sum(1 for a in taken if a in SEQUENCE)
        if step >= len(SEQUENCE):
            action = "stop"
        else:
            action = SEQUENCE[step]
        return action, params_for(action, observed)
