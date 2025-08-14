"""
Budget Agent

Responsible for:
  - Tracking departmental spend against monthly budget allocations
  - Approving or flagging spend requests from the Procurement Agent
  - Reporting current budget utilisation
  - Enforcing hard spend limits (anything over the limit is escalated,
    not rejected — the governance interceptor makes the final call)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Dict

from agents.base import BaseAgent
from protocol.a2a import AgentCard, MessageRole, Task

logger = logging.getLogger(__name__)

BUDGET_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "budget.json")


class BudgetAgent(BaseAgent):

    def __init__(self, bus):
        card = AgentCard(
            name="BudgetAgent",
            description="Tracks spend and approves procurement requests within budget",
            skills=["spend_approval", "budget_report", "utilisation_check"],
        )
        super().__init__(card, bus)
        self.budget = self._load_budget()

    def _load_budget(self) -> Dict:
        with open(BUDGET_FILE) as f:
            return json.load(f)

    def handle(self, task: Task) -> Task:
        handlers = {
            "approve_spend":    self._approve_spend,
            "get_budget_status": self._get_budget_status,
            "get_utilisation":  self._get_utilisation,
        }
        fn = handlers.get(task.action)
        if not fn:
            task.fail(f"Unknown action: {task.action}")
            return task
        return fn(task)

    # ------------------------------------------------------------------

    def _approve_spend(self, task: Task) -> Task:
        """
        Core approval logic.

        The agent approves if funds are available. It does NOT enforce
        dollar-amount escalation rules — that's the governance interceptor's
        job. This agent only cares about: "do we have the budget?"
        """
        total_cost  = task.payload.get("total_cost", 0)
        item        = task.payload.get("item", "unknown")
        supplier    = task.payload.get("supplier", "unknown")
        department  = task.payload.get("department", "supply_chain")

        dept_budget = self.budget.get(department)
        if not dept_budget:
            # Unknown department — default to supply_chain
            dept_budget = self.budget.get("supply_chain", {})

        remaining   = dept_budget.get("remaining", 0)
        allocated   = dept_budget.get("allocated", 0)
        spent       = dept_budget.get("spent", 0)
        utilisation = round((spent / allocated * 100), 1) if allocated else 0

        task.add_message(
            MessageRole.AGENT,
            f"Budget check for ${total_cost:,.2f} | "
            f"Dept: {department} | "
            f"Remaining: ${remaining:,.2f} | "
            f"Utilisation: {utilisation}%",
        )

        if total_cost > remaining:
            task.fail(
                f"Insufficient budget. Requested: ${total_cost:,.2f}, "
                f"Available: ${remaining:,.2f}"
            )
            logger.warning(
                f"[BudgetAgent] Rejected spend of ${total_cost:,} — "
                f"exceeds remaining budget (${remaining:,})"
            )
            return task

        # Tentatively reserve the funds
        # (In production this would be transactional — rollback if PO fails)
        self.budget[department]["spent"]     = round(spent + total_cost, 2)
        self.budget[department]["remaining"] = round(remaining - total_cost, 2)

        task.complete({
            "approved":       True,
            "total_cost":     total_cost,
            "item":           item,
            "supplier":       supplier,
            "department":     department,
            "remaining_after": self.budget[department]["remaining"],
            "utilisation_pct": round(
                (self.budget[department]["spent"] / allocated * 100), 1
            ),
            "approved_at":    datetime.utcnow().isoformat(),
        })

        logger.info(
            f"[BudgetAgent] Approved ${total_cost:,} for {item} "
            f"from {supplier} | Remaining budget: ${self.budget[department]['remaining']:,}"
        )
        return task

    def _get_budget_status(self, task: Task) -> Task:
        """Return the full budget picture for all departments."""
        summary = {}
        for dept, data in self.budget.items():
            allocated = data.get("allocated", 0)
            spent     = data.get("spent", 0)
            summary[dept] = {
                "allocated":     allocated,
                "spent":         spent,
                "remaining":     data.get("remaining", 0),
                "utilisation_pct": round(spent / allocated * 100, 1) if allocated else 0,
            }
        task.complete({"departments": summary, "as_of": datetime.utcnow().isoformat()})
        return task

    def _get_utilisation(self, task: Task) -> Task:
        department = task.payload.get("department", "supply_chain")
        data       = self.budget.get(department, {})
        allocated  = data.get("allocated", 1)
        spent      = data.get("spent", 0)

        task.complete({
            "department":     department,
            "allocated":      allocated,
            "spent":          spent,
            "remaining":      data.get("remaining", 0),
            "utilisation_pct": round(spent / allocated * 100, 1),
        })
        return task

# get_utilisation: returns utilisation % per department for dashboard gauges

# get_utilisation: returns utilisation % per department for dashboard gauges
