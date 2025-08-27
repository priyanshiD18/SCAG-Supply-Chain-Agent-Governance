"""
main.py — run a full demo of the supply chain agent network.

This script boots the three agents, wires up the governance layer,
and runs a series of realistic scenarios so you can see the system
in action from the terminal.

Usage:
    python main.py
    python main.py --scenario all        # default
    python main.py --scenario approved
    python main.py --scenario escalate
    python main.py --scenario blocked
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from agents import BudgetAgent, InventoryAgent, ProcurementAgent
from governance import AuditLog, GovernanceInterceptor, PolicyEngine
from protocol.a2a import A2ABus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Colours for terminal output ──────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def print_result(label: str, task):
    state = task.state.value.upper()
    colour = {"COMPLETED": GREEN, "BLOCKED": RED, "FAILED": RED}.get(state, YELLOW)
    print(f"\n{colour}{BOLD}[{state}]{RESET}  {label}")
    if task.result:
        print(json.dumps(task.result, indent=2))
    print()


def build_system(alert_fn=None) -> dict:
    """Boot everything and return a dict of the key components."""
    bus            = A2ABus()
    policy_engine  = PolicyEngine()
    audit_log      = AuditLog()
    interceptor    = GovernanceInterceptor(policy_engine, audit_log, alert_fn)

    bus.set_interceptor(interceptor.intercept)

    procurement = ProcurementAgent(bus)
    inventory   = InventoryAgent(bus)
    budget      = BudgetAgent(bus)

    procurement.register()
    inventory.register()
    budget.register()

    return {
        "bus":          bus,
        "procurement":  procurement,
        "inventory":    inventory,
        "budget":       budget,
        "interceptor":  interceptor,
        "audit_log":    audit_log,
    }


# ── Scenarios ─────────────────────────────────────────────────────────

def scenario_approved(sys: dict):
    """Small orders that sail through governance automatically."""
    print(f"\n{CYAN}{'─'*60}")
    print("SCENARIO 1 — Small orders (auto-approved)")
    print(f"{'─'*60}{RESET}")

    task = sys["inventory"].send(
        "ProcurementAgent",
        "create_purchase_order",
        {"item": "Cooling Fan", "quantity": 500},
    )
    print_result("500× Cooling Fan @ ~$33 = ~$16,500 (under $50k limit)", task)

    task = sys["procurement"].send(
        "BudgetAgent",
        "approve_spend",
        {"item": "Network Card", "quantity": 200, "total_cost": 7600,
         "supplier": "Global Components Ltd"},
    )
    print_result("200× Network Card @ $38 = $7,600 budget check", task)


def scenario_escalate(sys: dict):
    """Mid-range order that gets flagged to Finance but still goes through."""
    print(f"\n{YELLOW}{'─'*60}")
    print("SCENARIO 2 — Large order (escalated to Finance)")
    print(f"{'─'*60}{RESET}")

    # 2,000 × $42.50 = $85,000 → over $50k escalation threshold
    task = sys["inventory"].send(
        "ProcurementAgent",
        "create_purchase_order",
        {"item": "GPU Module", "quantity": 2000},
    )
    print_result("2,000× GPU Module @ $42.50 = $85,000 (escalated)", task)


def scenario_blocked(sys: dict):
    """Very large orders that governance blocks outright."""
    print(f"\n{RED}{'─'*60}")
    print("SCENARIO 3 — Oversized orders (blocked by governance)")
    print(f"{'─'*60}{RESET}")

    # $42.50 × 6,000 = $255,000 → over $200k hard limit
    task = sys["inventory"].send(
        "ProcurementAgent",
        "create_purchase_order",
        {"item": "GPU Module", "quantity": 6000},
    )
    print_result("6,000× GPU Module = $255,000 (exceeds $200k hard limit)", task)

    # Unapproved supplier
    task = sys["procurement"].send(
        "ProcurementAgent",
        "create_purchase_order",
        {"item": "CPU Board", "quantity": 100, "supplier": "BudgetParts Wholesale"},
    )
    print_result("CPU Board from unapproved supplier (BudgetParts Wholesale)", task)


def scenario_reorder_sweep(sys: dict):
    """Full inventory scan — triggers mixed results across multiple items."""
    print(f"\n{CYAN}{'─'*60}")
    print("SCENARIO 4 — Full inventory reorder sweep")
    print(f"{'─'*60}{RESET}")

    task = sys["inventory"].send(
        "InventoryAgent",
        "trigger_reorders",
        {},
    )
    print_result("Inventory reorder sweep", task)


def print_audit_summary(sys: dict):
    stats = sys["audit_log"].get_stats()
    recent = sys["audit_log"].get_recent(10)

    print(f"\n{BOLD}{'═'*60}")
    print("AUDIT LOG SUMMARY")
    print(f"{'═'*60}{RESET}")
    print(f"Total decisions logged : {stats['total']}")
    print(f"By verdict             : {stats['by_verdict']}")
    print(f"\nLast {min(10, len(recent))} entries:")
    for row in recent[:10]:
        colour = {
            "approved": GREEN,
            "escalate": YELLOW,
            "blocked":  RED,
        }.get(row["verdict"], RESET)
        print(
            f"  {colour}[{row['verdict'].upper():8}]{RESET}  "
            f"{row['sender']:<20} → {row['action']}"
        )


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SCAG demo runner")
    parser.add_argument(
        "--scenario",
        choices=["all", "approved", "escalate", "blocked", "reorder"],
        default="all",
    )
    args = parser.parse_args()

    def alert(kind: str, task, reason: str):
        colour = YELLOW if kind == "escalate" else RED
        print(f"\n  {colour}[ALERT — {kind.upper()}]{RESET} {task.action} | {reason}")

    print(f"\n{BOLD}Supply Chain Agent Governance (SCAG){RESET}")
    print("Booting agents and governance layer...\n")

    sys_ = build_system(alert)

    if args.scenario in ("all", "approved"):
        scenario_approved(sys_)
    if args.scenario in ("all", "escalate"):
        scenario_escalate(sys_)
    if args.scenario in ("all", "blocked"):
        scenario_blocked(sys_)
    if args.scenario in ("all", "reorder"):
        scenario_reorder_sweep(sys_)

    print_audit_summary(sys_)
    print(f"\n{GREEN}Run 'streamlit run dashboard/app.py' to open the dashboard.{RESET}\n")


if __name__ == "__main__":
    main()

# build_system() returns component dict — shared by CLI runner and test fixtures

# build_system() returns component dict — shared by CLI runner and test fixtures

# interceptor registered on bus: every agent message passes through governance layer

# four scenarios: scenario_approved, scenario_escalate, scenario_blocked, scenario_reorder_sweep
