# SCAG — Project Blueprint

This document covers the full design rationale, stakeholder map, success metrics, failure modes, and production roadmap for the Supply Chain Agent Governance project.

---

## 1. Problem statement

### Background

Google and other large enterprises are deploying multi-agent AI systems to automate supply chain operations — procurement, inventory management, budget approval. The Agent2Agent (A2A) protocol (launched April 2025) has made agent-to-agent communication standardised and interoperable across frameworks and vendors.

### The gap

The protocol solves *how* agents communicate. It does not solve *whether they should have*. As of mid-2025, there is no standard for:

- Auditing what decisions agents made and why
- Enforcing policy limits on autonomous agent actions
- Routing decisions to humans when they exceed safe thresholds
- Giving non-technical stakeholders (Finance, Ops, Compliance) visibility into agent behaviour

### Consequence

Enterprises face a choice: either don't give agents real authority (which undermines the value of automation), or give them authority and hope they stay within acceptable bounds (which is not an acceptable governance posture for regulated or high-value operations).

This project demonstrates a third path: give agents real authority, but wrap that authority in a governance layer that enforces policy, logs everything, and escalates appropriately.

---

## 2. Scope

### In scope

- Three supply chain agents: Procurement, Inventory, Budget
- A2A-style message bus for agent communication
- Governance interceptor that evaluates every agent action
- Policy engine driven by a YAML config file
- Immutable audit log (SQLite)
- Human review dashboard (Streamlit)
- CLI demo runner with four scenarios
- Full test suite

### Out of scope (v1)

- Real LLM-powered agent reasoning
- Live HTTP-based A2A endpoints
- Integration with real ERP or procurement systems
- Multi-tenant governance (different policy sets per team)
- Role-based access control on the dashboard

---

## 3. Stakeholder map

| Stakeholder | What they care about | How this project serves them |
|---|---|---|
| Supply Chain Ops | Did the right orders get placed? | Dashboard shows every PO, its status, and which supplier was chosen |
| Finance | Did anything exceed our approval limits? | Escalation queue shows flagged items before money moves |
| Compliance / Legal | Can we prove what the agents did? | Audit log is immutable and queryable by task, verdict, or time |
| Engineering | How do I plug this into our existing agent stack? | Interceptor pattern — drop it onto any A2A bus without changing agents |
| Executive sponsor | What's the ROI? | Metrics: decisions automated, escalations caught, blocks prevented |

---

## 4. Success metrics

These are the metrics that would indicate the governance layer is working in production. For this prototype, they are simulated with the demo data.

| Metric | Target | How it's measured |
|---|---|---|
| Automation rate | >70% of decisions approved without human involvement | `audit_log.get_stats()` verdict breakdown |
| False positive rate | <5% of escalations deemed unnecessary by reviewers | Resolved escalations marked "reviewed, no action" |
| Mean time to resolve a block | <4 hours | Timestamp delta between block creation and resolution |
| Audit coverage | 100% of agent actions logged | All tasks pass through interceptor before delivery |
| Policy rule change cycle | <30 mins from decision to deployed | YAML file edit, restart app |

---

## 5. System design

### Message flow

```
Human or Inventory scan triggers a reorder
         │
         ▼
InventoryAgent.send("ProcurementAgent", "create_purchase_order", {...})
         │
         ▼
A2ABus.dispatch(task)
         │
         ▼
GovernanceInterceptor.intercept(task)          ← governance layer
    │         │         │
    ▼         ▼         ▼
APPROVED   ESCALATE  BLOCKED
    │         │         │
    │    log + alert  log + alert
    │    proceed      return blocked task
    │
    ▼
ProcurementAgent.handle(task)
    │
    ▼
ProcurementAgent.send("BudgetAgent", "approve_spend", {...})
    │
    ▼
GovernanceInterceptor.intercept(task)          ← every message intercepted
    │
    ▼
BudgetAgent.handle(task)
    │
    ▼
Task.complete(result) → returned to caller
```

### Key design choices

**Interceptor pattern, not middleware**

The governance layer is not built into the agents. It's registered as a callback on the message bus. This means:
- Agents can be developed and tested without governance
- Governance rules can change without touching agent code
- Multiple governance layers could be stacked if needed

**Policy as configuration, not code**

Rules live in `config/policies.yaml`. The policy engine reads them at startup (and can hot-reload). A Finance manager can change a spending threshold by editing one line. No pull request, no deployment.

**Audit-first design**

The audit log is written *before* the verdict is acted on. Even if the application crashes after logging, the record exists. This is the correct ordering for any system where auditability is a hard requirement.

**Fail-safe defaults**

If an action has no matching policy rule, it defaults to APPROVED. This prevents over-blocking legitimate operations during early rollout. In a production deployment, you'd invert this to BLOCKED by default once the rule set is mature.

---

## 6. Governance verdicts in detail

### APPROVED
Agent proceeds without any human notification. The decision is logged but doesn't appear in any alert queue.

Typical: small routine orders, budget checks within normal range, inventory updates.

### ESCALATE
Agent proceeds, but the decision is added to the escalation queue on the dashboard. A human reviews it within the agreed SLA (suggested: 4 hours during business hours). No action is required — this is informational unless the reviewer decides otherwise.

Typical: orders between $50k–$200k, budget utilisation above 80%, new item types not seen before.

### BLOCKED
Agent is stopped. The task returns with `state = BLOCKED` and the original action does not execute. The item appears in the "Blocked — human approval required" queue. A human must explicitly approve or reject it before the agent can retry.

Typical: orders above $200k, unapproved suppliers, order quantities that look like data errors.

---

## 7. Failure modes and mitigations

| Failure mode | Impact | Mitigation |
|---|---|---|
| Policy engine misconfigured | Orders blocked or escalated incorrectly | Config validation on startup; test suite covers boundary conditions |
| Audit log write fails | Decision not recorded | Write-before-act ordering; SQLite is local and reliable; production would use managed DB with replication |
| Agent bypasses the bus | No interception possible | In this design, agents can only communicate via the bus — there's no other channel |
| Policy file deleted or corrupted | Governance stops working | App fails to start if policy file is missing or invalid YAML |
| Human reviewer ignores escalation queue | High-value orders proceed without review | Dashboard shows unresolved count; could add email/Slack alert on ageing items |
| Agent makes correct decision that policy blocks | Operational delay | Policy rules have an ESCALATE tier specifically to avoid hard-blocking borderline cases |

---

## 8. Production roadmap

### Phase 1 — Foundation (this prototype)
- ✅ Three agents with realistic business logic
- ✅ A2A-style message bus
- ✅ Governance interceptor with three verdict tiers
- ✅ YAML-configurable policy engine
- ✅ SQLite audit log
- ✅ Streamlit dashboard
- ✅ CLI demo runner
- ✅ Test suite (19 tests)

### Phase 2 — Real agent reasoning
- Replace rule-based agent logic with LLM calls (Gemini via Vertex AI)
- Add chain-of-thought logging so the audit trail includes agent reasoning, not just outcomes
- Add confidence scores to agent decisions (low confidence → auto-escalate)

### Phase 3 — Real infrastructure
- Deploy each agent as an HTTP service using the actual A2A SDK
- Replace SQLite with BigQuery or Cloud Spanner for audit log
- Add Pub/Sub for alert delivery (Slack, PagerDuty, email)
- Move policy engine to a versioned config store (e.g. Google Cloud Config)

### Phase 4 — Enterprise hardening
- Role-based access control on the dashboard
- Multi-tenant policy sets (different rules for different teams or regions)
- Policy change audit trail (who changed what threshold and when)
- SLA tracking for escalation resolution times
- Reporting exports for quarterly compliance reviews

### Phase 5 — Live data integration (personal and enterprise use)

> **Note:** The governance layer is the core of this project — it works independently of where the data comes from. For personal or enterprise use, the static JSON files in `data/` can be replaced with live feeds from real platforms using a data adapter layer. The governance logic, policy engine, and audit trail remain unchanged.

#### What data can come from real platforms

| Data file | Platform examples | API / method |
|---|---|---|
| `budget.json` | SAP S/4HANA, Oracle Fusion ERP, NetSuite, Microsoft Dynamics 365 | OData / REST — cost center budgets, actuals, commitments |
| `inventory.json` | SAP MM, Oracle SCM, Fishbowl, Zoho Inventory | REST / SOAP — stock levels, reorder points, warehouse quantities |
| `suppliers.json` | Coupa, Ariba (SAP), Jaggaer, Oracle Procurement | REST — approved vendor lists, pricing, lead times |

#### Recommended adapter pattern

Instead of loading static JSON, each agent would use a pluggable data adapter:

```
BudgetAgent
  └── BudgetDataAdapter
        ├── LocalJSONAdapter      ← current (dev / demo)
        ├── OracleFusionAdapter   ← REST: /fscmRestApi/resources/.../budgetaryControlResults
        ├── SAPAdapter            ← OData: /sap/opu/odata/sap/ZCOSTCENTER_BUDGET_SRV/BudgetSet
        └── NetSuiteAdapter       ← SuiteQL query on budget vs. actuals

InventoryAgent
  └── InventoryDataAdapter
        ├── LocalJSONAdapter
        ├── SAPMMAdapter          ← OData: material stock per plant/storage location
        └── ZohoInventoryAdapter  ← REST: /api/v1/items

ProcurementAgent
  └── SupplierDataAdapter
        ├── LocalJSONAdapter
        ├── CoupaAdapter          ← REST: /api/business_entity/v2/suppliers
        └── AribaAdapter          ← REST: /api/approval/v1/purchase-orders
```

The adapter is injected at boot time via config — agent logic and governance layer stay identical across environments. This is the correct extension point because it keeps the governance concern (interceptor, policy engine, audit log) fully separate from the data sourcing concern.

---

## 9. Connection to Google's A2A ecosystem

This project is directly relevant to work Google is doing in 2025–2026:

**A2A protocol** — this project implements the core A2A concepts (AgentCard, Task lifecycle, message routing) in a self-contained simulation. The architectural patterns are the same as the real protocol; only the transport layer differs.

**Governance gap** — Google's own Agent Payments Protocol (AP2) documentation acknowledges that the A2A protocol does not include authorization controls. This project builds exactly that layer — policy-based authorization that wraps any A2A agent network.

**Supply chain context** — the A2A developer guide explicitly uses a supply chain scenario (kitchen manager agent coordinating with supplier agents) as its reference implementation. This project operates in the same domain with a more complete governance story.

**Agentspace and enterprise deployment** — Google's Agentspace platform provides governance, safety, and control features for A2A agents deployed to end users. This project demonstrates what that governance layer looks like at the infrastructure level, below the platform.

---

## 10. What this project demonstrates for a TPM role

Building this project required thinking through:

- **Requirements definition** — what does "governance" actually mean in an agent context? What are the three tiers and when does each apply?
- **Stakeholder needs** — Finance, Ops, Compliance, and Engineering all have different requirements from the same system; the design serves all four
- **Success metrics** — defining automation rate, false positive rate, and resolution time before writing any code
- **Failure mode analysis** — seven identified failure modes with explicit mitigations
- **Rollout planning** — four-phase production roadmap from prototype to enterprise deployment
- **Build vs buy decisions** — SQLite vs managed DB, YAML config vs code, in-process bus vs HTTP

These are program management decisions, not engineering decisions. The code is the proof of concept. The thinking above is the portfolio.

# added section 9: connection to Google A2A ecosystem and Agentspace platform

# added section 10: TPM portfolio framing — decisions made, not just code written
