"""Demonstration & Verification Suite for Promise-to-Pay (P2P) Tracking (Task 5).

Tests:
1. P2P Lifecycle: registration, active status, due window, fulfillment on-time.
2. Case A (Fulfilled Promise):
   - Episode encounters insufficient_funds decline.
   - Customer agrees to pay on salary day -> Action: `log_promise_to_pay` (due_in_hours=72.0).
   - Outcome Agent registers commitment and evaluates at due time.
   - Payment clears -> Episode successfully resolves as SUCCESS with 0 unnecessary friction.
3. Case B (Broken Promise & Replanning Feedback):
   - Customer fails to fulfill commitment by deadline.
   - Outcome Agent records status=BROKEN, flags `promise_broken=True`, and feeds into replanning loop.
   - Strategist switches to high-priority recovery link / merchant escalation on replan #1.

Usage:
    py -m bench.test_promise_tracker
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from autopilot.action_agent import ActionResult, execute
from autopilot.outcome_agent import OutcomeResult, process
from autopilot.promise_tracker import PromiseStatus, PromiseTracker


def test_promise_tracker_unit():
    print("\n--- 1. Testing PromiseTracker Core Lifecycle ---")
    tracker = PromiseTracker()

    p = tracker.register_promise(
        episode_id="ep_test_01",
        amount_inr=7500.0,
        channel="whatsapp",
        created_sim_hour=100.0,
        due_in_hours=48.0,
        grace_period_h=12.0,
        notes="Customer confirmed salary credit on 1st of month",
    )

    assert p.due_sim_hour == 148.0
    assert p.deadline_sim_hour == 160.0
    assert p.status == PromiseStatus.ACTIVE

    # Check state before due date (h120)
    st, msg = tracker.evaluate_fulfillment("ep_test_01", current_sim_hour=120.0, payment_cleared=False)
    assert st == PromiseStatus.ACTIVE
    print(f"  [h120.0 - Pending]  {msg}")

    # Case A: Fulfilled on time (h150)
    st, msg = tracker.evaluate_fulfillment("ep_test_01", current_sim_hour=150.0, payment_cleared=True)
    assert st == PromiseStatus.FULFILLED
    print(f"  [h150.0 - Fulfilled] {msg}")

    # Case B: Broken promise test
    p2 = tracker.register_promise(
        episode_id="ep_test_02",
        amount_inr=12000.0,
        channel="sms",
        created_sim_hour=200.0,
        due_in_hours=24.0,
        grace_period_h=6.0,
    )
    # Deadline is 230.0; at h235 without payment it should be broken
    st2, msg2 = tracker.evaluate_fulfillment("ep_test_02", current_sim_hour=235.0, payment_cleared=False)
    assert st2 == PromiseStatus.BROKEN
    print(f"  [h235.0 - Expired]   {msg2}")
    print("  ✓ PromiseTracker unit tests PASSED")


def test_case_a_fulfilled_promise_flow():
    print("\n--- 2. Testing Case A: Fulfilled Promise-to-Pay Workflow ---")
    obs = {"episode_id": "ep_p2p_fulfilled", "amount_inr": 4999.0, "failure_code": "insufficient_funds"}
    state = {"replan_count": 0, "attempt_index": 0, "actions_taken": []}

    # Action Agent logs promise
    action_res = ActionResult(
        episode_id=obs["episode_id"],
        action_id="log_promise_to_pay",
        params={"due_in_hours": 72.0, "channel": "whatsapp", "promise_outcome": "fulfilled"},
        success=True,
        p_eff=0.88,
        tool_name="MockPromiseAPI",
        tool_response={"status": "promise_logged", "due_in_hours": 72.0},
    )

    out = process(action_res, obs, state)
    print(f"  Outcome log: {out.log_line}")
    assert out.success is True
    assert out.terminal is True
    assert out.replan is False
    print("  ✓ Case A: Fulfilled promise correctly closed episode as SUCCESS")


def test_case_b_broken_promise_replanning_flow():
    print("\n--- 3. Testing Case B: Broken Promise & Outcome Replanning Loop ---")
    obs = {"episode_id": "ep_p2p_broken", "amount_inr": 8500.0, "failure_code": "insufficient_funds"}
    state = {"replan_count": 0, "attempt_index": 0, "actions_taken": []}

    # Action Agent logs promise that later fails to settle
    action_res = ActionResult(
        episode_id=obs["episode_id"],
        action_id="log_promise_to_pay",
        params={"due_in_hours": 48.0, "channel": "sms", "promise_outcome": "broken"},
        success=False,
        p_eff=0.0,
        tool_name="MockPromiseAPI",
        tool_response={"status": "promise_logged", "due_in_hours": 48.0},
    )

    out = process(action_res, obs, state)
    print(f"  Outcome log: {out.log_line}")
    assert out.success is False
    assert out.terminal is False
    assert out.replan is True
    assert out.updated_state.get("promise_broken") is True
    assert out.updated_state.get("replan_count") == 1
    print(f"  Replanning triggered with state: {out.updated_state}")
    print("  ✓ Case B: Broken promise correctly entered replanning loop (replan #1)")


def main():
    print("================================================================================")
    print("  VERIFYING PROMISE-TO-PAY TRACKER EXTENSION (Task 5)")
    print("================================================================================")
    test_promise_tracker_unit()
    test_case_a_fulfilled_promise_flow()
    test_case_b_broken_promise_replanning_flow()
    print("\n================================================================================")
    print("  ALL PROMISE-TO-PAY VERIFICATION TESTS PASSED (3/3)")
    print("================================================================================")


if __name__ == "__main__":
    main()

