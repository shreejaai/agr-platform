# AGR — Agentic Governance Runtime
### Product Brief · shreejaai.com

---

## What It Is

**AGR is a drop-in governance layer for AI agents.**

Every time your AI agent tries to do something — transfer funds, access patient data, deploy code, send an email — AGR evaluates that action against your policies *before* it executes. If it's allowed, the agent proceeds. If it's risky, a human reviews it. If it's blocked, it stops. Every decision is logged in a tamper-proof audit trail.

One line of code in your agent. Complete control over what it can do.

```python
result = agr.evaluate(agent="finance-bot", action="transfer_funds",
                       resource="account:123", context={"amount": 500000})
if result.requires_approval:
    agr.wait_for_approval(result.approval_id)
```

---

## The Problem

Every company deploying AI agents faces the same gap:

- Agents can execute actions with real business consequences — financial transactions, data access, infrastructure changes
- There is no standard layer between "agent decides to act" and "action executes"
- Compliance teams have no visibility, no audit trail, no controls
- One rogue agent action = a regulatory incident, a security breach, or a PR crisis

Teams today bolt this together manually — custom middleware, spreadsheet approvals, ad-hoc logging. It breaks. It doesn't scale. It doesn't satisfy auditors.

---

## What AGR Does

| Capability | What It Means |
|---|---|
| **Policy enforcement** | Cedar rules evaluated on every tool call. ALLOW, DENY, or route to human approval. |
| **Risk scoring** | Deterministic 0–100 score per action. High-risk actions auto-escalate. |
| **Human-in-the-loop** | Approval requests routed via email + Slack. 48-hour durable workflow. |
| **Audit log** | SHA-256 hash-chained, append-only. Cryptographically verifiable. |
| **Compliance hooks** | Built-in checks for EU AI Act Art.13, SOC2 CC6.1, ISO 42001. |
| **Framework-native SDKs** | LangChain, LangGraph, CrewAI, and plain Python/TypeScript. |
| **Dashboard** | Full UI for policies, approvals, agents, audit review, and team management. |

---

## Who It's For

**Primary buyers:** Engineering leaders and compliance officers at companies deploying autonomous AI agents in regulated or high-stakes environments.

**Best fit:**
- **FinTech** — AI agents handling transactions, credit decisions, fraud analysis
- **Healthcare** — AI agents accessing patient records, generating clinical summaries
- **Enterprise SaaS** — AI agents with write access to customer data or production systems
- **DevOps/Platform teams** — AI agents deploying code, modifying infrastructure

**Champion persona:** The engineering lead or CTO who has already shipped an AI agent and is now being asked by legal or compliance: *"How do we prove what the agent did and why?"*

---

## Why Now

The EU AI Act enters enforcement in 2026. SOC2 auditors are starting to ask about AI systems. Every enterprise deploying LLM agents is one incident away from a governance crisis. The teams building with LangChain and CrewAI today have no governance layer — they are building it themselves, badly, one at a time.

AGR is the first purpose-built governance runtime for AI agents with a complete stack: policy engine, approval workflow, audit trail, and SDK integrations — ready to deploy in a day.

---

## Pricing

| Plan | Evaluations | Price | Best For |
|---|---|---|---|
| **Developer** | 100 / week | Free | Evaluation, prototypes |
| **Startup** | 1,000,000 / mo | $49 / mo | Early-stage teams |
| **Business** | Unlimited | $199 / mo | Growing teams, SLA included |
| **Enterprise** | Unlimited | Custom | On-prem, SAML SSO, dedicated support |

Annual plans: 20% discount. On-prem deployment available.

---

## What You Get Out of the Box

- REST API + Python SDK + TypeScript SDK
- Pre-built policy packs: FinTech, DevOps, Healthcare, Security
- Dashboard for non-technical stakeholders (compliance officers, managers)
- Email + Slack approval flows — no dashboard login required for approvers
- Docker Compose for local dev; production-ready containers for cloud deployment
- Multi-tenant from day one — one deployment, multiple teams

---

## Built By

**Navneet · Shreeja AI** · shreejaai.com

Solo founder. Full-stack platform: FastAPI backend, Angular dashboard, Python + TypeScript SDKs, 298 passing tests, zero linting errors, production-grade from day one.

*We are looking for design partners in FinTech and Healthcare. If your team is deploying AI agents and needs governance controls, we want to talk.*

**Contact:** navneet@shreejaai.com

---

*AGR — Agentic Governance Runtime · github.com/shreejaai/agr-platform*
