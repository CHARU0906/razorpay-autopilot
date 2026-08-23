"""Oracle [CEILING] — optimal EU-maximising action subject to the same compliance
constraints every other strategy operates under (SPEC §5, amended Phase 3).

Constraint applied here (mirrors Autopilot policy_engine.py human_failure_codes):
  stolen_or_lost_card, risk_blocked → escalate_to_merchant regardless of GT optimal_action.
  This matches what real fraud policy mandates; retrying a stolen card because GT
  assigns it a non-zero probability is not a valid ceiling.
"""

from __future__ import annotations

from strategies.common import params_for, MANDATORY_ESCALATION_CODES

# Alias for external imports that already reference this name directly.
COMPLIANCE_ESCALATE_CODES = MANDATORY_ESCALATION_CODES


class Oracle:
    name = "oracle"

    def __init__(self, ground_truth_rows: list[dict]):
        self._by_id = {row["episode_id"]: row for row in ground_truth_rows}

    def decide(self, observed: dict, episode_state: dict) -> tuple[str, dict]:
        gt = self._by_id[observed["episode_id"]]
        code = observed.get("failure_code") or ""

        # Compliance override: fraud codes must escalate, never retry.
        if code in COMPLIANCE_ESCALATE_CODES:
            action = "escalate_to_merchant"
        else:
            action = gt["optimal_action"]

        return action, params_for(action, observed)
