"""
Inventory Agent

Responsible for:
  - Tracking current stock levels for all components
  - Identifying items that have fallen below reorder thresholds
  - Triggering procurement requests when stock is low
  - Updating inventory levels after deliveries
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List

from agents.base import BaseAgent
from protocol.a2a import AgentCard, MessageRole, Task, TaskState

logger = logging.getLogger(__name__)

INVENTORY_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "inventory.json")


class InventoryAgent(BaseAgent):

    def __init__(self, bus):
        card = AgentCard(
            name="InventoryAgent",
            description="Monitors stock levels and triggers reorder when needed",
            skills=["stock_check", "reorder_trigger", "inventory_update"],
        )
        super().__init__(card, bus)
        self.inventory = self._load_inventory()

    def _load_inventory(self) -> Dict:
        with open(INVENTORY_FILE) as f:
            return json.load(f)

    def handle(self, task: Task) -> Task:
        handlers = {
            "check_stock":       self._check_stock,
            "check_all_levels":  self._check_all_levels,
            "update_stock":      self._update_stock,
            "trigger_reorders":  self._trigger_reorders,
        }
        fn = handlers.get(task.action)
        if not fn:
            task.fail(f"Unknown action: {task.action}")
            return task
        return fn(task)

    # ------------------------------------------------------------------

    def _check_stock(self, task: Task) -> Task:
        item = task.payload.get("item")
        if not item:
            task.fail("Missing 'item' in payload")
            return task

        entry = self.inventory.get(item)
        if not entry:
            task.fail(f"Item not found in inventory: {item}")
            return task

        status = self._stock_status(entry)
        task.complete({
            "item":            item,
            "current_stock":   entry["quantity"],
            "reorder_point":   entry["reorder_point"],
            "max_stock":       entry["max_stock"],
            "unit":            entry.get("unit", "units"),
            "status":          status,
            "needs_reorder":   entry["quantity"] <= entry["reorder_point"],
        })
        return task

    def _check_all_levels(self, task: Task) -> Task:
        """Return the full picture — useful for the dashboard."""
        results = []
        for item, entry in self.inventory.items():
            results.append({
                "item":          item,
                "current_stock": entry["quantity"],
                "reorder_point": entry["reorder_point"],
                "max_stock":     entry["max_stock"],
                "status":        self._stock_status(entry),
            })
        task.complete({"inventory": results})
        return task

    def _update_stock(self, task: Task) -> Task:
        """
        Called after a delivery is received. Adds quantity to current stock
        but doesn't exceed max_stock.
        """
        item     = task.payload.get("item")
        quantity = task.payload.get("quantity", 0)

        if not item or quantity <= 0:
            task.fail("Invalid item or quantity for stock update")
            return task

        entry = self.inventory.get(item)
        if not entry:
            task.fail(f"Item not in inventory: {item}")
            return task

        old_qty = entry["quantity"]
        new_qty = min(old_qty + quantity, entry["max_stock"])
        self.inventory[item]["quantity"] = new_qty

        task.add_message(
            MessageRole.AGENT,
            f"Stock updated for {item}: {old_qty} → {new_qty} units",
        )
        task.complete({
            "item":         item,
            "old_quantity": old_qty,
            "new_quantity": new_qty,
            "added":        new_qty - old_qty,  # may be less than requested if near max
        })
        logger.info(f"[InventoryAgent] {item}: {old_qty} → {new_qty}")
        return task

    def _trigger_reorders(self, task: Task) -> Task:
        """
        Scans all items and fires a procurement request for anything
        that's fallen below its reorder point.
        """
        triggered = []
        skipped   = []

        for item, entry in self.inventory.items():
            if entry["quantity"] > entry["reorder_point"]:
                continue

            # How many to order: fill up to 80% of max to leave headroom
            order_qty = int(entry["max_stock"] * 0.8) - entry["quantity"]
            if order_qty <= 0:
                continue

            task.add_message(
                MessageRole.AGENT,
                f"Low stock detected for {item}: "
                f"{entry['quantity']} units remaining (reorder point: {entry['reorder_point']}). "
                f"Requesting {order_qty} units.",
            )

            po_task = self.send(
                recipient="ProcurementAgent",
                action="create_purchase_order",
                payload={"item": item, "quantity": order_qty},
            )

            if po_task.state == TaskState.COMPLETED:
                triggered.append({
                    "item":     item,
                    "quantity": order_qty,
                    "po":       po_task.result,
                })
            elif po_task.state == TaskState.BLOCKED:
                skipped.append({
                    "item":   item,
                    "reason": po_task.result.get("blocked_reason", "blocked by governance"),
                })
            else:
                skipped.append({
                    "item":   item,
                    "reason": po_task.result.get("error", "unknown failure"),
                })

        task.complete({
            "reorders_triggered": triggered,
            "reorders_skipped":   skipped,
            "total_triggered":    len(triggered),
            "total_skipped":      len(skipped),
        })
        return task

    # ------------------------------------------------------------------

    def _stock_status(self, entry: Dict) -> str:
        qty = entry["quantity"]
        if qty == 0:
            return "out_of_stock"
        elif qty <= entry["reorder_point"]:
            return "low"
        elif qty <= entry["reorder_point"] * 2:
            return "moderate"
        else:
            return "healthy"

# update_stock: caps delivery at max_stock to prevent data entry errors

# status labels: out / low / moderate / healthy based on reorder thresholds

# update_stock: caps delivery at max_stock to prevent data entry errors

# status labels: out / low / moderate / healthy based on reorder thresholds

# fix: return FAILED state for unknown item instead of KeyError
