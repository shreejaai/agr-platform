# AGR — Agentic Governance Runtime

> Drop-in governance layer for AI agent frameworks. Every tool call is evaluated against Cedar policies before execution. Sensitive actions require human approval.

[![CI](https://github.com/shreejaai/agr-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/shreejaai/agr-platform/actions/workflows/ci.yml)

---

## What it does

```
Agent calls a tool
      ↓
agr.evaluate(agent, action, resource, context)
      ↓
Cedar policy engine
      ↓
Risk scoring engine (deterministic, 0-100)
      ↓
Compliance hooks (advisory — EU AI Act, SOC2, ISO 42001)
      ↓
      ├── ALLOW             → agent executes immediately
      ├── DENY              → agent is blocked
      └── APPROVAL_REQUIRED → human reviews in dashboard or email
```

- **Policy engine** — Cedar rules evaluated on every tool call. Python regex fallback if Cedar CLI not installed.
- **Risk scoring** — Deterministic 0–100 score from 5 weighted factors. Upgrades ALLOW → APPROVAL_REQUIRED or DENY.
- **Compliance hooks** — Advisory-only plugin framework. Built-in: EU AI Act Art.13, SOC2 CC6.1, ISO 42001 §8.4.
- **Human-in-the-loop** — Approval requests → Temporal durable workflow → email + Slack one-click approve/reject.
- **Audit log** — SHA-256 hash-chained, append-only, monthly partitioned. Verifiable via `GET /v1/audit/verify`.
- **Webhooks** — HMAC-SHA256 signed push on every approval decision (3× retry with backoff).
- **Dashboard** — Angular 17 UI for policies, approvals, agents, audit log, webhooks.
- **Policy packs** — Pre-built YAML policy sets for FinTech, DevOps, Healthcare/HIPAA, EU AI Act, and more.

---

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/shreejaai/agr-platform.git
cd agr-platform
cp .env.example services/agr-api/.env
# Edit .env — fill in SECRET_KEY at minimum
```

### 2. Start infrastructure

```bash
docker compose up -d postgres redis
```

### 3. Run migrations

```bash
for f in infra/migrations/0*.sql; do
  echo "Running $f..."
  psql postgresql://agr:password@localhost:5432/agr_dev -f "$f"
done
```

### 4. Create your first org + API key

```bash
psql postgresql://agr:password@localhost:5432/agr_dev -c "
INSERT INTO organizations (id, name, slug, api_key)
VALUES (
  gen_random_uuid(), 'My Org', 'my-org',
  'agr_sk_' || encode(gen_random_bytes(24), 'hex')
)
RETURNING id, api_key;
"
```

### 5. Start the API

```bash
cd services/agr-api
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API: http://localhost:8000 · Docs: http://localhost:8000/docs

### 6. Start the dashboard

```bash
cd apps/agr-dashboard
npm install
npm start   # http://localhost:4200
```

Go to **Settings** → paste your `agr_sk_` API key.

---

## API usage

```bash
export AGR_KEY=agr_sk_your_key_here

# Evaluate a tool call
curl -X POST http://localhost:8000/v1/evaluate \
  -H "Authorization: Bearer $AGR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-agent",
    "action":   "deploy",
    "resource": "production-server",
    "context":  {"environment": "production"}
  }'
# → {"decision": "APPROVAL_REQUIRED", "approval_id": "..."}

# Approve
curl -X POST http://localhost:8000/v1/approvals/{id}/approve \
  -H "Authorization: Bearer $AGR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"decided_by": "alice@example.com"}'

# Verify audit chain integrity
curl -H "Authorization: Bearer $AGR_KEY" http://localhost:8000/v1/audit/verify
# → {"valid": true, "total": 42}
```

---

## Python SDK

```bash
pip install -e packages/agr-sdk-python
```

```python
from agr import AGRClient

agr = AGRClient(api_key="agr_sk_...", base_url="http://localhost:8000")

result = agr.evaluate(
    agent="my-agent",
    action="deploy",
    resource="production-server",
    context={"environment": "production"},
)

if result.requires_approval:
    approved = agr.wait_for_approval(result.approval_id, timeout=3600)
    if not approved:
        raise RuntimeError("Deploy rejected.")
```

LangGraph plugin:

```python
from agr.plugins.langgraph import agr_governed

@agr_governed(agr_client=agr, agent_id="my-agent")
def web_search(query: str) -> str:
    ...
```

---

## TypeScript SDK

```bash
cd packages/agr-sdk-ts && npm install && npm run build
```

```typescript
import { AGRClient } from './dist'

const agr = new AGRClient({ apiKey: 'agr_sk_...', baseUrl: 'http://localhost:8000' })

const result = await agr.evaluate({
  agentId: 'my-agent', action: 'deploy',
  resource: 'production-server', context: { environment: 'production' },
})

if (result.requiresApproval) {
  const approved = await agr.waitForApproval(result.approvalId!)
}
```

---

## Risk scoring

Every `evaluate` call returns a risk score (0–100) alongside the policy decision:

```json
{
  "decision": "APPROVAL_REQUIRED",
  "risk_score": 72,
  "risk_level": "high",
  "risk_factors": {
    "action_severity": 60, "context_signals": 80,
    "rate_pattern": 20, "agent_trust": 40, "amount_scale": 0
  }
}
```

Configure thresholds in `.env`:
```bash
RISK_THRESHOLDS_ALLOW_MAX=30       # scores above this trigger APPROVAL_REQUIRED
RISK_THRESHOLDS_APPROVAL_MAX=70    # scores above this trigger DENY
RISK_SCORING_ENABLED=true
```

---

## Policy import/export

```bash
# Export all policies
curl -H "Authorization: Bearer $AGR_KEY" http://localhost:8000/v1/policies/export > policies.json

# Import from JSON (dry run first)
curl -X POST http://localhost:8000/v1/policies/import \
  -H "Authorization: Bearer $AGR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"policies": [...], "dry_run": true}'

# Import a pre-built policy pack
curl -X POST http://localhost:8000/v1/policies/import \
  -H "Authorization: Bearer $AGR_KEY" \
  -H "Content-Type: application/x-yaml" \
  --data-binary @examples/policy_packs/fintech.yaml
```

---

## Running tests

```bash
cd services/agr-api
source .venv/bin/activate
pytest -v                          # all tests (SQLite in-memory)
pytest tests/unit -v
pytest tests/integration -v
ruff check . && ruff format --check .
mypy app/

# PostgreSQL-specific tests (RLS, partitioning, JSONB)
docker-compose -f docker-compose.test.yml up -d postgres-test
PG_TEST_URL=postgresql+asyncpg://agr_test:agr_test_password@localhost:5433/agr_test \
  pytest tests/postgres/ -v
```

---

## Repo structure

```
agr-platform/
├── apps/agr-dashboard/     Angular 17 dashboard (port 4200)
├── services/agr-api/       FastAPI governance API (port 8000)
│   └── tests/postgres/     PostgreSQL integration tests (RLS, partitioning, JSONB)
├── packages/
│   ├── agr-core/           Cedar policy engine + Python regex fallback
│   ├── agr-sdk-python/     Python SDK
│   └── agr-sdk-ts/         TypeScript SDK (ESM + CJS)
├── infra/migrations/       Forward migrations 001–013
│   └── rollback/           Rollback scripts
├── examples/               Demo scripts (curl, Python, TypeScript) + policy packs
└── docker-compose.yml      postgres + redis + agr-api + agr-dashboard
```

---

## Environment variables

See [`.env.example`](.env.example) for the full reference.

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✓ | PostgreSQL async connection string |
| `SECRET_KEY` | ✓ | HMAC key for email tokens — `openssl rand -hex 32` |
| `REDIS_URL` | — | Redis for eval cache + rate limiting |
| `TEMPORAL_HOST` | — | Temporal server — empty = DB-only approvals |
| `RESEND_API_KEY` | — | Resend — empty = approval emails disabled |
| `SLACK_BOT_TOKEN` | — | Slack Bot Token — empty = Slack disabled |
| `SLACK_CHANNEL_ID` | — | Slack channel ID — empty = Slack disabled |
| `CLERK_WEBHOOK_SECRET` | — | Svix signature — empty = skip verify (dev-safe) |
| `RISK_SCORING_ENABLED` | — | Enable risk scoring engine (default: `true`) |
| `RISK_THRESHOLDS_ALLOW_MAX` | — | Max score for ALLOW (default: `30`) |
| `RISK_THRESHOLDS_APPROVAL_MAX` | — | Max score before DENY (default: `70`) |

---

## Pricing

| Plan | Monthly evals | Price |
|---|---|---|
| Developer | 100/week | Free |
| Startup | 1,000,000 | $49/mo |
| Business | Unlimited | $199/mo |
| Enterprise | Unlimited | Custom |

---

**Built by [Shreeja AI](https://shreejaai.com)**
