# AGR Quickstart — First Evaluation in 5 Minutes

This guide walks you through authenticating, creating a policy, and running your first evaluation using the AGR API.

---

## Prerequisites

- AGR API running locally (`docker compose up`) or on a hosted instance
- `curl` installed (or Python 3.10+ / Node 18+ for SDK examples)
- Your API key (`agr_sk_...`) — see [Get Your API Key](#get-your-api-key) below

**Default local base URL:** `http://localhost:8000`

---

## 1. Health Check

Verify the API is up:

```bash
curl http://localhost:8000/v1/health
```

Expected:

```json
{"status": "ok", "version": "0.1.0"}
```

---

## 2. Get Your API Key

### SaaS / dashboard

Sign in at `https://dashboard.agr.dev`. Your API key is shown under **Settings → API Keys**.

### Local / on-prem (first boot)

```bash
docker compose up
# Watch the logs for:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AGR ON-PREM INITIALIZED
#  API Key: agr_sk_xxxxx
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Copy the key — it is only shown once.

Set it for this session:

```bash
export AGR_API_KEY="agr_sk_your_key_here"
export AGR_BASE="http://localhost:8000"
```

---

## 3. Create a Sample Policy

A `permit` policy allows a specific agent action. Paste this to create one:

```bash
curl -s -X POST "$AGR_BASE/v1/policies" \
  -H "Authorization: Bearer $AGR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "allow-read-tickets",
    "cedar_rule": "permit(principal, action == Action::\"read_ticket\", resource);",
    "description": "Allow agents to read support tickets.",
    "level": "org"
  }' | jq .
```

Expected (partial):

```json
{
  "id": "e2a7b3...",
  "name": "allow-read-tickets",
  "state": "active",
  ...
}
```

> **Note:** Without any active policies, all actions are denied by default.

---

## 4. Run Your First Evaluation

```bash
curl -s -X POST "$AGR_BASE/v1/evaluate" \
  -H "Authorization: Bearer $AGR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "support-agent-1",
    "action": "read_ticket",
    "resource": "ticket-42",
    "context": {"department": "support"}
  }' | jq '{decision, reason, risk_score, eval_id}'
```

Expected:

```json
{
  "decision": "ALLOW",
  "reason": "Action 'read_ticket' on 'ticket-42' is allowed by policy.",
  "risk_score": 5,
  "eval_id": "a1b2c3..."
}
```

---

## 5. Try a Blocked Action

Without a permit policy for `deploy`, the action is denied:

```bash
curl -s -X POST "$AGR_BASE/v1/evaluate" \
  -H "Authorization: Bearer $AGR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "support-agent-1",
    "action": "deploy",
    "resource": "prod-server",
    "context": {}
  }' | jq '{decision, reason}'
```

Expected:

```json
{
  "decision": "DENY",
  "reason": "No matching policy for 'deploy' on 'prod-server'. Denied by default."
}
```

---

## 6. Create an Approval-Required Policy

```bash
curl -s -X POST "$AGR_BASE/v1/policies" \
  -H "Authorization: Bearer $AGR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "deploy-requires-approval",
    "cedar_rule": "forbid(principal, action == Action::\"deploy\", resource) unless { context.approval_status == \"approved\" };",
    "description": "Production deploys require human approval.",
    "level": "org"
  }' | jq .id
```

Now evaluate:

```bash
curl -s -X POST "$AGR_BASE/v1/evaluate" \
  -H "Authorization: Bearer $AGR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "deploy-bot",
    "action": "deploy",
    "resource": "prod-server",
    "context": {},
    "approver_email": "ops@example.com"
  }' | jq '{decision, approval_id}'
```

Expected:

```json
{
  "decision": "APPROVAL_REQUIRED",
  "approval_id": "f8e9d0..."
}
```

---

## 7. Inspect Audit Trail

Every evaluation writes a hash-chained audit record:

```bash
curl -s "$AGR_BASE/v1/audit?limit=5" \
  -H "Authorization: Bearer $AGR_API_KEY" | jq '.[] | {event_type, agent_id, decision, created_at}'
```

---

## Python SDK

```python
import os
from agr import AGRClient

agr = AGRClient(
    api_key=os.environ["AGR_API_KEY"],
    base_url=os.environ.get("AGR_BASE_URL", "http://localhost:8000"),
)

result = agr.evaluate(
    agent="support-agent-1",
    action="read_ticket",
    resource="ticket-42",
    context={"department": "support"},
)

print(result.decision)   # ALLOW | DENY | APPROVAL_REQUIRED
print(result.risk_score) # 0-100
```

### Async (LangGraph / CrewAI)

```python
import asyncio
from agr import AsyncAGRClient

async def main() -> None:
    agr = AsyncAGRClient(api_key=os.environ["AGR_API_KEY"])
    result = await agr.evaluate(
        agent="langgraph-agent",
        action="write_database",
        resource="customer-records",
        context={"env": "production"},
    )
    print(result.decision)

asyncio.run(main())
```

---

## TypeScript / Node SDK

```typescript
import { AGRClient } from "@shreejaai/agr-sdk";

const agr = new AGRClient({
  apiKey: process.env.AGR_API_KEY!,
  baseUrl: process.env.AGR_BASE_URL ?? "http://localhost:8000",
});

const result = await agr.evaluate({
  agentId: "crewai-agent",
  action: "read_secret",
  resource: "vault/db-password",
  context: { env: "production" },
});

console.log(result.decision);   // "ALLOW" | "DENY" | "APPROVAL_REQUIRED"
console.log(result.riskScore);
```

---

## Next Steps

| Goal | Where to look |
|------|--------------|
| Policy authoring guide | `examples/policy_packs/` |
| Approval workflows | `docs/architecture.md` |
| Risk scoring config | `POST /v1/risk-config` |
| Compliance posture | `GET /v1/compliance` |
| Webhook integration | `POST /v1/webhooks` |
| Dashboard | `http://localhost:4200` |
| Interactive API docs | `http://localhost:8000/docs` |
| OpenAPI schema | `http://localhost:8000/openapi.json` |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `401 Unauthorized` | Missing or wrong API key | Check `Authorization: Bearer agr_sk_...` header |
| `decision: DENY` unexpectedly | No active policies match | Add a `permit` policy or check policy state |
| `429 Too Many Requests` | Evaluation limit hit | Check `GET /v1/org` for `eval_count` / `eval_limit` |
| `decision_trace.fallback_used: true` | Cedar CLI not on PATH | Install `cedar-policy-cli` for authoritative evaluation |

---

## Production Rollout Notes

### Migration 030 — `no_policy_action`

Migration `030_no_policy_action.sql` must be applied **before** deploying any backend build that includes the `no_policy_action` feature.

```bash
# Apply on the production database before rolling out the new backend image
psql $DATABASE_URL -f infra/migrations/030_no_policy_action.sql
```

Rollback: `infra/migrations/rollback/030_down.sql` drops the column and constraint.

**Default behaviour:** all existing orgs default to `deny`. No change to existing evaluation decisions until an admin explicitly changes the setting.

### `no_policy_action` — mode summary

| Mode | Effect when no policy matches |
|------|-------------------------------|
| `deny` (default) | Request blocked — same as pre-030 behaviour |
| `allow` | Request passes through; risk scoring and compliance checks still apply |
| `approval_required` | Request queued for human approval |

Change via API (admin only):
```bash
curl -X PATCH $AGR_BASE/v1/org/settings \
  -H "Authorization: Bearer $AGR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"no_policy_action": "allow"}'
```

Or use **Settings → Governance Settings** in the dashboard.

### Webhook reachability

`url_warning` is returned on every webhook read/create response. It is advisory — delivery is still attempted. The warning fires when the registered URL is a localhost or private-network address.

AGR delivers webhooks server-to-server from a remote host. To test locally:
- Use a public tunnel: [ngrok](https://ngrok.com), [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
- Or deploy a staging receiver on a public HTTPS endpoint

```bash
# Example: ngrok tunnel for local testing
ngrok http 3000
# Use the ngrok HTTPS URL as your webhook endpoint
```
