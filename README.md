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
- **Human-in-the-loop** — Approval requests → Temporal durable workflow → email + verified Slack interactive approve/reject.
- **Audit log** — SHA-256 hash-chained, append-only, monthly partitioned. Verifiable via `GET /v1/audit/verify`.
- **Webhooks** — HMAC-SHA256 signed push on every approval decision (3× retry with backoff).
- **Dashboard** — Angular 17 UI for policies, approvals, agents, audit log, webhooks.
- **CLI** — Lightweight `agr` CLI for `eval`, `simulate`, and `policy apply` workflows.
- **CI validation** — GitHub Action validates changed policies and runs evaluation scenarios from YAML.
- **Policy packs** — Pre-built YAML policy sets for FinTech, DevOps, Healthcare/HIPAA, EU AI Act, and more.

---

## Quick Start

```bash
# 1. Start AGR
docker compose up --build

# 2. Sign in at http://localhost:4200 — your API key is auto-provisioned
#    Or for headless/CI setup:
source examples/curl/00_setup.sh

# 3. Run all demo scenarios
bash examples/curl/12_full_demo.sh
```

See [examples/](examples/) for Python SDK, TypeScript SDK, and policy pack examples.

## Policy Packs

Import pre-built governance rules for common scenarios:

```bash
# Preview what will be imported (dry run)
bash examples/curl/08_import_policies_yaml.sh

# Commit the import
bash examples/curl/08_import_policies_yaml.sh --commit
```

Available packs in [examples/policy_packs/](examples/policy_packs/):

| Pack | Policies | Use Case |
|------|----------|----------|
| `finance_controls.yaml` | 6 | Transfer limits, international blocks, vendor approval |
| `devops_controls.yaml` | 5 | Production deploy gates, DB deletion protection |
| `data_access_controls.yaml` | 5 | Export bans, confidential data approval |
| `security_signals.yaml` | 4 | Prompt injection defense, anomaly detection |
| `starter_pack.yaml` | 20 | All packs combined — import this to get started |

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

Generic framework hook:

```python
from agr import AGRPolicyEnforcer

enforcer = AGRPolicyEnforcer(agr, agent_id="my-agent")

@enforcer.wrap(
    action="deploy",
    resource="production-cluster",
    context=lambda version: {"environment": "production", "release_version": version},
)
def deploy_release(version: str) -> str:
    ...
```

---

## CLI

```bash
pip install -e packages/agr-sdk-python
pip install -e packages/agr-cli

export AGR_API_KEY=agr_sk_your_key_here
export AGR_BASE_URL=http://localhost:8000

agr eval \
  --agent deploy-bot \
  --action deploy \
  --resource production-cluster \
  --context '{"environment":"production"}'

agr simulate \
  --agent finance-bot \
  --action transfer_funds \
  --resource treasury-system \
  --context '{"amount":50000,"currency":"USD"}'

agr policy apply \
  --file examples/policy_packs/devops_controls.yaml \
  --dry-run
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

List curated templates for dashboard import:

```bash
curl -H "Authorization: Bearer $AGR_KEY" \
  http://localhost:8000/v1/policies/templates
```

---

## GitHub Action

Use the bundled action to validate changed policies and run evaluation scenarios in CI.

```yaml
name: AGR Policy Check

on:
  pull_request:
    paths:
      - 'policies/**'
      - '**/*.cedar'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: shreejaai/agr-platform/tools/github-action@main
        with:
          api-key: ${{ secrets.AGR_API_KEY }}
          policy-dir: policies/
          config-file: .github/agr-policy-check.yml
          changed-only: 'true'
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
│   ├── agr-cli/            Lightweight CLI package
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
| `DASHBOARD_BASE_URL` | — | Dashboard URL used in Slack approval deep links |
| `TEMPORAL_HOST` | — | Temporal server — empty = DB-only approvals |
| `RESEND_API_KEY` | — | Resend — empty = approval emails disabled |
| `SLACK_BOT_TOKEN` | — | Slack Bot Token — empty = Slack disabled |
| `SLACK_CHANNEL_ID` | — | Slack channel ID — empty = Slack disabled |
| `SLACK_SIGNING_SECRET` | — | Slack signing secret for interactive approve/reject |
| `SLACK_TEAM_ID` | — | Optional Slack workspace/team ID allowlist |
| `CLERK_WEBHOOK_SECRET` | — | Svix signature — empty = skip verify (dev-safe) |
| `RISK_SCORING_ENABLED` | — | Enable risk scoring engine (default: `true`) |
| `RISK_THRESHOLDS_ALLOW_MAX` | — | Max score for ALLOW (default: `30`) |
| `RISK_THRESHOLDS_APPROVAL_MAX` | — | Max score before DENY (default: `70`) |

---

## Examples

Runnable examples in [examples/](examples/):

| Directory | Description |
|-----------|-------------|
| `examples/curl/` | 12 curl scripts covering all major scenarios |
| `examples/python/` | Python SDK examples: quickstart, approvals, risk scoring, LangGraph, CrewAI |
| `examples/node/` | TypeScript SDK examples |
| `examples/policy_packs/` | Ready-to-import policy collections |

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
