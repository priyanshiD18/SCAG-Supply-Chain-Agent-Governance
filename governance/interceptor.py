"""
Governance Interceptor

This is the heart of the project.

Every task dispatched on the A2A bus passes through here before it
reaches the intended agent. The interceptor:

  1. Asks the PolicyEngine for a verdict
  2. Logs the verdict to the AuditLog (always, regardless of outcome)
  3. Either lets the task through, flags it, or blocks it

The agents don't know this exists — which is the point. You can update
governance rules without touching any agent code.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from governance.audit_log import AuditLog
from governance.policy_engine import PolicyEngine, Verdict
from protocol.a2a import Task, TaskState

logger = logging.getLogger(__name__)


# Callback type: called when a task is escalated or blocked
AlertCallback = Callable[[str, Task, str], None]


class GovernanceInterceptor:
    """
    Sits between the A2ABus dispatcher and the receiving agent.
    Registered as the bus interceptor via bus.set_interceptor().
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        audit_log:     AuditLog,
        alert_callback: Optional[AlertCallback] = None,
    ):
        self.policy  = policy_engine
        self.log     = audit_log
        self.alert   = alert_callback
        self._escalations: List[dict] = []   # in-memory list for dashboard
        self._blocks:      List[dict] = []

    # ------------------------------------------------------------------
    # The main intercept method — registered with A2ABus
    # ------------------------------------------------------------------

    def intercept(self, task: Task) -> Task:
        verdict, reason = self.policy.evaluate(task.action, task.payload)

        # Always write to the audit log first
        self.log.record(
            task_id=task.task_id,
            sender=task.sender,
            recipient=task.recipient,
            action=task.action,
            verdict=verdict.value,
            reason=reason,
            payload=task.payload,
        )

        if verdict == Verdict.APPROVED:
            logger.debug(
                "[Interceptor] APPROVED | %s → %s | %s",
                task.sender, task.action, reason
            )
            return task

        if verdict == Verdict.ESCALATE:
            logger.warning(
                "[Interceptor] ESCALATE | %s → %s | %s",
                task.sender, task.action, reason
            )
            self._record_escalation(task, reason)
            if self.alert:
                self.alert("escalate", task, reason)
            # Task proceeds but the flag is recorded
            return task

        if verdict == Verdict.BLOCKED:
            logger.error(
                "[Interceptor] BLOCKED  | %s → %s | %s",
                task.sender, task.action, reason
            )
            self._record_block(task, reason)
            if self.alert:
                self.alert("block", task, reason)
            task.block(reason)
            return task

        # Shouldn't happen, but don't let unknown verdicts slip through
        task.block(f"Unknown governance verdict: {verdict}")
        return task

    # ------------------------------------------------------------------
    # In-memory tracking for the dashboard
    # ------------------------------------------------------------------

    def _record_escalation(self, task: Task, reason: str):
        self._escalations.append({
            "task_id":  task.task_id,
            "sender":   task.sender,
            "action":   task.action,
            "payload":  task.payload,
            "reason":   reason,
            "resolved": False,
        })

    def _record_block(self, task: Task, reason: str):
        self._blocks.append({
            "task_id":  task.task_id,
            "sender":   task.sender,
            "action":   task.action,
            "payload":  task.payload,
            "reason":   reason,
            "resolved": False,
        })

    def get_pending_escalations(self) -> List[dict]:
        return [e for e in self._escalations if not e["resolved"]]

    def get_pending_blocks(self) -> List[dict]:
        return [b for b in self._blocks if not b["resolved"]]

    def resolve(self, task_id: str, action: str = "approved"):
        """Human operator resolves a flagged item."""
        for item in self._escalations + self._blocks:
            if item["task_id"] == task_id:
                item["resolved"] = True
                item["resolution"] = action
                self.log.record(
                    task_id=task_id,
                    sender="human_operator",
                    recipient="governance",
                    action="manual_resolution",
                    verdict=action,
                    reason=f"Manually {action} by operator",
                )
                logger.info("[Interceptor] Task %s resolved: %s", task_id[:8], action)
                return

        logger.warning("[Interceptor] resolve() called for unknown task_id: %s", task_id)

    @property
    def stats(self) -> dict:
        return {
            "total_escalations": len(self._escalations),
            "total_blocks":      len(self._blocks),
            "pending_escalations": len(self.get_pending_escalations()),
            "pending_blocks":      len(self.get_pending_blocks()),
        }

# alert_callback: injected at boot so dashboard and CLI can wire different handlers

# get_pending_escalations() and resolve() support human-review workflow in dashboard

# alert_callback: injected at boot so dashboard and CLI can wire different handlers

# get_pending_escalations() and resolve() support human-review workflow in dashboard
