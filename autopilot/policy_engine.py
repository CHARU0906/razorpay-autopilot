"""Policy Engine — Stage 3 of the Autopilot pipeline (SPEC §5).

Applies autonomy-tier thresholds from policy.yaml.
Returns one of: "automatic", "requires-approval", "requires-human".
Never reads ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML required") from exc

ROOT = Path(__file__).resolve().parents[1]

_POLICY: dict | None = None


def _load_policy(*, _reload: bool = False) -> dict:
    global _POLICY
    if _POLICY is None or _reload:
        with (ROOT / "policy.yaml").open(encoding="utf-8") as f:
            _POLICY = yaml.safe_load(f)
    return _POLICY


@dataclass
class PolicyResult:
    tier: str                   # "automatic" | "requires-approval" | "requires-human"
    action_id: str              # possibly overridden to "escalate_to_merchant"
    params: dict
    reason: str


def apply(
    action_id: str,
    params: dict,
    observed: dict,
    episode_state: dict,
    *,
    inferred_class: str,
) -> PolicyResult:
    policy = _load_policy()
    auto = policy["autonomy"]

    amount_inr = float(observed.get("amount_inr") or 0.0)
    risk_score = float(observed.get("risk_score_gateway") or 0.0)
    failure_code = observed.get("failure_code") or ""
    replan_count = int(episode_state.get("replan_count") or 0)

    # --- always-human: certain failure codes or action types ---
    if failure_code in auto.get("human_failure_codes", []):
        return PolicyResult(
            tier="requires-human",
            action_id="escalate_to_merchant",
            params={"queue": "recovery_ops", "note": f"policy: human_failure_code={failure_code}"},
            reason=f"Failure code '{failure_code}' is on always-human list",
        )

    if action_id in auto.get("always_human", []):
        # min_amount_for_escalate guard: below threshold, escalate is EU-negative
        # for non_recoverable-like episodes (90 INR floor vs low base_p).
        # Exempt: policy-engine-generated escalations from hard-stop failure codes
        # (handled above) — those are mandatory regardless of amount.
        min_amt = float(auto.get("min_amount_for_escalate_inr", 0.0))
        if action_id == "escalate_to_merchant" and amount_inr < min_amt:
            return PolicyResult(
                tier="automatic",
                action_id="stop",
                params={},
                reason=(
                    f"escalate_to_merchant suppressed: amount_inr {amount_inr:.0f} "
                    f"< min_amount_for_escalate {min_amt:.0f} INR; "
                    f"90 INR cost floor cannot clear break-even at this amount"
                ),
            )
        return PolicyResult(
            tier="requires-human",
            action_id=action_id,
            params=params,
            reason=f"Action '{action_id}' always requires human routing",
        )

    # --- max re-plan exceeded → escalate ---
    if replan_count >= int(auto.get("max_replan_attempts", 3)):
        return PolicyResult(
            tier="requires-human",
            action_id="escalate_to_merchant",
            params={"queue": "recovery_ops", "note": "max_replan_attempts reached"},
            reason=f"Re-plan count {replan_count} ≥ max {auto['max_replan_attempts']}",
        )

    # --- high risk score → escalate ---
    if risk_score >= float(auto.get("high_risk_score", 0.85)):
        # Only escalate for customer-visible actions — silent retries are still automatic
        from strategies.common import SILENT_RETRIES
        if action_id not in SILENT_RETRIES and action_id != "stop":
            return PolicyResult(
                tier="requires-human",
                action_id="escalate_to_merchant",
                params={"queue": "recovery_ops", "note": f"risk_score={risk_score:.3f}"},
                reason=f"Risk score {risk_score:.3f} ≥ threshold {auto['high_risk_score']} with customer-visible action",
            )

    # --- high value + customer-visible → requires-approval ---
    if amount_inr > float(auto.get("high_value_inr", 15000.0)):
        if action_id in auto.get("approval_if_high_value", []):
            return PolicyResult(
                tier="requires-approval",
                action_id=action_id,
                params=params,
                reason=f"amount_inr {amount_inr:.0f} > {auto['high_value_inr']:.0f} with customer-visible action",
            )

    # --- automatic ---
    return PolicyResult(
        tier="automatic",
        action_id=action_id,
        params=params,
        reason="Within automatic autonomy thresholds",
    )
