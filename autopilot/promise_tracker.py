"""Promise-to-Pay (P2P) Tracking Subsystem (Task 5 Breadth Extension).

Enables customer-facing promise logging and lifecycle tracking:
1. Action: `log_promise_to_pay` schedules a commitment timestamp (e.g. aligned with salary/billing date).
2. Action Agent calls MockPromiseAPI to record the promise.
3. Outcome Agent tracks status at due date:
   - Case A (Fulfilled): Customer initiates payment by due timestamp -> episode closes as SUCCESS.
   - Case B (Broken): Promise window expires without payment -> feeds back into replanning loop with
     `promise_broken=True` for high-urgency recovery link / escalation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PromiseStatus(str, Enum):
    ACTIVE = "active"
    FULFILLED = "fulfilled"
    BROKEN = "broken"
    CANCELLED = "cancelled"


@dataclass
class PromiseToPay:
    episode_id: str
    amount_inr: float
    channel: str                    # "whatsapp" | "sms" | "in_app" | "ivr"
    created_sim_hour: float
    due_sim_hour: float             # scheduled payment commitment hour
    grace_period_h: float = 12.0    # buffer before marking broken
    status: PromiseStatus = PromiseStatus.ACTIVE
    fulfillment_sim_hour: Optional[float] = None
    notes: str = ""

    @property
    def deadline_sim_hour(self) -> float:
        return self.due_sim_hour + self.grace_period_h

    def is_due(self, current_sim_hour: float) -> bool:
        return current_sim_hour >= self.due_sim_hour

    def is_expired(self, current_sim_hour: float) -> bool:
        return current_sim_hour > self.deadline_sim_hour


class PromiseTracker:
    """In-memory tracker for active and historical Promise-to-Pay commitments."""

    def __init__(self):
        self._promises: dict[str, list[PromiseToPay]] = {}

    def register_promise(
        self,
        episode_id: str,
        amount_inr: float,
        channel: str,
        created_sim_hour: float,
        due_in_hours: float,
        grace_period_h: float = 12.0,
        notes: str = "",
    ) -> PromiseToPay:
        p = PromiseToPay(
            episode_id=episode_id,
            amount_inr=amount_inr,
            channel=channel,
            created_sim_hour=created_sim_hour,
            due_sim_hour=created_sim_hour + due_in_hours,
            grace_period_h=grace_period_h,
            status=PromiseStatus.ACTIVE,
            notes=notes,
        )
        if episode_id not in self._promises:
            self._promises[episode_id] = []
        self._promises[episode_id].append(p)
        return p

    def get_latest_promise(self, episode_id: str) -> Optional[PromiseToPay]:
        proms = self._promises.get(episode_id, [])
        return proms[-1] if proms else None

    def evaluate_fulfillment(
        self,
        episode_id: str,
        current_sim_hour: float,
        payment_cleared: bool,
    ) -> tuple[PromiseStatus, str]:
        """Evaluate promise state at current simulation timestamp."""
        p = self.get_latest_promise(episode_id)
        if p is None:
            return PromiseStatus.CANCELLED, "No active promise found"

        if p.status != PromiseStatus.ACTIVE:
            return p.status, f"Promise already marked {p.status.value}"

        if payment_cleared:
            p.status = PromiseStatus.FULFILLED
            p.fulfillment_sim_hour = current_sim_hour
            return PromiseStatus.FULFILLED, f"Promise fulfilled on time at h{current_sim_hour:.1f}"

        if p.is_expired(current_sim_hour):
            p.status = PromiseStatus.BROKEN
            return PromiseStatus.BROKEN, (
                f"Promise broken: deadline h{p.deadline_sim_hour:.1f} passed without payment "
                f"(current_h={current_sim_hour:.1f})"
            )

        return PromiseStatus.ACTIVE, f"Promise active, pending due date h{p.due_sim_hour:.1f}"

