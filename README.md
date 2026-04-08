# SCAG — Supply Chain Agent Governance

A working prototype of a governance and observability layer for multi-agent AI systems operating in supply chain environments.

Built on top of Google's [Agent2Agent (A2A) protocol](https://github.com/google/A2A) concepts, SCAG demonstrates how to make autonomous AI agents **auditable, policy-bound, and safe to run in production** — without modifying the agents themselves.

---

## The problem this solves

Companies are increasingly deploying networks of AI agents to automate supply chain tasks — ordering components, managing inventory, approving spend. These agents can act faster than any human team, but they create a new operational risk: **nobody knows what decisions they made, why, or whether a human ever approved them.**

This project addresses that gap directly. It adds a governance layer that:

- Intercepts every agent action before it executes
- Evaluates it against a configurable policy ruleset
- Logs the decision permanently (approved / escalated / blocked)
- Alerts humans when something needs their attention

The agents themselves don't need to change. The governance layer is transparent to them — it sits on the message bus, not inside any agent.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    A2A Message Bus                        │
│                                                          │
│   InventoryAgent ──┐                                     │
│                    ├──► GovernanceInterceptor ──► Agent  │
│   ProcurementAgent─┤         │                           │
│                    │    PolicyEngine                      │
│   BudgetAgent ─────┘    AuditLog (SQLite)                │
└──────────────────────────────────────────────────────────┘
```

**Three agents:**
- `InventoryAgent` — monitors stock levels, triggers reorders when items fall below threshold
- `ProcurementAgent` — selects suppliers, raises purchase orders, coordinates with Budget
- `BudgetAgent` — tracks departmental spend, approves or rejects spend requests

**Governance layer (the core of this project):**
- `GovernanceInterceptor` — sits on the A2A bus; every task passes through before delivery
- `PolicyEngine` — loads rules from `config/policies.yaml`; returns APPROVED / ESCALATE / BLOCKED
- `AuditLog` — SQLite-backed immutable log of every agent decision

**Dashboard:**
- Streamlit app with live decision feed, pending approvals queue, inventory view, budget utilisation, and policy viewer

---

## Governance verdicts

| Verdict | Meaning | Example |
|---|---|---|
| `APPROVED` | Agent proceeds without human involvement | Order 200 fans @ $7,600 total |
| `ESCALATE` | Agent proceeds, Finance is notified | Order 2,000 GPU modules @ $76,000 |
| `BLOCKED` | Agent is stopped; human must act | Order $255,000 of hardware from unapproved supplier |

Thresholds are defined in `config/policies.yaml` — no code changes needed to adjust them.

---

## Quickstart

```bash
# 1. Clone and set up
git clone https://github.com/your-username/scag.git
cd scag
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Run the terminal demo
python main.py

# 3. Open the dashboard
streamlit run dashboard/app.py
```

The project runs fully offline. No API keys required.

---

## Project structure

```
scag/
├── agents/
│   ├── base.py            # shared BaseAgent scaffolding
│   ├── procurement.py     # ProcurementAgent
│   ├── inventory.py       # InventoryAgent
│   └── budget.py          # BudgetAgent
│
├── governance/
│   ├── interceptor.py     # GovernanceInterceptor — the core layer
│   ├── policy_engine.py   # loads + evaluates rules from YAML
│   └── audit_log.py       # SQLite-backed decision log
│
├── protocol/
│   └── a2a.py             # A2A protocol simulation (AgentCard, Task, Bus)
│
├── config/
│   └── policies.yaml      # governance rules — edit without touching code
│
├── data/
│   ├── suppliers.json      # approved supplier catalog
│   ├── inventory.json      # component stock levels
│   └── budget.json         # departmental budget allocations
│
├── dashboard/
│   └── app.py             # Streamlit dashboard
│
├── tests/
│   └── test_all.py        # 19 tests covering agents + governance
│
└── main.py                # CLI demo runner
```

---

## Demo scenarios

Run all four scenarios at once with `python main.py`, or pick one:

```bash
python main.py --scenario approved   # small orders, fully automated
python main.py --scenario escalate   # Finance gets notified
python main.py --scenario blocked    # agent is stopped
python main.py --scenario reorder    # full inventory sweep
```

**What to watch for in the output:**

- `[COMPLETED]` in green — agent decision approved and executed
- `[ALERT — ESCALATE]` in yellow — went through but a human was notified
- `[BLOCKED]` in red — governance stopped it before the agent could act
- The audit log summary at the end shows the full breakdown

---

## Editing governance rules

Open `config/policies.yaml`. Everything a supply chain ops manager would want to tune is there:

```yaml
spending_limits:
  escalate_above: 50000    # notify Finance above this
  block_above: 200000      # hard stop above this

approved_suppliers:
  - "TechParts Inc"
  - "Global Components Ltd"
  # add or remove suppliers here
```

Restart the app to pick up changes. No Python required.

---

## Running tests

```bash
pytest tests/ -v
```

19 tests covering policy evaluation, all three agents, and audit logging. Each test spins up a fresh SQLite DB in a temp directory so tests are fully isolated.

---

## Design decisions

**Why is the governance layer separate from the agents?**

The agents are designed to make good business decisions — pick the cheapest supplier, flag low stock, check the budget. They shouldn't also be responsible for enforcing company policy. Keeping these concerns separate means you can update governance rules (or swap the policy engine entirely) without touching agent logic.

**Why YAML for policy rules?**

So that a supply chain ops manager or Finance lead can read and edit them without needing a developer. The goal is for governance to be owned by the business, not the engineering team.

**Why SQLite for the audit log?**

Zero setup, portable, queryable with standard SQL tools. In production you'd replace this with BigQuery, Cloud Spanner, or any append-only store — the `AuditLog` class is the only thing that would change.

**Why simulate A2A instead of using the real SDK?**

The real A2A protocol communicates over HTTP between independently deployed services. Simulating it in-process makes the demo runnable with a single `python main.py` command, while keeping the same architectural patterns (AgentCard, Task lifecycle, message routing) that the real protocol uses.

---

## The niche: the governance layer

The core idea of this project is not the agents — it's the **governance layer that sits between them**.

The agents (Inventory, Procurement, Budget) are intentionally simple rule-based systems. They represent any autonomous process that makes decisions: an LLM, a workflow, an RPA bot, or a human-facing form. The point is that **the governance layer works regardless of what the agents are doing inside**.

This is the pattern that's missing from most multi-agent deployments:

```
without SCAG:  Agent ──────────────────────────► Action (no visibility, no control)

with SCAG:     Agent ──► GovernanceInterceptor ──► Action
                               │
                         PolicyEngine (YAML rules)
                         AuditLog (every decision logged)
                         Escalation queue (human-in-the-loop)
```

You can drop this governance layer onto any agent network — without modifying the agents — and immediately get auditability, policy enforcement, and human escalation.

---

## Using this with real data (personal and enterprise use)

The static JSON files in `data/` are placeholders for demo purposes. For personal or enterprise use, they can be replaced with live feeds from real platforms. **The governance layer, policy engine, and audit trail are completely unaffected by this change.**

| File | What to replace it with |
|---|---|
| `data/budget.json` | SAP S/4HANA, Oracle Fusion ERP, NetSuite, Microsoft Dynamics 365 (cost center APIs) |
| `data/inventory.json` | SAP MM, Oracle SCM, Fishbowl, Zoho Inventory (stock level APIs) |
| `data/suppliers.json` | Coupa, Ariba, Jaggaer, Oracle Procurement (approved vendor APIs) |

The recommended approach is a pluggable data adapter per agent — `LocalJSONAdapter` for dev/demo, a platform-specific adapter in production. See `BLUEPRINT.md → Phase 5` for the full adapter pattern and example API endpoints.

---

## What's next

A few directions this could go in a production context:

- **Real LLM reasoning** — swap the rule-based agent logic for LLM calls (the `handle()` interface stays the same)
- **Real A2A endpoints** — deploy each agent as an HTTP service using the actual A2A SDK
- **Live data integration** — replace JSON files with ERP/procurement platform APIs via adapters (see Phase 5 in BLUEPRINT.md)
- **Webhook alerts** — wire the `alert_callback` to Slack, PagerDuty, or email
- **Policy versioning** — track changes to `policies.yaml` in git so there's a history of who changed what threshold and when

---

## Context

This project was built to explore the governance gap in multi-agent supply chain systems — specifically the question of how enterprises can deploy AI agents with confidence when those agents are making decisions that affect real procurement spend.

The Agent2Agent protocol, launched by Google in April 2025, makes it easy for agents to talk to each other across frameworks and vendors. What it doesn't provide is a standard for oversight, auditability, and human-in-the-loop controls. This project is a prototype of what that layer could look like.

---

## License

MIT
