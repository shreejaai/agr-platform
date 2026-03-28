# AGR Live Demo Strategy
## Cover every feature. Close every question. In under 10 minutes.

---

## Three Demo Modes

| Mode | Audience | Time | Goal |
|------|---------|------|------|
| **Investor / Executive** | VCs, CEOs, non-technical buyers | 3 min | Show the problem → solution moment. One story. |
| **Technical Buyer (CTO/Lead)** | Engineering leads, architects | 8 min | Show everything works. Show integration simplicity. |
| **Self-Serve** | Anyone visiting the demo URL | Unlimited | Explore all scenarios interactively |

---

## Setup (Do Once)

### 1. Seed the demo environment
```bash
export AGR_API_KEY=agr_sk_...
export AGR_BASE_URL=https://your-deployed-agr.example.com
cd examples/demo
pip install httpx
python seed_demo.py
```

This creates: 5 policies, 4 agents, ~15 audit events, 2 pending approvals.

### 2. Open the interactive demo
```
examples/demo/interactive-demo.html
```
Open in Chrome. No server needed — it's pure HTML/JS that calls your AGR API directly.

Or serve with a direct URL:
```
interactive-demo.html?url=https://your-agr-url&key=agr_sk_...
```

### 3. Configure Resend (email) and Slack for the "approval email" wow moment
Set in your `.env`:
```
RESEND_API_KEY=re_...
DEMO_APPROVER_EMAIL=navneet@shreejaai.com   # your phone is checking this
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID=C...
```

---

## The 3-Minute Investor Demo (Script)

**One sentence before you start:** *"Let me show you what happens when an AI agent tries to do something it shouldn't."*

### Step 1 — Show the threat (30 seconds)
Open the demo. Point to the Sidebar.

> "This is a FinTech company. They have three AI agents — a finance bot, a DevOps bot, and an analytics bot. The agents can read accounts, transfer money, deploy code, export customer data. All real actions."

### Step 2 — The dangerous action (30 seconds)
Click **"Prompt Injection Detected"** in the sidebar.

> "Someone just compromised one of the agents. It's now trying to export your entire customer database. Without AGR, that export runs. Let me show you what happens with AGR."

Watch the result: **DENY — Blocked instantly.**

> "AGR evaluated that request in [X]ms. Policy said: any action with an injection score above 0.8 is blocked. Done. The agent never reached the database."

### Step 3 — The human-in-the-loop moment (60 seconds)
Click **"$50K Transfer → Approval Required"**.

> "Now here's the second scenario. The finance agent wants to transfer $50,000. That's within policy, but over the risk threshold — so it doesn't just run. It waits."

Point to the approval card that appears.

> "An email just went to the CFO's inbox. One click — approve or reject — right from the email. No dashboard login required. And here's the key thing..."

Click **"✓ Approve"** on the approval card.

> "That entire interaction — the original request, the risk score, who approved it, at what time — is in an immutable audit log. Cryptographically signed. Tamper-proof."

### Step 4 — The audit trail (30 seconds)
Switch to the **Audit Log** tab. Point to the hash chain.

> "This is what your compliance officer brings to the EU AI Act audit. Every decision, every approval, every block — with a hash chain that proves nothing was altered."

### Step 5 — One line of code (30 seconds)
Point to the stream panel showing the API call.

> "And this is how your engineering team plugs this in. One function call. Works with LangChain, LangGraph, CrewAI. The SDK handles the rest."

---

## The 8-Minute Technical Demo (Script + Sequence)

Go through these in order. Use the interactive demo for each.

### Minute 1 — ALLOW (fast path)
**Scenario:** Safe Account Read

Show the stream panel — one API call, 18ms response.

Key talking points:
- Redis cache — second call returns in <5ms
- Full decision trace in response
- Audit event written on every path

### Minute 2 — DENY (policy enforcement)
**Scenario:** $250K International Transfer Blocked

Show:
- Decision: DENY
- Risk score tab — high score from amount_scale + context_signals factors
- Raw response — `reason` field is human-readable

> "Your engineering team can use that reason field to show users why their action failed. You're not just blocking — you're explaining."

### Minute 3 — APPROVAL_REQUIRED (human loop)
**Scenario:** $50K Transfer

Show:
- Decision: APPROVAL_REQUIRED
- Approval card appears in the Approvals tab
- Email notification fires (show your phone if email is configured)
- Approve it live
- Audit event updates

> "The approval workflow runs in Temporal — so even if your server restarts, the workflow continues. The approval doesn't get lost."

### Minute 4 — Security (injection detection)
**Scenario:** Prompt Injection Detected

Show:
- Instant DENY — no human step needed for injection
- Risk score: 95+
- Stream: 12ms response

> "This is not ML-based detection — it's deterministic. If injection_score > 0.8, it's blocked. Always. No false negatives."

### Minute 5 — Risk Scoring
**Scenario:** After-Hours Production Deploy

Click the **Risk Score** tab.

Show the factor breakdown:
- action_severity: high (production deploy)
- context_signals: high (after hours)
- agent_trust: medium (provisional agent)

> "Every score is explainable. You can tell an auditor exactly why score was 82 — it's not a black box."

### Minute 6 — Compliance Posture
**Scenario:** Compliance Posture

Show the Compliance tab:
- EU AI Act Art. 13 — PASS (human oversight active)
- SOC2 CC6.1 — PASS (access controls enforced)
- ISO 42001 §8.4 — PASS (risk scoring enabled)

> "You can configure each standard to be advisory or blocking. Advisory means you see the finding but it doesn't stop the action. Blocking means a compliance violation stops execution."

### Minute 7 — Audit Chain
**Scenario:** Verify Audit Chain

Show the hash chain blocks.

> "SHA-256. Every event hashes the previous event. If anyone modifies a log entry — even changes a timestamp — the chain breaks and verification fails. This is what regulators want."

### Minute 8 — Integration
Show the raw SDK code:

```python
# That's it. This is the entire integration.
result = agr.evaluate(
    agent="finance-bot",
    action="transfer_funds",
    resource="account:123",
    context={"amount": 50000}
)
if result.requires_approval:
    agr.wait_for_approval(result.approval_id)
```

> "LangChain? One decorator. CrewAI? Same. Your team ships this in a day, not a sprint."

---

## Feature Coverage Checklist

Every feature demonstrated, mapped to demo scenario:

| Feature | Scenario | Tab | Time |
|---------|---------|-----|------|
| Policy enforcement (ALLOW) | Safe Account Read | Result | Min 1 |
| Redis cache hit | Safe Account Read (2nd run) | Stream | Min 1 |
| Risk scoring — 5 factors | Any DENY scenario | Risk Score | Min 2 |
| Policy enforcement (DENY) | $250K Intl Transfer | Result | Min 2 |
| Human-in-the-loop | $50K Transfer | Approvals | Min 3 |
| Email/Slack notification | $50K Transfer | (notification) | Min 3 |
| Temporal approval workflow | $50K Transfer | Result trace | Min 3 |
| Multi-step approve/reject | $50K Transfer → Approve | Approvals | Min 3 |
| Prompt injection detection | Prompt Injection | Result | Min 4 |
| After-hours policy | After-Hours Deploy | Result | Min 5 |
| Risk factor breakdown | After-Hours Deploy | Risk Score | Min 5 |
| Compliance — EU AI Act | Compliance Posture | Compliance | Min 6 |
| Compliance — SOC2 | Compliance Posture | Compliance | Min 6 |
| Compliance — ISO 42001 | Compliance Posture | Compliance | Min 6 |
| Advisory vs blocking mode | Compliance Posture | Compliance | Min 6 |
| SHA-256 hash chain | Verify Audit Chain | Audit | Min 7 |
| Audit log query | Any scenario | Audit tab | Min 7 |
| Tamper-proof verification | Verify Audit Chain | Audit | Min 7 |
| SDK — one line | (show code) | — | Min 8 |
| LangChain integration | (show code) | — | Min 8 |
| Raw API (request/response) | Any scenario | Request/Response | Any |
| PII export compliance | PII Data Export | Approvals | Extra |
| Approval rejection | Any approval | Approvals | Extra |
| Live API stream | (persistent) | Stream panel | Always |

---

## Questions Investors Ask — Answers

**"Who are your competitors?"**
> Cerbos and OPA enforce authorization for app APIs — general-purpose policy engines. AGR is purpose-built for the agent action loop: risk scoring, durable approval workflows, agent trust levels, framework-native SDKs. Nobody else has the Temporal + Cedar + audit chain combination in one product.

**"What's the market?"**
> Every company shipping LangChain agents today has this governance gap. LangChain alone has 10M+ monthly downloads. EU AI Act enforcement starts 2026. This is the new compliance category.

**"How do I know it's production-ready?"**
> 298 passing tests, mypy strict mode, zero linting errors, multi-tenant PostgreSQL RLS, full integration test suite. Show them the GitHub if they ask.

**"Why Cedar policies?"**
> Cedar is Amazon's open-source policy language, used in AWS Verified Permissions. It's purpose-built for authorization decisions — not a homegrown DSL. Open standard, auditable syntax, tool ecosystem.

**"What's your pricing?"**
> Developer (free), Startup ($49/mo), Business ($199/mo), Enterprise (custom). Annual is 20% discount. On-prem deployment for enterprises that can't use SaaS.

---

## Questions Technical Buyers Ask — Answers

**"What's the latency overhead?"**
> Cache hit: <5ms. Fresh Cedar evaluation: ~15–30ms. Approval creation: ~50ms including DB write + email trigger. Show them the stream panel latency numbers.

**"What if AGR goes down?"**
> Currently: evaluation fails closed (agents wait). Roadmap: embedded SDK evaluation mode with local policy cache. On-prem deployment removes the network dependency entirely.

**"Can we use our own Cedar policies?"**
> Yes — full Cedar syntax. Import from YAML files or write directly in the dashboard. Policy simulator lets you dry-run before activating. GitHub Action validates policies in CI.

**"How does multi-tenancy work?"**
> PostgreSQL Row-Level Security. Every query has `SET LOCAL app.current_org_id` injected at the session level — no org can ever see another org's data, even with a code bug.

**"What frameworks do you support?"**
> LangChain, LangGraph, CrewAI, plain Python, TypeScript. Generic `AGRPolicyEnforcer` wraps any function. Shows three lines of code.

**"Is Temporal required?"**
> No — graceful degradation. Without Temporal, approvals are DB-only (no durable workflows, no auto-escalation). Temporal adds: 48h durable workflow, automatic reminders, escalation signals. Recommended for production approval flows.

---

## The Demo URL Format

For sharing with prospects:
```
https://demo.shreejaai.com/demo?key=agr_sk_demo_readonly
```

The `?key=` param auto-fills the API key. Use a read-only scoped key for public demos.

For self-service:
```
https://demo.shreejaai.com/demo
```
User enters their own key — or you create a sandbox org per prospect.

---

## Pre-Demo Checklist (5 minutes before)

- [ ] AGR instance is running and healthy (`/health` returns OK)
- [ ] Demo environment seeded (`python seed_demo.py` completed)
- [ ] 2 pending approvals visible in the Approvals tab
- [ ] Email configured — you can see your inbox on your phone
- [ ] Slack configured — channel visible
- [ ] Chrome open, full screen, dark mode, no notifications
- [ ] API key entered, connection tested (green dot)
- [ ] Know which 3 scenarios you're leading with for this specific audience
