"""
Procurement Agent

Responsible for:
  - Receiving reorder requests from the Inventory Agent
  - Choosing the best supplier based on price, lead time, and approval status
  - Requesting budget approval from the Budget Agent
  - Submitting the final purchase order

The agent deliberately doesn't know about governance rules — that's the
interceptor's job. It just makes the best business decision it can.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional

from agents.base import BaseAgent
from protocol.a2a import AgentCard, MessageRole, Task, TaskState

logger = logging.getLogger(__name__)

SUPPLIERS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "suppliers.json")


def _load_suppliers() -> List[Dict]:
    with open(SUPPLIERS_FILE) as f:
        return json.load(f)


class ProcurementAgent(BaseAgent):
    """
    Handles the end-to-end flow of raising and approving a purchase order.
    """

    def __init__(self, bus):
        card = AgentCard(
            name="ProcurementAgent",
            description="Selects suppliers and raises purchase orders",
            skills=["supplier_selection", "purchase_order", "rfq"],
        )
        super().__init__(card, bus)
        self.suppliers = _load_suppliers()

    # ------------------------------------------------------------------
    # Task router — dispatches to the right internal method
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> Task:
        handlers = {
            "create_purchase_order": self._create_purchase_order,
            "get_supplier_list":     self._get_supplier_list,
            "get_best_quote":        self._get_best_quote,
        }

        fn = handlers.get(task.action)
        if not fn:
            task.fail(f"Unknown action: {task.action}")
            return task

        return fn(task)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _create_purchase_order(self, task: Task) -> Task:
        """
        Main action: create a PO for a given item and quantity.

        Steps:
          1. Find the best available supplier
          2. Ask the Budget Agent to approve the spend
          3. Return PO details if everything clears
        """
        item     = task.payload.get("item")
        quantity = task.payload.get("quantity", 0)

        if not item or quantity <= 0:
            task.fail("Missing 'item' or invalid 'quantity' in payload")
            return task

        supplier = self._select_supplier(item)
        if not supplier:
            task.fail(f"No approved supplier found for item: {item}")
            return task

        unit_price  = supplier["unit_price"]
        total_cost  = round(unit_price * quantity, 2)
        supplier_name = supplier["name"]

        task.add_message(
            MessageRole.AGENT,
            f"Selected supplier: {supplier_name} @ ${unit_price}/unit. "
            f"Total for {quantity} units: ${total_cost:,}",
        )

        # Ask the Budget Agent before committing
        budget_task = self.send(
            recipient="BudgetAgent",
            action="approve_spend",
            payload={
                "item":          item,
                "quantity":      quantity,
                "supplier":      supplier_name,
                "total_cost":    total_cost,
                "requested_by":  self.card.name,
            },
        )

        if budget_task.state == TaskState.BLOCKED:
            task.block(
                f"Budget approval blocked: "
                f"{budget_task.result.get('blocked_reason', 'unknown')}"
            )
            return task

        if budget_task.state != TaskState.COMPLETED:
            task.fail(
                f"Budget approval failed: "
                f"{budget_task.result.get('error', 'unknown error')}"
            )
            return task

        # All clear — build the PO
        po_number = f"PO-{task.task_id[:8].upper()}"
        task.complete({
            "po_number":    po_number,
            "item":         item,
            "quantity":     quantity,
            "supplier":     supplier_name,
            "unit_price":   unit_price,
            "total_cost":   total_cost,
            "lead_time_days": supplier["lead_time_days"],
            "status":       "approved",
        })

        logger.info(
            f"[ProcurementAgent] PO created: {po_number} | "
            f"{quantity}x {item} from {supplier_name} | ${total_cost:,}"
        )
        return task

    def _get_supplier_list(self, task: Task) -> Task:
        item = task.payload.get("item")
        suppliers = [
            s for s in self.suppliers
            if not item or item.lower() in [i.lower() for i in s.get("items", [])]
        ]
        task.complete({"suppliers": suppliers})
        return task

    def _get_best_quote(self, task: Task) -> Task:
        item     = task.payload.get("item")
        quantity = task.payload.get("quantity", 1)
        supplier = self._select_supplier(item)
        if not supplier:
            task.fail(f"No supplier available for: {item}")
            return task

        task.complete({
            "supplier":   supplier["name"],
            "unit_price": supplier["unit_price"],
            "total":      round(supplier["unit_price"] * quantity, 2),
            "lead_time":  supplier["lead_time_days"],
        })
        return task

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_supplier(self, item: str) -> Optional[Dict]:
        """
        Pick the cheapest approved supplier that carries the requested item.
        In real life you'd weight lead time and reliability scores too.
        """
        candidates = [
            s for s in self.suppliers
            if s.get("approved") and item.lower() in [i.lower() for i in s.get("items", [])]
        ]
        if not candidates:
            return None

        # Sort by price, break ties with lead time
        candidates.sort(key=lambda s: (s["unit_price"], s["lead_time_days"]))
        return candidates[0]

# supplier selection: cheapest approved supplier, break ties on lead time

# PO number format: PO-<ITEM>-<TIMESTAMP> for audit traceability

# supplier selection: cheapest approved supplier, break ties on lead time

# PO number format: PO-<ITEM>-<TIMESTAMP> for audit traceability
