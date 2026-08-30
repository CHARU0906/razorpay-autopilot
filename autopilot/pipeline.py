"""Autopilot pipeline orchestrator — wires all five stages (SPEC §5).

Also exposes the 6b ablation: same pipeline, degradation detection disabled.
The ablation is a config flag, not a separate code path.

decide() satisfies the identical Strategy interface:
    def decide(observed, episode_state) -> (action_id, params)

For full traces (bench / demo), use run_episode() which returns the complete log.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from autopilot.investigator import InvestigatorResult, investigate
from autopilot.strategist import StrategistResult, score_all_actions
from autopilot.policy_engine import PolicyResult, apply as policy_apply
from autopilot.action_agent import ActionResult, execute as action_execute
from autopilot.outcome_agent import OutcomeResult, process as outcome_process
from strategies.common import params_for, MANDATORY_ESCALATION_CODES
from strategies.retry_model import load_bundle
from detect.degradation import DegradationDetector


@dataclass
class StageLog:
    stage: str
    summary: str
    detail: dict = field(default_factory=dict)


@dataclass
class EpisodeTrace:
    episode_id: str
    success: bool
    n_actions: int
    stages: list[StageLog] = field(default_factory=list)
    final_action: str = "stop"
    replan_count: int = 0
    # True when every escalation in this episode was compliance-driven
    # (mandatory_escalation_codes path), not EU-optimising.
    # Used by Phase 4 scorer for IRPI Option 2 denominator exclusion.
    mandatory_escalation_count: int = 0


class Autopilot:
    """
    Full Autopilot (6) — degradation detector enabled.
    For the 6b ablation, pass detection_enabled=False.
    """
    name = "autopilot"

    def __init__(
        self,
        *,
        detection_enabled: bool = True,
        llm_enabled: bool = False,
        retry_bundle=None,
        ground_truth_rows: list[dict] | None = None,
        rng: Optional[random.Random] = None,
        detector: Optional[DegradationDetector] = None,
    ):
        self.detection_enabled = detection_enabled
        self.llm_enabled = llm_enabled
        self._bundle = retry_bundle if retry_bundle is not None else load_bundle()
        self._gt_by_id: dict[str, dict] = (
            {r["episode_id"]: r for r in ground_truth_rows}
            if ground_truth_rows else {}
        )
        self._rng = rng or random.Random()
        # Phase 5: shared detector instance (None = detection disabled / 6b ablation)
        self._detector: Optional[DegradationDetector] = (
            detector if detection_enabled else None
        )
        if not detection_enabled:
            self.name = "autopilot_no_detection"

    # ------------------------------------------------------------------
    # Strategy interface (Phase 4 harness calls this)
    # ------------------------------------------------------------------

    def decide(self, observed: dict, episode_state: dict) -> tuple[str, dict]:
        """First-action decision only (no execution, no ground truth access)."""
        inv = investigate(observed, episode_state, llm_enabled=self.llm_enabled)
        # Phase 5: enrich with live detector state before Strategist sees it
        if self._detector is not None:
            self._detector.enrich(inv, observed)
        incident_detected = inv.incident_active if self.detection_enabled else False
        strat = score_all_actions(
            observed, episode_state,
            inferred_class=inv.inferred_class,
            incident_detected=incident_detected,
            retry_bundle=self._bundle,
        )
        pol = policy_apply(
            strat.recommended_action,
            strat.recommended_params,
            observed, episode_state,
            inferred_class=inv.inferred_class,
        )
        return pol.action_id, pol.params

    def is_mandatory_escalation(self, observed: dict) -> bool:
        """True if this episode's failure_code forces escalation regardless of EU.
        Used by Phase 4 scorer for IRPI Option 2 denominator exclusion.
        """
        return (observed.get("failure_code") or "") in MANDATORY_ESCALATION_CODES

    # ------------------------------------------------------------------
    # Full episode runner (Phase 3 trace / Phase 4 bench)
    # ------------------------------------------------------------------

    def run_episode(
        self,
        observed: dict,
        episode_state: dict,
        ground_truth: dict | None = None,
    ) -> EpisodeTrace:
        """
        Run a full episode through the pipeline with outcome sampling.
        ground_truth is used only by the Action Agent.
        """
        if ground_truth is None:
            ground_truth = self._gt_by_id.get(observed["episode_id"], {})

        trace = EpisodeTrace(episode_id=observed["episode_id"], success=False, n_actions=0)
        state = dict(episode_state)
        obs = dict(observed)

        max_actions = 6
        max_replan = 3

        while True:
            # Stage 1 — Investigator
            inv: InvestigatorResult = investigate(obs, state, llm_enabled=self.llm_enabled)
            # Phase 5: enrich with live detector state
            if self._detector is not None:
                self._detector.enrich(inv, obs)
            incident_detected = inv.incident_active if self.detection_enabled else False
            
            # Format multi-line causal reasoning summary
            inv_summary_lines = [
                f"inferred_class={inv.inferred_class} (confidence={inv.confidence:.2f}, observability={inv.observability})",
                f"Diagnostic Summary: {inv.diagnostic_summary}",
                "Causal Chain:",
            ]
            for step_txt in inv.causal_chain:
                inv_summary_lines.append(f"  → {step_txt}")
            if inv.flags:
                inv_summary_lines.append(f"Flags: {inv.flags}")
            if inv.llm_used:
                inv_summary_lines.append(f"LLM Reasoning: {inv.llm_reasoning}")

            trace.stages.append(StageLog(
                stage="Investigator",
                summary="\n".join(inv_summary_lines),
                detail={
                    "inferred_class": inv.inferred_class,
                    "observability": inv.observability,
                    "confidence": inv.confidence,
                    "flags": inv.flags,
                    "incident_detected": incident_detected,
                    "incident_id": inv.incident_id,
                    "causal_chain": inv.causal_chain,
                    "diagnostic_summary": inv.diagnostic_summary,
                    "eliminated_hypotheses": inv.eliminated_hypotheses,
                    "action_space_constraints": inv.action_space_constraints,
                },
            ))

            # Stage 2 — Strategist
            strat: StrategistResult = score_all_actions(
                obs, state,
                inferred_class=inv.inferred_class,
                incident_detected=incident_detected,
                retry_bundle=self._bundle,
            )
            top3 = strat.scores[:3]
            trace.stages.append(StageLog(
                stage="Strategist",
                summary=strat.reasoning,
                detail={"recommended_action": strat.recommended_action,
                        "top3": [(s.action_id, s.expected_utility) for s in top3]},
            ))

            # Stage 3 — Policy Engine
            pol: PolicyResult = policy_apply(
                strat.recommended_action,
                strat.recommended_params,
                obs, state,
                inferred_class=inv.inferred_class,
            )
            trace.stages.append(StageLog(
                stage="PolicyEngine",
                summary=(
                    f"tier={pol.tier}, action={pol.action_id}, reason={pol.reason}"
                ),
                detail={"tier": pol.tier, "action_id": pol.action_id,
                        "reason": pol.reason},
            ))

            # Stage 4 — Action Agent
            act: ActionResult = action_execute(
                pol.action_id, pol.params, obs, state, ground_truth, rng=self._rng
            )
            trace.stages.append(StageLog(
                stage="ActionAgent",
                summary=(
                    f"tool={act.tool_name}, action={act.action_id}, "
                    f"p_eff={act.p_eff:.4f}, outcome={'SUCCESS' if act.success else 'FAILURE'}"
                ),
                detail={"action_id": act.action_id, "p_eff": act.p_eff,
                        "success": act.success, "tool_response": act.tool_response},
            ))

            # Stage 5 — Outcome Agent
            out: OutcomeResult = outcome_process(
                act, obs, state,
                max_replan=max_replan,
                max_actions=max_actions,
            )
            trace.stages.append(StageLog(
                stage="OutcomeAgent",
                summary=out.log_line,
                detail={"terminal": out.terminal, "replan": out.replan,
                        "replan_count": out.updated_state.get("replan_count", 0)},
            ))

            state = out.updated_state
            trace.n_actions += 1
            trace.final_action = pol.action_id
            trace.replan_count = int(state.get("replan_count") or 0)

            # Track mandatory (compliance-driven) escalations for IRPI Option 2
            failure_code = obs.get("failure_code") or ""
            if (pol.action_id == "escalate_to_merchant"
                    and failure_code in MANDATORY_ESCALATION_CODES):
                trace.mandatory_escalation_count += 1

            # Phase 5: feed outcome into detector after each resolved action
            if self._detector is not None:
                self._detector.record_outcome(obs, act.success, float(obs.get("sim_hour") or 0.0))

            if out.terminal:
                trace.success = out.success
                break
            if not out.replan:
                break

        return trace


class AutopilotNoDetection(Autopilot):
    """6b ablation — same pipeline, degradation detection disabled (D1)."""
    name = "autopilot_no_detection"

    def __init__(self, **kwargs):
        kwargs["detection_enabled"] = False
        kwargs.pop("detector", None)  # 6b never gets a detector
        super().__init__(**kwargs)
