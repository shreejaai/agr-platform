# AGR Platform — Full Analysis: Audience, Use Cases, Gaps, Roadmap

**Date:** 2026-03-27
**Author:** Navneet (Shreeja AI)
**Purpose:** Strategic planning + investor/co-founder communication

---

## 1. What AGR Is

**One line:** AGR is the authorization layer for AI agents — the same way AWS IAM controls what humans and services can do, AGR controls what AI agents can do.

**The core problem:** Every AI agent today runs with root access. LangGraph, CrewAI, AutoGen — they call tools (delete files, transfer money, deploy code, query databases) with zero policy enforcement between the LLM decision and the real-world action. AGR is the missing enforcement layer.

```
Agent wants to execute tool
      ↓
AGR evaluates: is this allowed?
      ↓
ALLOW → execute
DENY → block with reason
APPROVAL_REQUIRED → pause, email a human, resume on decision
```

**Technical differentiators:**
- **Cedar policies** — industry-standard, formally verified policy language (built by AWS)
- **Risk scoring** — dynamic, per-org configurable, 6-factor model running after Cedar
- **Hash-chained audit log** — tamper-evident, cryptographically verifiable, compliance-ready
- **Drop-in integration** — one decorator (`@agr_governed`) wraps any LangGraph/CrewAI tool
- **Human-in-the-loop** — built-in approval workflows with email links, quorum support, SLA escalation

**Market timing:** EU AI Act enforcement begins 2025. SOC2 auditors are starting to ask about AI agent controls. Companies are deploying agents in production but have no governance story.

---

## 2. Who Can Use AGR — Audience Segments

### Segment 1: AI Engineering Teams at Mid-to-Large Companies
**Who:** Teams building internal AI agents at fintech, healthcare, or enterprise SaaS companies.
**Pain:** Agents are in production but the CISO/legal team is asking "how do we know what the agent did and why?" They have no answer.
**How they use AGR:** Install SDK → wrap tools with `@agr_governed` → point to org API key. Done in an afternoon.
**Buying signal:** "We have agents in prod and need to pass a SOC2 audit."

### Segment 2: Platform / DevOps Teams Managing AI Infrastructure
**Who:** The team that owns the AI tooling platform inside a larger org.
**Pain:** 10 different teams building agents with 10 different "we'll handle safety ourselves" approaches.
**How they use AGR:** Deploy one central AGR instance, enforce org-wide Cedar policies, give each team an API key with scoped trust levels.
**Buying signal:** "We need a standardised way to govern all our AI agents."

### Segment 3: Regulated Industry Teams — Finance, Healthcare, Legal, Government
**Who:** A bank's automation team, a hospital's AI ops team, a legal tech company.
**Pain:** They cannot deploy agents without proving human oversight, audit trails, and compliance with EU AI Act / HIPAA / SOC2.
**How they use AGR:** Multi-step quorum approvals, compliance summary reports, hash-chain verification, CSV audit export for auditors.
**Buying signal:** "We have a regulatory audit in Q3 and our agents need to be compliant."

### Segment 4: AI-Powered SaaS Companies Building for Customers
**Who:** Companies building AI products where their customers run agents.
**Pain:** Enterprise customers demand AI governance controls before signing.
**How they use AGR:** Multi-tenant architecture — each of their customers gets an org with their own policies, audit log, approvals. AGR becomes their "enterprise AI governance" feature.
**Buying signal:** "Our enterprise prospects are asking about AI governance controls before they'll sign."

### Segment 5: Security / Compliance Teams (Buyers, Not Builders)
**Who:** CISO, Head of Compliance, or Risk Officer at a company using AI agents.
**Pain:** They didn't build the agents but they're accountable for what they do.
**How they use AGR:** Dashboard-only. Review approvals, check compliance summary, export audit logs, set risk thresholds. No code needed.
**Buying signal:** "We need a dashboard where our compliance team can see what our AI agents are doing."

### Segment 6: AI Safety Researchers / Red-Teamers
**Who:** Academic labs, AI safety organisations, red-team consultancies.
**Pain:** Need to test and simulate agent behaviour under policy constraints.
**How they use AGR:** Policy simulation endpoint, conflict detection, decision traces.
**Buying signal:** Lower priority commercially; strong for credibility and community.

### Ideal Customer Profile (ICP)
> A 50–500 person company in fintech, healthcare, or enterprise SaaS that has shipped AI agents to production and faces a compliance audit or enterprise customer asking about AI governance. They have an AI engineering team and a security/compliance function. They'll pay $500–5,000/month.

---

## 3. How They Use AGR — Key Use Cases

| Use Case | Who | Key Features Used |
|----------|-----|-------------------|
| Wrap agent tools with policy enforcement | AI engineers | SDK `@agr_governed`, evaluate endpoint |
| Write policies in natural language | Policy authors | Copilot chat |
| Approve/reject sensitive agent actions | Approvers | Email links, approval dashboard |
| Monitor agent behaviour | Ops/security | Dashboard, audit log, Prometheus metrics |
| Pass a compliance audit | CISO/compliance | Compliance summary, audit export, hash verify |
| Set risk thresholds per org | Admins | Risk config API/UI |
| Register and trust-level agents | Platform teams | Agent registration, trust levels |
| Export policies for backup / CI | DevOps | Policy import/export, SDK |
| Simulate a policy before activating | Policy authors | Simulate endpoint |
| Investigate a specific incident | Security teams | Audit search, decision trace |

---

## 4. Gap Analysis

### 🔴 CRITICAL — Product Promise Broken Without These

1. **Cedar CLI not wired end-to-end**
   The value prop is "Cedar policy enforcement." Currently falls back to Python regex. Cedar is what makes AGR formally verifiable and enterprise-credible. Fix before any serious customer evaluation.

2. **No public API docs / OpenAPI generation**
   Well-designed API, working SDK, but no browsable docs. Developers cannot self-onboard. Every enterprise eval starts with "can I see your API docs?"

3. **Temporal not wired end-to-end**
   Approval SLA escalation, durable workflows, guaranteed delivery — none work without Temporal. The DB fallback means approvals can get stuck silently. Blocker for regulated industries.

4. **No org/team management API or UI**
   Role changes require direct DB access. No "invite a team member" flow. A CISO cannot be onboarded to the dashboard without engineering help. Blocker for every enterprise deal.

### 🟠 HIGH — Significantly Limits Growth or Revenue

5. **Python SDK is sync-only** — Blocks the event loop in async LangGraph/CrewAI contexts. Production bug waiting to happen.

6. **No dashboard UI for policy simulation** — `POST /v1/policies/simulate` exists but is buried in the API. Best activation feature needs to be in the dashboard.

7. **No risk score breakdown UI** — API returns `risk_factors` but dashboard shows nothing. Governance teams need to understand *why* an action was flagged.

8. **No getting started / onboarding flow** — New users with an API key have no guided path. Kills activation.

9. **Approval dashboard is incomplete** — Multi-step approval UI, quorum type, SLA config only possible via API.

10. **No TypeScript/JavaScript SDK docs or examples** — TS SDK exists but is undocumented. Frontend teams cannot self-onboard.

### 🟡 MEDIUM — Quality and Completeness Issues

11. **Compliance hooks are advisory with no remediation guidance** — Flags violations but doesn't say how to fix them.

12. **No bulk policy management in dashboard** — Import/export exists in API/SDK but not dashboard.

13. **No agent activity timeline per agent** — No dedicated per-agent history view.

14. **Webhook delivery failure UI** — No retry/history panel in dashboard.

15. **No eval count / rate limit visibility in dashboard** — Users hit 429 without warning.

16. **No plugin for OpenAI Agents SDK / Google ADK / AutoGen** — Fastest-growing frameworks have no plugin.

17. **Copilot upgrade path is unclear** — Upgrade URL hardcoded to `agr.dev/pricing` which may not be live. Wastes conversion moments.

### 🟢 LOW — Nice to Have

18. No CLI tool (`agr-cli`)
19. No GitHub Action for policy-as-code
20. No Terraform provider
21. No Slack approval bot
22. No SDKs for Go / Java / Ruby / Node
23. No mobile-responsive approval page
24. Rollback scripts missing for migrations 014 and 015

---

## 5. New Features Roadmap

### Theme 1: Developer Experience
- **Async Python SDK** — `AsyncAGRClient` with `await client.evaluate()`
- **OpenAI Agents SDK plugin** — `@agr_governed` adapted to OpenAI tool pattern
- **Google ADK plugin** — Same for Google Agent Development Kit
- **`agr-cli`** — `agr policy list`, `agr policy simulate`, `agr audit export`
- **GitHub Action `agr-policy-check`** — Validate Cedar policies on PR

### Theme 2: Dashboard Completeness
- **Policy Simulator UI** — Choose agent, action, resource, context → see decision + reason + risk breakdown
- **Risk Score Breakdown Panel** — Inline factor breakdown wherever risk scores appear
- **Agent Activity Timeline** — Per-agent view: decisions over time, risk trend, deny rate
- **Eval Usage Meter** — "743/1,000 evaluations used" with 80% warning and upgrade CTA
- **Approval Workflow Manager** — Full UI for steps, quorum, SLA, escalation

### Theme 3: Enterprise Features
- **Team Management — Invite & Roles** — Email invite → role select → Clerk onboarding
- **SSO / SAML via Clerk** — Enterprise checkbox; unblocks large company deals
- **Compliance Report Export (PDF)** — One-click auditor-ready report
- **Audit Anomaly Detection** — Background alerts for unusual agent patterns
- **Multi-org / Sub-org Hierarchy** — Parent policies inherited by child orgs

### Theme 4: Ecosystem & Integrations
- **Slack Approval Bot** — Approve/reject from Slack message buttons
- **PagerDuty / OpsGenie Integration** — Incident trigger on critical-risk deny or SLA breach
- **Policy Template Library** — Curated Cedar policy packs for finance, healthcare, infra
- **Webhook Replay & Retry UI** — See delivery history, replay failed deliveries

### Theme 5: AI-Native Features (Longer Term)
- **Natural Language Policy Testing in Copilot** — "Test this policy against 5 scenarios"
- **Dynamic Agent Trust Scoring** — Trust score computed from actual behaviour history
- **Policy Conflict Auto-Resolver** — Copilot suggests merges for conflicting policies
- **Evaluation Explanation API** — Plain English explanation of any past decision

---

## 6. Prioritisation — 4 Waves

### Wave 1 — Fix Before Any Customer Evaluation (2–4 weeks)
| Item | Effort |
|------|--------|
| Wire Cedar CLI end-to-end | 3–5 days |
| Async Python SDK | 2–3 days |
| OpenAPI docs + Swagger UI | 1–2 days |
| Team invite + role UI | 2–3 days |
| Policy Simulator UI in dashboard | 2–3 days |
| Eval usage meter in dashboard | 1 day |

### Wave 2 — First Paying Customers (Weeks 4–8)
| Item | Effort |
|------|--------|
| Risk score breakdown UI | 2 days |
| Approval workflow manager UI | 3 days |
| Compliance PDF export | 2–3 days |
| Policy Template Library | 2 days |
| OpenAI Agents SDK plugin | 2 days |
| Wire Temporal end-to-end | 4–6 days |

### Wave 3 — Grow to $10k MRR (Weeks 8–16)
| Item | Effort |
|------|--------|
| Slack approval bot | 3–4 days |
| Agent activity timeline | 2–3 days |
| `agr-cli` | 3–4 days |
| SSO / SAML via Clerk | 2–3 days |
| Audit anomaly detection | 4–5 days |
| Google ADK plugin | 1–2 days |

### Wave 4 — Enterprise & Ecosystem (Beyond 16 weeks)
- Dynamic agent trust scoring
- Multi-org / sub-org hierarchy
- GitHub Action for policy-as-code
- Terraform provider
- Natural language policy testing in Copilot
- Evaluation Explanation API

### The One-Line Strategy
> Fix the core engine (Cedar) → make developers self-serve (docs + async SDK + simulator) → close first enterprise deals (team management + compliance export + Temporal) → grow through ecosystem (plugins + Slack + CLI).

---

## 7. Competitive Positioning

AGR sits at the intersection of three trends:
1. **AI agents going to production** — every company deploying agents needs a governance story
2. **AI regulation becoming law** — EU AI Act, emerging US frameworks, enterprise security questionnaires
3. **Cedar becoming the standard** — AWS-backed, formally verified, increasingly adopted

The moat builds over time: every policy, every audit event, every risk calibration is org-specific data that makes the system more accurate and harder to replace. The Copilot layer (natural language → Cedar policy) is the wedge for non-technical governance teams.

---

*Generated: 2026-03-27 | AGR Platform v0.1.0*
