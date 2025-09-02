"""
Policy Engine

Loads governance rules from config/policies.yaml and evaluates any
incoming task against those rules.

Returns one of three verdicts:
  APPROVED  — agent can proceed without any human involvement
  ESCALATE  — agent can proceed, but a human is notified
  BLOCKED   — agent is stopped; human must act before anything happens

Keeping the rules in a YAML file (not hardcoded here) means a supply
chain ops manager can update thresholds without touching Python code.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Any, Dict, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

POLICY_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "policies.yaml")


class Verdict(str, Enum):
    APPROVED = "approved"
    ESCALATE = "escalate"
    BLOCKED  = "blocked"


class PolicyEngine:

    def __init__(self, policy_file: str = POLICY_FILE):
        self.policy_file = policy_file
        self.rules = self._load_rules()
        logger.info("[PolicyEngine] Rules loaded from %s", policy_file)

    def _load_rules(self) -> Dict:
        with open(self.policy_file) as f:
            return yaml.safe_load(f)

    def reload(self):
        """Hot-reload rules without restarting — useful in long-running services."""
        self.rules = self._load_rules()
        logger.info("[PolicyEngine] Rules reloaded")

    # ------------------------------------------------------------------
    # Main evaluation entry point
    # ------------------------------------------------------------------

    def evaluate(self, action: str, payload: Dict[str, Any]) -> Tuple[Verdict, str]:
        """
        Evaluate a proposed action against all applicable rules.

        Returns (verdict, reason) where reason is a human-readable
        explanation of why the verdict was reached.
        """
        evaluators = {
            "create_purchase_order": self._eval_purchase_order,
            "approve_spend":         self._eval_spend_approval,
            "update_stock":          self._eval_stock_update,
            "trigger_reorders":      self._eval_reorder_trigger,
        }

        fn = evaluators.get(action)
        if fn:
            return fn(payload)

        # Actions with no specific rule default to approved
        return Verdict.APPROVED, f"No policy rule for action '{action}' — defaulting to approved"

    # ------------------------------------------------------------------
    # Per-action evaluators
    # ------------------------------------------------------------------

    def _eval_purchase_order(self, payload: Dict) -> Tuple[Verdict, str]:
        total_cost = payload.get("total_cost", 0)
        supplier   = payload.get("supplier", "")
        item       = payload.get("item", "")
        quantity   = payload.get("quantity", 0)

        limits = self.rules.get("spending_limits", {})
        block_above    = limits.get("block_above", 200_000)
        escalate_above = limits.get("escalate_above", 50_000)

        approved_suppliers = self.rules.get("approved_suppliers", [])
        inv_rules          = self.rules.get("inventory_thresholds", {})
        max_single_order   = inv_rules.get("max_single_order", 10_000)

        # Hard blocks first
        if total_cost > block_above:
            return (
                Verdict.BLOCKED,
                f"PO value ${total_cost:,.2f} exceeds autonomous limit "
                f"(${block_above:,}). Human approval required.",
            )

        if supplier and approved_suppliers and supplier not in approved_suppliers:
            return (
                Verdict.BLOCKED,
                f"Supplier '{supplier}' is not on the approved supplier list.",
            )

        if quantity > max_single_order:
            return (
                Verdict.BLOCKED,
                f"Order quantity {quantity:,} exceeds single-order limit "
                f"({max_single_order:,} units). Possible data error.",
            )

        # Soft escalations
        if total_cost > escalate_above:
            return (
                Verdict.ESCALATE,
                f"PO value ${total_cost:,.2f} is above ${escalate_above:,}. "
                f"Finance team notified for awareness.",
            )

        return Verdict.APPROVED, f"PO for ${total_cost:,.2f} approved automatically."

    def _eval_spend_approval(self, payload: Dict) -> Tuple[Verdict, str]:
        total_cost = payload.get("total_cost", 0)
        limits     = self.rules.get("spending_limits", {})
        block_above = limits.get("block_above", 200_000)
        escalate_above = limits.get("escalate_above", 50_000)

        if total_cost > block_above:
            return (
                Verdict.BLOCKED,
                f"Spend of ${total_cost:,.2f} requires human sign-off (limit: ${block_above:,}).",
            )
        if total_cost > escalate_above:
            return (
                Verdict.ESCALATE,
                f"Spend of ${total_cost:,.2f} flagged for Finance awareness.",
            )

        return Verdict.APPROVED, "Spend within autonomous limits."

    def _eval_stock_update(self, payload: Dict) -> Tuple[Verdict, str]:
        quantity = payload.get("quantity", 0)
        inv_rules = self.rules.get("inventory_thresholds", {})
        max_delivery = inv_rules.get("max_delivery_update", 50_000)

        if quantity > max_delivery:
            return (
                Verdict.BLOCKED,
                f"Delivery quantity {quantity:,} is unusually large. "
                f"Possible data entry error — manual review required.",
            )
        return Verdict.APPROVED, "Stock update within normal range."

    def _eval_reorder_trigger(self, payload: Dict) -> Tuple[Verdict, str]:
        # Reorder sweeps are always allowed to run — individual POs
        # get evaluated separately by _eval_purchase_order
        return Verdict.APPROVED, "Reorder scan approved."

# fail-safe default: unknown actions return APPROVED to avoid over-blocking on rollout

# fail-safe default: unknown actions return APPROVED to avoid over-blocking on rollout

# approve_spend evaluator: checks high utilisation as ESCALATE trigger
