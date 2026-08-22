"""Outcome Agent — Stage 5 of the Autopilot pipeline (SPEC §5).

On success: closes the episode.
On failure: feeds back into the Strategist for outcome-driven replanning.
  - Increments replan_count; enforces max_replan_attempts cap.
  - Never calls this process "learning" (SPEC P5).
"""

from __future__ import annotations

from dataclasses import dataclass

from autopilot.action_agent import ActionResult


@dataclass
class OutcomeResult:
    episode_id: str
    action_id: str
    success: bool
    terminal: bool          # True when episode is done (success or cap hit or stop)
    replan: bool            # True when we should loop back to Strategist
    updated_state: dict     # mutated episode_state to pass to next Strategist call
    log_line: str


def process(
    action_result: ActionResult,
    observed: dict,
    episode_state: dict,
    *,
    max_replan: int = 3,
    max_actions: int = 6,
) -> OutcomeResult:
    eid = observed["episode_id"]
    action_id = action_result.action_id

    # Build updated episode state
    new_state = dict(episode_state)
    actions_taken = list(episode_state.get("actions_taken") or [])
    actions_taken.append({
        "action": action_id,
        "params": action_result.params,
        "outcome": "success" if action_result.success else "failure",
        "p_eff": action_result.p_eff,
    })
    new_state["actions_taken"] = actions_taken
    new_state["last_action"] = action_id
    new_state["last_outcome"] = "success" if action_result.success else "failure"
    new_state["attempt_index"] = int(episode_state.get("attempt_index") or 0) + 1

    # Count customer contacts
    visible = {"send_dunning_notification", "send_recovery_link",
               "request_reauth", "request_new_payment_method"}
    if action_id in visible:
        new_state["customer_contacts_sent"] = int(episode_state.get("customer_contacts_sent") or 0) + 1

    # Terminal conditions
    n_actions = len(actions_taken)
    replan_count = int(episode_state.get("replan_count") or 0)

    if action_result.success:
        log = (f"[{eid}] ✓ {action_id} SUCCEEDED "
               f"(p_eff={action_result.p_eff:.3f}, attempt={n_actions})")
        return OutcomeResult(
            episode_id=eid, action_id=action_id,
            success=True, terminal=True, replan=False,
            updated_state=new_state, log_line=log,
        )

    if action_id == "stop":
        log = f"[{eid}] ■ stop — episode closed without recovery"
        return OutcomeResult(
            episode_id=eid, action_id=action_id,
            success=False, terminal=True, replan=False,
            updated_state=new_state, log_line=log,
        )

    if n_actions >= max_actions:
        log = (f"[{eid}] ✗ {action_id} failed — action cap {max_actions} reached, "
               f"episode closed")
        return OutcomeResult(
            episode_id=eid, action_id=action_id,
            success=False, terminal=True, replan=False,
            updated_state=new_state, log_line=log,
        )

    if replan_count >= max_replan:
        log = (f"[{eid}] ✗ {action_id} failed — replan cap {max_replan} reached; "
               f"episode will escalate on next policy check")
        # Don't increment replan here; policy engine enforces the cap
        return OutcomeResult(
            episode_id=eid, action_id=action_id,
            success=False, terminal=False, replan=True,
            updated_state=new_state, log_line=log,
        )

    # Still within caps — request a replan
    new_state["replan_count"] = replan_count + 1
    log = (f"[{eid}] ✗ {action_id} failed "
           f"(p_eff={action_result.p_eff:.3f}, attempt={n_actions}) — "
           f"outcome-driven replanning (replan #{replan_count + 1})")
    return OutcomeResult(
        episode_id=eid, action_id=action_id,
        success=False, terminal=False, replan=True,
        updated_state=new_state, log_line=log,
    )
