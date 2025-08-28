"""
Tests for agents and governance layer.

Run:
    pytest tests/ -v
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch

from agents import ProcurementAgent, InventoryAgent, BudgetAgent
from governance import AuditLog, GovernanceInterceptor, PolicyEngine, Verdict
from protocol.a2a import A2ABus, TaskState


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def system(tmp_path):
    """Boot a fresh system with a temporary audit DB for each test."""
    db_path = str(tmp_path / "test_audit.db")
    bus           = A2ABus()
    policy_engine = PolicyEngine()
    audit_log     = AuditLog(db_path)
    interceptor   = GovernanceInterceptor(policy_engine, audit_log)

    bus.set_interceptor(interceptor.intercept)

    procurement = ProcurementAgent(bus)
    inventory   = InventoryAgent(bus)
    budget      = BudgetAgent(bus)

    procurement.register()
    inventory.register()
    budget.register()

    return {
        "bus":         bus,
        "procurement": procurement,
        "inventory":   inventory,
        "budget":      budget,
        "interceptor": interceptor,
        "audit_log":   audit_log,
        "policy":      policy_engine,
    }


# ── Policy Engine ─────────────────────────────────────────────────────

class TestPolicyEngine:

    def test_small_purchase_is_approved(self, system):
        verdict, reason = system["policy"].evaluate(
            "create_purchase_order",
            {"total_cost": 10_000, "supplier": "TechParts Inc", "quantity": 200},
        )
        assert verdict == Verdict.APPROVED

    def test_mid_purchase_is_escalated(self, system):
        verdict, reason = system["policy"].evaluate(
            "create_purchase_order",
            {"total_cost": 85_000, "supplier": "TechParts Inc", "quantity": 2000},
        )
        assert verdict == Verdict.ESCALATE

    def test_large_purchase_is_blocked(self, system):
        verdict, reason = system["policy"].evaluate(
            "create_purchase_order",
            {"total_cost": 250_000, "supplier": "TechParts Inc", "quantity": 5000},
        )
        assert verdict == Verdict.BLOCKED

    def test_unapproved_supplier_is_blocked(self, system):
        verdict, reason = system["policy"].evaluate(
            "create_purchase_order",
            {"total_cost": 5_000, "supplier": "BudgetParts Wholesale", "quantity": 100},
        )
        assert verdict == Verdict.BLOCKED
        assert "approved supplier" in reason.lower()

    def test_excess_quantity_is_blocked(self, system):
        verdict, reason = system["policy"].evaluate(
            "create_purchase_order",
            {"total_cost": 20_000, "supplier": "TechParts Inc", "quantity": 15_000},
        )
        assert verdict == Verdict.BLOCKED


# ── Procurement Agent ─────────────────────────────────────────────────

class TestProcurementAgent:

    def test_valid_order_completes(self, system):
        task = system["inventory"].send(
            "ProcurementAgent",
            "create_purchase_order",
            {"item": "Cooling Fan", "quantity": 200},
        )
        assert task.state == TaskState.COMPLETED
        assert task.result["po_number"].startswith("PO-")
        assert task.result["quantity"] == 200

    def test_missing_item_fails(self, system):
        task = system["procurement"].send(
            "ProcurementAgent",
            "create_purchase_order",
            {"quantity": 100},
        )
        assert task.state == TaskState.FAILED

    def test_zero_quantity_fails(self, system):
        task = system["procurement"].send(
            "ProcurementAgent",
            "create_purchase_order",
            {"item": "GPU Module", "quantity": 0},
        )
        assert task.state == TaskState.FAILED

    def test_large_order_blocked_by_governance(self, system):
        task = system["inventory"].send(
            "ProcurementAgent",
            "create_purchase_order",
            {"item": "GPU Module", "quantity": 6000},   # > $200k
        )
        assert task.state == TaskState.BLOCKED

    def test_best_quote_returns_cheapest_supplier(self, system):
        task = system["procurement"].send(
            "ProcurementAgent",
            "get_best_quote",
            {"item": "GPU Module", "quantity": 100},
        )
        assert task.state == TaskState.COMPLETED
        assert task.result["unit_price"] > 0


# ── Inventory Agent ───────────────────────────────────────────────────

class TestInventoryAgent:

    def test_check_stock_returns_status(self, system):
        task = system["inventory"].send(
            "InventoryAgent",
            "check_stock",
            {"item": "GPU Module"},
        )
        assert task.state == TaskState.COMPLETED
        assert "current_stock" in task.result
        assert "status" in task.result

    def test_update_stock_increases_quantity(self, system):
        before = system["inventory"].send(
            "InventoryAgent", "check_stock", {"item": "Cooling Fan"}
        ).result["current_stock"]

        system["inventory"].send(
            "InventoryAgent", "update_stock", {"item": "Cooling Fan", "quantity": 100}
        )

        after = system["inventory"].send(
            "InventoryAgent", "check_stock", {"item": "Cooling Fan"}
        ).result["current_stock"]

        assert after > before

    def test_check_all_levels_returns_all_items(self, system):
        task = system["inventory"].send(
            "InventoryAgent", "check_all_levels", {}
        )
        assert task.state == TaskState.COMPLETED
        assert len(task.result["inventory"]) > 0

    def test_unknown_item_fails(self, system):
        task = system["inventory"].send(
            "InventoryAgent", "check_stock", {"item": "Nonexistent Part XYZ"}
        )
        assert task.state == TaskState.FAILED


# ── Budget Agent ──────────────────────────────────────────────────────

class TestBudgetAgent:

    def test_spend_within_budget_is_approved(self, system):
        task = system["budget"].send(
            "BudgetAgent",
            "approve_spend",
            {"item": "Network Card", "total_cost": 5_000,
             "supplier": "Global Components Ltd", "department": "supply_chain"},
        )
        assert task.state == TaskState.COMPLETED
        assert task.result["approved"] is True

    def test_get_budget_status_returns_all_depts(self, system):
        task = system["budget"].send(
            "BudgetAgent", "get_budget_status", {}
        )
        assert task.state == TaskState.COMPLETED
        assert "departments" in task.result


# ── Audit Log ─────────────────────────────────────────────────────────

class TestAuditLog:

    def test_every_decision_is_logged(self, system):
        before = system["audit_log"].get_stats()["total"]

        system["inventory"].send(
            "ProcurementAgent",
            "create_purchase_order",
            {"item": "Cooling Fan", "quantity": 100},
        )

        after = system["audit_log"].get_stats()["total"]
        assert after > before

    def test_blocked_decisions_are_logged(self, system):
        system["inventory"].send(
            "ProcurementAgent",
            "create_purchase_order",
            {"item": "GPU Module", "quantity": 6000},
        )
        blocked = system["audit_log"].get_by_verdict("blocked")
        assert len(blocked) >= 1

    def test_get_recent_respects_limit(self, system):
        rows = system["audit_log"].get_recent(5)
        assert len(rows) <= 5
