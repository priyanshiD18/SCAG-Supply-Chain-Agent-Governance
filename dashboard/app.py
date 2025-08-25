"""
SCAG Dashboard

A Streamlit app that gives supply chain ops and finance a live view
of what the agents are doing — without needing to read Python code.

Run:
    streamlit run dashboard/app.py
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st

from agents import BudgetAgent, InventoryAgent, ProcurementAgent
from governance import AuditLog, GovernanceInterceptor, PolicyEngine
from protocol.a2a import A2ABus

# ── Page config ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="SCAG — Supply Chain Agent Governance",
    page_icon="🔍",
    layout="wide",
)


# ── Session state: boot the system once per session ───────────────────
@st.cache_resource
def boot_system():
    bus           = A2ABus()
    policy_engine = PolicyEngine()
    audit_log     = AuditLog()
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
    }


system = boot_system()


# ── Sidebar ───────────────────────────────────────────────────────────
st.sidebar.title("SCAG")
st.sidebar.caption("Supply Chain Agent Governance")
page = st.sidebar.radio(
    "Navigation",
    ["Live Dashboard", "Run Simulation", "Audit Log", "Inventory", "Budget", "Policy Rules"],
)


# ── Helper functions ──────────────────────────────────────────────────
def verdict_badge(v: str) -> str:
    colours = {"approved": "🟢", "escalate": "🟡", "blocked": "🔴"}
    return colours.get(v, "⚪")


def fmt_currency(val) -> str:
    try:
        return f"${float(val):,.2f}"
    except (TypeError, ValueError):
        return str(val)


# ═══════════════════════════════════════════════════════════════════════
# PAGE: Live Dashboard
# ═══════════════════════════════════════════════════════════════════════
if page == "Live Dashboard":
    st.title("Live Dashboard")
    st.caption("Real-time view of agent decisions and governance flags")

    stats    = system["audit_log"].get_stats()
    int_stats = system["interceptor"].stats

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total decisions", stats.get("total", 0))
    col2.metric("Auto-approved",   stats["by_verdict"].get("approved", 0))
    col3.metric("Escalated",       stats["by_verdict"].get("escalate", 0), delta_color="inverse")
    col4.metric("Blocked",         stats["by_verdict"].get("blocked",  0), delta_color="inverse")

    st.divider()

    # Pending items needing human attention
    pending_blocks = system["interceptor"].get_pending_blocks()
    pending_escs   = system["interceptor"].get_pending_escalations()

    if pending_blocks:
        st.subheader("🔴 Blocked — human approval required")
        for item in pending_blocks:
            with st.expander(f"{item['action']}  |  {item['sender']}  |  {item['task_id'][:8]}"):
                st.write("**Reason:**", item["reason"])
                st.json(item["payload"])
                col_a, col_b = st.columns(2)
                if col_a.button("✅ Approve", key=f"app_{item['task_id']}"):
                    system["interceptor"].resolve(item["task_id"], "approved")
                    st.rerun()
                if col_b.button("❌ Reject", key=f"rej_{item['task_id']}"):
                    system["interceptor"].resolve(item["task_id"], "rejected")
                    st.rerun()

    if pending_escs:
        st.subheader("🟡 Escalated — for your awareness")
        for item in pending_escs:
            with st.expander(f"{item['action']}  |  {item['sender']}  |  {item['task_id'][:8]}"):
                st.write("**Reason:**", item["reason"])
                st.json(item["payload"])
                if st.button("Mark as reviewed", key=f"rev_{item['task_id']}"):
                    system["interceptor"].resolve(item["task_id"], "reviewed")
                    st.rerun()

    if not pending_blocks and not pending_escs:
        st.success("No pending items — all agent decisions are within policy.")

    st.divider()
    st.subheader("Recent decisions")
    recent = system["audit_log"].get_recent(20)
    for row in recent:
        cols = st.columns([1, 3, 3, 4])
        cols[0].write(verdict_badge(row["verdict"]) + " " + row["verdict"].upper())
        cols[1].write(row["sender"])
        cols[2].write(row["action"])
        cols[3].write(row["reason"][:80] + ("…" if len(row["reason"]) > 80 else ""))


# ═══════════════════════════════════════════════════════════════════════
# PAGE: Run Simulation
# ═══════════════════════════════════════════════════════════════════════
elif page == "Run Simulation":
    st.title("Run a simulation")
    st.caption("Trigger agent actions manually and watch governance respond")

    st.subheader("Create a purchase order")
    with st.form("po_form"):
        items = ["GPU Module", "CPU Board", "Memory Module", "Network Card",
                 "SSD Drive", "Power Supply Unit", "Cooling Fan", "Motherboard"]
        item     = st.selectbox("Item", items)
        quantity = st.number_input("Quantity", min_value=1, max_value=20000, value=500, step=100)
        submitted = st.form_submit_button("Submit to Procurement Agent")

    if submitted:
        task = system["inventory"].send(
            "ProcurementAgent",
            "create_purchase_order",
            {"item": item, "quantity": quantity},
        )
        st.divider()
        verdict_map = {
            "completed": ("success", "✅ Approved and completed"),
            "blocked":   ("error",   "🔴 Blocked by governance"),
            "failed":    ("error",   "❌ Failed"),
        }
        display_type, label = verdict_map.get(task.state.value, ("info", "ℹ️ " + task.state.value))
        getattr(st, display_type)(label)
        if task.result:
            st.json(task.result)

    st.divider()
    st.subheader("Trigger full inventory reorder sweep")
    if st.button("Run reorder sweep now"):
        with st.spinner("Scanning all inventory levels…"):
            task = system["inventory"].send("InventoryAgent", "trigger_reorders", {})
        st.success(f"Sweep complete. Triggered: {task.result.get('total_triggered', 0)}, "
                   f"Skipped: {task.result.get('total_skipped', 0)}")
        if task.result:
            st.json(task.result)


# ═══════════════════════════════════════════════════════════════════════
# PAGE: Audit Log
# ═══════════════════════════════════════════════════════════════════════
elif page == "Audit Log":
    st.title("Audit Log")
    st.caption("Complete record of every agent decision — immutable, timestamped")

    filter_verdict = st.selectbox(
        "Filter by verdict", ["all", "approved", "escalate", "blocked"]
    )

    if filter_verdict == "all":
        rows = system["audit_log"].get_recent(100)
    else:
        rows = system["audit_log"].get_by_verdict(filter_verdict, 100)

    if not rows:
        st.info("No entries yet. Run a simulation first.")
    else:
        for row in rows:
            badge = verdict_badge(row["verdict"])
            with st.expander(
                f"{badge} {row['verdict'].upper()}  |  "
                f"{row['sender']} → {row['action']}  |  "
                f"{row['created_at'][:19]}"
            ):
                st.write("**Reason:**", row["reason"])
                col1, col2 = st.columns(2)
                if row.get("payload"):
                    col1.write("**Payload**")
                    col1.json(row["payload"])
                if row.get("result"):
                    col2.write("**Result**")
                    col2.json(row["result"])


# ═══════════════════════════════════════════════════════════════════════
# PAGE: Inventory
# ═══════════════════════════════════════════════════════════════════════
elif page == "Inventory":
    st.title("Inventory levels")

    task = system["inventory"].send("InventoryAgent", "check_all_levels", {})
    if task.result:
        items = task.result.get("inventory", [])
        for item in items:
            status = item["status"]
            colour = {"healthy": "🟢", "moderate": "🟡", "low": "🔴", "out_of_stock": "⛔"}.get(status, "⚪")
            pct = item["current_stock"] / item["max_stock"] * 100 if item["max_stock"] else 0
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            col1.write(f"**{item['item']}**")
            col2.write(f"{item['current_stock']:,} / {item['max_stock']:,} units")
            col3.progress(int(pct), text=f"{pct:.0f}%")
            col4.write(f"{colour} {status}")


# ═══════════════════════════════════════════════════════════════════════
# PAGE: Budget
# ═══════════════════════════════════════════════════════════════════════
elif page == "Budget":
    st.title("Budget utilisation")

    task = system["budget"].send("BudgetAgent", "get_budget_status", {})
    if task.result:
        departments = task.result.get("departments", {})
        for dept, data in departments.items():
            st.subheader(dept.replace("_", " ").title())
            col1, col2, col3 = st.columns(3)
            col1.metric("Allocated", fmt_currency(data["allocated"]))
            col2.metric("Spent",     fmt_currency(data["spent"]))
            col3.metric("Remaining", fmt_currency(data["remaining"]))
            pct = data.get("utilisation_pct", 0)
            colour = "normal" if pct < 80 else "inverse"
            st.progress(int(min(pct, 100)), text=f"{pct:.1f}% utilised")
            st.divider()


# ═══════════════════════════════════════════════════════════════════════
# PAGE: Policy Rules
# ═══════════════════════════════════════════════════════════════════════
elif page == "Policy Rules":
    st.title("Policy rules")
    st.caption("Current governance rules loaded from config/policies.yaml")

    rules = system["interceptor"].policy.rules

    st.subheader("Spending limits")
    limits = rules.get("spending_limits", {})
    col1, col2 = st.columns(2)
    col1.metric("Auto-approve below", fmt_currency(limits.get("escalate_above", 0)))
    col2.metric("Hard block above",   fmt_currency(limits.get("block_above", 0)))

    st.subheader("Approved suppliers")
    for s in rules.get("approved_suppliers", []):
        st.write(f"✅ {s}")

    st.subheader("Inventory thresholds")
    inv = rules.get("inventory_thresholds", {})
    st.write(f"Max single order: **{inv.get('max_single_order', 0):,} units**")
    st.write(f"Max delivery update: **{inv.get('max_delivery_update', 0):,} units**")

    st.divider()
    st.caption(
        "To update rules, edit `config/policies.yaml` and restart the app. "
        "No code changes required."
    )

# Live Dashboard tab: pending blocks queue, escalation queue, recent decisions feed
