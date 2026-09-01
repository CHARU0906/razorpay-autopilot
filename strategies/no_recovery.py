"""No Recovery — always stop. The do-nothing floor (SPEC §5 #1)."""

from __future__ import annotations

from strategies.common import params_for


class NoRecovery:
    name = "no_recovery"

    def decide(self, observed: dict, episode_state: dict) -> tuple[str, dict]:
        return "stop", params_for("stop", observed)
