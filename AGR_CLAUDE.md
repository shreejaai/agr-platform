# CLAUDE.md — AGR Platform

This file is read by Claude Code at the start of every session. It contains everything needed to work in this codebase without re-explanation.

**GROUND TRUTH ONLY. Every section reflects the actual code, not aspirations. Planned-but-not-built items are clearly marked `[NOT YET IMPLEMENTED]`.**

---

## What This Repo Is

**AGR (Agentic Governance Runtime)** — developer infrastructure. A drop-in governance layer for AI agent frameworks. Every agent tool call is evaluated against Cedar policies before execution. Sensitive actions (production deploys, DB drops) require human approval.

**This repo is the backend product only.** The frontend dashboard lives separately.

**Owner:** Navneet — solo founder, Shreeja AI (`shreejaai.com`)

---

## How It Works (Mental Model)

```
Agent calls a tool
      ↓
agr.evaluate(agent, action, resource, context)
      ↓
POST /v1/evaluate  [this repo]
      ↓
Redis cache check (60s TTL, key: eval:{org_id}:{sha256(agent+action+resource+context)})
  HIT  → return cached result (audit event written with "cached": True)
  MISS ↓
Cedar policy engine:
  If `cedar` binary on PATH → Cedar CLI subprocess (cedar authorize)
  Else → Python regex fallback evaluator
      ↓
ALLOW → return immediately, agent executes
DENY  → return immediately, agent does not execute
APPROVAL_REQUIRED → create approval_requests row in DB
                  → start Temporal workflow (if TEMPORAL_HOST configured)
                  → send Resend email with one-click approve/reject links (if RESEND_API_KEY set)
                  → SDK's wait_for_approval() polls GET /v1/approvals/{id} until resolved
                  → agent executes (if approved) or aborts (if rejected)
      ↓
Every path (except rate-limited) writes a hash-chained entry to audit_events
Result cached in Redis via BackgroundTask
eval_count synced to DB via BackgroundTask (Redis is authoritative for rate checks)
```

---

## Repo Structure (Actual Files)

```
agr-platform/
├── services/
│   └── agr-api/                        # The deployed FastAPI service
│       ├── app/
│       │   ├── main.py                 # FastAPI app + CORS + AuthMiddleware + all routers
│       │   ├── config.py               # pydantic_settings.BaseSettings — reads .env
│       │   ├── database.py             # Async SQLAlchemy engine (pool_size=20) + get_session()
│       │   ├── models.py               # ORM: Organization, Policy, ApprovalRequest, AuditEvent, Agent, Webhook
│       │   ├── schemas.py              # ALL Pydantic v2 request/response models (single file)
│       │   ├── routes/
│       │   │   ├── evaluate.py         # POST /v1/evaluate — core endpoint (Redis cache + rate limit)
│       │   │   ├── policies.py         # GET/POST/GET{id}/PATCH/DELETE /v1/policies
│       │   │   ├── approvals.py        # Full approval endpoints + email one-click flow
│       │   │   ├── audit.py            # GET /v1/audit (with filters)
│       │   │   ├── agents.py           # POST /v1/agents/register, GET /v1/agents (DB-backed)
│       │   │   ├── webhooks.py         # POST/GET/DELETE /v1/webhooks
│       │   │   ├── clerk.py            # POST /v1/clerk/webhook (Clerk user.created → org + policies)
│       │   │   └── health.py           # GET /health (no auth)
│       │   ├── services/
│       │   │   ├── cedar_service.py    # Load policies from DB + call policy_engine.evaluate_policies()
│       │   │   ├── approval_service.py # Create ApprovalRequest + start Temporal workflow
│       │   │   ├── audit_service.py    # Hash-chained append-only audit logger
│       │   │   ├── notification_service.py # HMAC-signed email tokens + Resend email
│       │   │   ├── org_service.py      # seed_default_policies() — 5 default Cedar rules
│       │   │   ├── redis_service.py    # Eval cache + rate limiting (atomic Redis INCR)
│       │   │   ├── temporal_service.py # Lazy Temporal client, start/signal workflow (graceful degradation)
│       │   │   └── webhook_service.py  # fire_approval_webhook() — HMAC-SHA256 signed POST
│       │   ├── workflows/
│       │   │   └── approval_workflow.py # Temporal ApprovalWorkflow — 48h wait + human_decision signal
│       │   ├── workers/
│       │   │   └── approval_worker.py  # Standalone Temporal worker process
│       │   └── middleware/
│       │       └── auth.py             # Bearer token → org lookup → request.state.org + request.state.org_id
│       ├── scripts/
│       │   └── migrate.py
│       ├── tests/
│       │   ├── conftest.py             # SQLite in-memory fixtures (NOT PostgreSQL)
│       │   ├── unit/
│       │   │   ├── test_audit_hash.py
│       │   │   ├── test_langgraph_plugin.py
│       │   │   ├── test_policy_engine.py
│       │   │   └── test_sdk_client.py
│       │   └── integration/
│       │       ├── test_evaluate.py
│       │       ├── test_approvals.py
│       │       ├── test_policies.py
│       │       └── test_multi_tenant.py
│       ├── requirements.txt
│       ├── Dockerfile
│       └── Dockerfile.dev
├── packages/
│   ├── agr-core/
│   │   ├── __init__.py
│   │   ├── policy_engine.py            # Cedar CLI subprocess + Python regex fallback
│   │   └── policies/
│   │       └── default.cedar           # 5 default Cedar policies (mirrored in org_service.py)
│   ├── agr-sdk-python/
│   │   ├── setup.py
│   │   └── agr/
│   │       ├── __init__.py
│   │       ├── client.py               # evaluate(), wait_for_approval() (polls GET /v1/approvals/{id}), register_agent()
│   │       └── plugins/
│   │           ├── langgraph.py        # @agr_governed decorator
│   │           └── crewai.py           # AGRToolWrapper class decorator
│   └── agr-sdk-ts/                     # TypeScript SDK (ESM + CJS dual output)
│       ├── package.json
│       ├── tsconfig.json
│       └── src/
│           ├── client.ts               # AGRClient: evaluate(), waitForApproval(), registerAgent()
│           ├── types.ts                # EvaluationResult, ApprovalApiResponse, AgentApiResponse
│           ├── errors.ts               # AGRError, AGRAuthError, AGRRateLimitError
│           ├── index.ts                # re-exports public API
│           └── __tests__/
│               ├── client.test.ts
│               └── errors.test.ts
├── infra/
│   └── migrations/
│       ├── 001_initial_schema.sql      # Core schema: orgs, policies, approval_requests, audit_events + RLS
│       ├── 002_approval_enhancements.sql # approver_email, decision_at, temporal_run_id columns
│       ├── 003_default_policy_trigger.sql # PostgreSQL trigger: on_org_created → seed 5 default policies
│       ├── 004_agents_table.sql        # agents table + RLS
│       ├── 005_webhooks_table.sql      # webhooks table + RLS
│       └── 006_audit_partitioning.sql  # Convert audit_events to monthly RANGE partitions
├── .github/
│   └── workflows/
│       └── ci.yml
├── docker-compose.yml                  # postgres:16 + redis:7 + agr-api
├── pyproject.toml                      # ruff + mypy + pytest config
├── .env.example
└── README.md
```

---

## Tech Stack

| Layer | Technology | Status | Notes |
|---|---|---|---|
| Language | Python 3.12 | Live | Type hints everywhere, async throughout |
| API framework | FastAPI 0.115 | Live | Async, OpenAPI auto-docs at /docs |
| Policy engine | Cedar CLI → Python fallback | Live | `shutil.which("cedar")` first; Python regex if no binary |
| ORM | SQLAlchemy 2.0 async | Live | AsyncSession, no sync queries |
| DB | PostgreSQL 16 | Live | RLS on all 6 tables. Monthly partitioning on audit_events. |
| Cache | Redis 7 (redis.asyncio) | Live | 60s eval cache, org-scoped invalidation on policy change |
| Rate limiting | Redis INCR + DB fallback | Live | Atomic Redis counter; DB synced via BackgroundTask |
| Approval workflows | Temporal (temporalio SDK) | Live | Graceful degradation if TEMPORAL_HOST unset |
| Email notifications | Resend REST API | Live | No-ops if RESEND_API_KEY blank; one-click HMAC-signed links |
| Webhook push | httpx + HMAC-SHA256 | Live | Fires on approve/reject; Stripe-style signature header |
| Auth (dashboard) | Clerk webhook | Live | POST /v1/clerk/webhook → create org + seed policies |
| Secrets | .env / Doppler (prod) | Live | pydantic_settings reads .env |
| Deploy | Railway | Live | Auto-deploys from main |
| Validation | Pydantic v2 | Live | All request/response models in schemas.py |
| Linting | ruff 0.8 | Live | Line length 100 |
| Type checking | mypy --strict | Live | Must pass on every PR. tests/ excluded. |
| Testing | pytest + pytest-asyncio | Live | SQLite in-memory for integration tests |
| TypeScript SDK | native fetch, ESM+CJS | Live | Node 18+, camelCase interface |

---

## Database — Actual Schema

### organizations
```
id          UUID PK
name        TEXT NOT NULL
slug        TEXT UNIQUE (nullable)
plan        TEXT DEFAULT 'developer'   -- developer|startup|business|enterprise
api_key     TEXT UNIQUE NOT NULL       -- agr_sk_ + 48 hex chars
eval_count  BIGINT DEFAULT 0
eval_limit  BIGINT DEFAULT 10000       -- 0 = unlimited
created_at  TIMESTAMPTZ
updated_at  TIMESTAMPTZ

Index: idx_organizations_api_key
```

### policies
```
id          UUID PK
org_id      UUID FK → organizations (CASCADE DELETE)
project_id  UUID NULLABLE
agent_id    TEXT NULLABLE              -- NULL = all agents
name        TEXT NOT NULL
level       TEXT NOT NULL              -- org | project | agent
cedar_rule  TEXT NOT NULL
version     INT DEFAULT 1              -- increments on cedar_rule change
active      BOOLEAN DEFAULT TRUE
created_at  TIMESTAMPTZ
updated_at  TIMESTAMPTZ

Indexes: idx_policies_org_id, idx_policies_org_active (org_id, active)
```

### approval_requests
```
id              UUID PK
org_id          UUID FK → organizations (CASCADE DELETE)
agent_id        TEXT NOT NULL
action          TEXT NOT NULL
resource        TEXT NOT NULL
context         JSONB NULLABLE
status          TEXT DEFAULT 'pending'  -- pending|approved|rejected
approver_email  TEXT NULLABLE           -- set from EvaluateRequest.approver_email
decision_at     TIMESTAMPTZ NULLABLE    -- set when approve/reject is called
temporal_run_id TEXT NULLABLE           -- Temporal workflow ID (null if Temporal not configured)
expires_at      TIMESTAMPTZ NOT NULL    -- created_at + 48h
created_at      TIMESTAMPTZ

Indexes: idx_approval_requests_org_id, idx_approval_requests_status (org_id, status)
```

### audit_events (append-only, hash-chained, monthly partitioned)
```
id           UUID NOT NULL
org_id       UUID NOT NULL              -- NO FK intentionally — audit outlives orgs
sequence_num BIGINT NOT NULL            -- app-managed per-org sequential counter
event_type   TEXT NOT NULL              -- TOOL_ALLOW|TOOL_DENY|APPROVAL_REQUESTED|APPROVAL_APPROVED|APPROVAL_REJECTED
agent_id     TEXT NOT NULL
action       TEXT NOT NULL
resource     TEXT NOT NULL
decision     TEXT NOT NULL
policy_id    UUID NULLABLE
approval_id  UUID NULLABLE
payload      JSONB NULLABLE
prev_hash    TEXT NULLABLE
entry_hash   TEXT NOT NULL              -- SHA-256(seq:event_type:json(payload):prev_hash)
recorded_at  TIMESTAMPTZ NOT NULL

Primary Key: (id, recorded_at) — required for partitioning
PARTITION BY RANGE (recorded_at) — monthly child tables auto-created
RLS enabled (inherited by all partitions)
```

### agents
```
id          UUID PK
org_id      UUID FK → organizations (CASCADE DELETE)
agent_id    TEXT NOT NULL
metadata    JSONB NULLABLE
created_at  TIMESTAMPTZ
updated_at  TIMESTAMPTZ

Unique: (org_id, agent_id) enforced at app layer (upsert logic in route)
RLS enabled
```

### webhooks
```
id          UUID PK
org_id      UUID FK → organizations (CASCADE DELETE)
url         TEXT NOT NULL
secret      TEXT NOT NULL              -- "agr_wh_" + 48 hex chars, shown once on creation
events      JSONB DEFAULT '["approval.approved","approval.rejected"]'
active      BOOLEAN DEFAULT TRUE
created_at  TIMESTAMPTZ

RLS enabled
```

**RLS:** ALL SIX tables have RLS enabled. `set_rls_org()` in `auth.py` sets `SET LOCAL app.current_org = '<org_id>'`. Routes also explicitly filter by `org_id` in every SQLAlchemy query — RLS is the safety net, explicit `WHERE org_id = X` is the primary guard.

**Default policies:** Migration 003 adds a PostgreSQL trigger `on_org_created`. `org_service.seed_default_policies()` provides the same seeding at the app layer for Clerk webhooks and SQLite tests.

---

## All API Endpoints (Actual Implementation)

### POST /v1/evaluate ← the entire product
```
Auth:    Bearer agr_sk_...
Body:    { agent_id, action, resource, context: {}, approver_email?: str }
Returns: { decision, reason, policy_id, approval_id, latency_ms, eval_id }

Decision values:
  ALLOW             → agent may execute immediately
  DENY              → agent must not execute
  APPROVAL_REQUIRED → approval_request created in DB, approval_id is non-null
                      Temporal workflow started (if configured)
                      Resend email sent to approver_email (if configured)

Rate limit: 429 when Redis eval counter >= eval_limit (non-zero). No audit event on 429.
Redis INCR is authoritative. DB eval_count synced via BackgroundTask.
Cache: Redis 60s TTL on ALLOW/DENY results. APPROVAL_REQUIRED is never cached.
```

### GET /v1/policies
Query params: `active=true|false`
Returns: list of PolicyResponse (scoped to org, ordered by created_at desc)

### POST /v1/policies
Body: `{ name, level, cedar_rule, project_id?, agent_id? }`
Returns: PolicyResponse (201). Invalidates Redis eval cache for org.

### GET /v1/policies/{id}
Returns: PolicyResponse (404 if not found or wrong org)

### PATCH /v1/policies/{id}
Body: `{ cedar_rule?, active?, name? }`
cedar_rule change increments version. Invalidates Redis eval cache. Returns: PolicyResponse.

### DELETE /v1/policies/{id}
Returns: 204. Hard delete. Invalidates Redis eval cache.

### GET /v1/approvals
Query params: `status=pending|approved|rejected`
Returns: list of ApprovalResponse (scoped to org, ordered by created_at desc)

### GET /v1/approvals/{id}
Returns: ApprovalResponse (404 if not found or wrong org)

### POST /v1/approvals/{id}/decide
Body: `{ decision: "approved"|"rejected", decided_by?: str, reason?: str }`
Unified decide endpoint. Signals Temporal, fires webhook, writes audit event.
Returns: ApprovalResponse. 409 if not pending.

### POST /v1/approvals/{id}/approve
Body: `{ decided_by?: str, reason?: str }`
Sets status=approved. Signals Temporal, fires webhook, writes APPROVAL_APPROVED audit event.
Returns: ApprovalResponse. 409 if not pending.

### POST /v1/approvals/{id}/reject
Body: `{ decided_by?: str, reason?: str }`
Sets status=rejected. Signals Temporal, fires webhook, writes APPROVAL_REJECTED audit event.
Returns: ApprovalResponse. 409 if not pending.

### GET /v1/approvals/decide (no auth)
Query param: `token=<hmac_signed_token>`
Renders HTML confirmation page for one-click email approve/reject.
Token format: `{approval_id}:{decision}:{expires_unix}:{hmac_sha256}`

### POST /v1/approvals/decide (no auth)
Query param: `token=<hmac_signed_token>`
Executes the decision from email link. Returns HTML result page.
Signals Temporal, fires webhook, writes audit event.

### GET /v1/audit
Query params: `event_type`, `agent_id`, `start_date`, `end_date`, `limit` (max 200, default 50), `offset`
Returns: list of AuditEventResponse (scoped to org, ordered by sequence_num desc)

### POST /v1/agents/register
Body: `{ agent_id, metadata?: {} }`
Upserts on (org_id, agent_id). Returns: AgentResponse. DB-persisted.

### GET /v1/agents
Returns: list of AgentResponse (scoped to org, ordered by created_at desc)

### GET /v1/agents/{id}
Returns: AgentResponse (404 if not found or wrong org). `id` is the UUID primary key.

### POST /v1/webhooks
Body: `{ url, events?: ["approval.approved","approval.rejected"] }`
Creates webhook subscription. Returns: WebhookResponse (201) — secret shown once.
Valid event values: `approval.approved`, `approval.rejected`

### GET /v1/webhooks
Returns: list of WebhookResponse (scoped to org)

### GET /v1/webhooks/{id}
Returns: WebhookResponse (404 if not found or wrong org)

### DELETE /v1/webhooks/{id}
Returns: 204. Hard delete.

### POST /v1/clerk/webhook (no auth)
Handles Clerk `user.created` event. Creates Organization + seeds 5 default policies.
Svix signature verified if `CLERK_WEBHOOK_SECRET` is set (skipped in dev if blank).
Idempotent: duplicate slug → 200.

### GET /health
No auth required. Returns `{ status: "ok" }`.
Also unprotected: `/docs`, `/openapi.json`, `/redoc`, `/v1/approvals/decide`, `/v1/clerk/webhook`

---

## Webhook Signature Verification

Payloads are signed with HMAC-SHA256 (Stripe-style):
```
X-AGR-Signature: t=<unix_timestamp>,v1=<hmac_hex>
Signed content: "<timestamp>.<json_body>"
```

Receiving end verification:
```python
import hmac, hashlib, time
ts = header.split(",")[0].split("=")[1]
sig = header.split("v1=")[1]
expected = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
assert hmac.compare_digest(sig, expected)
assert abs(int(ts) - time.time()) < 300  # 5-minute tolerance
```

---

## Auth Middleware (Actual Behavior)

`AuthMiddleware` (Starlette `BaseHTTPMiddleware`) runs on every request:
1. Skip auth for `UNPROTECTED_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/v1/approvals/decide", "/v1/clerk/webhook"}` and OPTIONS
2. Require `Authorization: Bearer agr_sk_...` header — 401 with actionable message if missing
3. Look up `Organization` by `api_key` in DB
4. Set `request.state.org_id: UUID` and `request.state.org: Organization`

Routes access org via `request.state.org_id` — there is **no** `Depends(get_current_org)` dependency.
`set_rls_org()` exists in `auth.py` but is not called automatically — routes can call it if needed.

---

## Cedar Policy Engine (Actual Behavior)

`evaluate_policies()` in `packages/agr-core/policy_engine.py`:

1. Try `shutil.which("cedar")` — if found, use Cedar CLI subprocess
2. If Cedar CLI fails or is not installed, fall back to Python regex evaluator

**Cedar CLI path** (`_cedar_cli_evaluator`):
- Writes temp `policies.cedar` + `entities.json` files
- Runs `cedar authorize --policies ... --entities ... --request-json ...`
- APPROVAL_REQUIRED detection via double-eval: first call with given context → if DENY, re-call with `approval_status=approved` injected → if ALLOW, return APPROVAL_REQUIRED
- `policy_id` is always `None` (Cedar CLI does not report which policy matched)

**Python fallback path** (`_python_evaluator`):
- Parses `forbid`/`permit` from cedar_rule text
- `_check_action_match()` — regex on `Action::"name"` or action-in-list
- `_check_when_clause()` — extracts `resource.attr == "val"`, `resource.attr like "pat*"`, `context.attr == "val"`
- Special case: `forbid ... unless { context has approval_status && context.approval_status == "approved" }` → APPROVAL_REQUIRED
- `policy_id` is populated (unlike Cedar CLI path)
- Forbid wins over permit (deny-overrides semantics)

**Limitations of Python evaluator (not full Cedar spec):**
- No principal attribute matching beyond pattern matching
- No Cedar schema validation
- `like` patterns only support `*` glob
- No Cedar entity/attribute type system

`cedar_service.py` loads policies via:
```python
SELECT * FROM policies WHERE org_id = ? AND active = TRUE
  [AND (agent_id IS NULL OR agent_id = ?)]
```

---

## Redis Service (`app/services/redis_service.py`)

```python
# Lazy client init — never blocks startup if Redis is down
async def _get_redis() -> Redis | None: ...

# Eval result cache
async def get_cached_eval(org_id, cache_key) -> dict | None   # None on miss or error
async def set_cached_eval(org_id, cache_key, result) -> None  # 60s TTL, never caches APPROVAL_REQUIRED
async def invalidate_org_eval_cache(org_id) -> None           # deletes eval:{org_id}:* pattern

# Rate limiting
async def rate_limit_incr(org_id, eval_limit, db_count) -> tuple[bool, int]
# Returns (rate_limited, new_count). Atomic INCR. Falls back to db_count if Redis down.

# DB sync
async def sync_eval_count_to_db(org_id, session) -> None  # called as BackgroundTask
```

Cache key: `eval:{org_id}:{sha256(agent_id+action+resource+sorted_context)}`

---

## Temporal Integration

**Workflow** (`app/workflows/approval_workflow.py`):
```python
@workflow.defn
class ApprovalWorkflow:
    @workflow.run
    async def run(self, approval_id: str) -> str:
        # Suspends up to 48h waiting for human_decision signal
        # Returns: "approved" | "rejected" | "expired"

    @workflow.signal
    def human_decision(self, decision: str) -> None: ...
```

**Worker** (`app/workers/approval_worker.py`):
```bash
# Run as standalone process alongside the API:
python -m app.workers.approval_worker
# Requires TEMPORAL_HOST env var
```

**Temporal service** (`app/services/temporal_service.py`):
- Lazy client init — logs warning and returns `None` if TEMPORAL_HOST unset or unreachable
- `start_approval_workflow(approval_id)` → returns workflow_id or None
- `signal_approval_workflow(workflow_id, decision)` → returns bool
- All decision endpoints (approve/reject/decide/email-link) call `signal_approval_workflow` if `temporal_run_id` is set

---

## Pydantic Schemas (`app/schemas.py`)

All models in one file:
- `EvaluateRequest` — agent_id, action, resource, context, approver_email?
- `EvaluateResponse` — decision, reason, policy_id, approval_id, latency_ms, eval_id
- `PolicyCreate` — name, level (org|project|agent), cedar_rule, project_id?, agent_id?
- `PolicyUpdate` — cedar_rule?, active?, name?
- `PolicyResponse` — full policy fields
- `ApprovalResponse` — id, org_id, agent_id, action, resource, context, status, approver_email, decision_at, expires_at, created_at
- `ApprovalDecisionRequest` — decided_by (default "api_user"), reason (default "")
- `ApprovalDecideRequest` — decision ("approved"|"rejected"), decided_by, reason
- `AuditEventResponse` — all audit_events fields
- `AgentRegisterRequest` — agent_id, metadata
- `AgentResponse` — id, org_id, agent_id, metadata, created_at, updated_at
- `WebhookCreate` — url, events (list of valid event strings)
- `WebhookResponse` — id, org_id, url, secret, events, active, created_at
- `HealthResponse` — status
- `ErrorResponse` — error, message, upgrade_url?

---

## App Config (`app/config.py`)

Uses `pydantic_settings.BaseSettings`. Reads from `.env`:
```python
database_url: str          # postgresql+asyncpg://...
redis_url: str             # redis://localhost:6379
secret_key: str            # openssl rand -hex 32  (used for HMAC token signing)
env: str                   # development | production | test
api_base_url: str          # http://localhost:8000  (used in email links)
temporal_host: str         # localhost:7233  (empty string = Temporal disabled)
temporal_namespace: str    # default
resend_api_key: str        # ""  (empty = email disabled)
slack_bot_token: str       # Slack Bot Token — empty = disabled
slack_channel_id: str      # Slack channel ID, e.g. C0123456789 — empty = disabled
clerk_webhook_secret: str  # ""  (empty = Svix verification skipped in dev)
clerk_secret_key: str      # ""  (for future dashboard auth)
clerk_publishable_key: str # ""  (for future dashboard auth)
```

---

## Database Connection (`app/database.py`)

```python
engine = create_async_engine(
    settings.database_url,
    echo=(settings.env == "development"),
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)
```

`get_session()` dependency: yields `AsyncSession`, commits on success, rolls back on exception.
**IMPORTANT**: `get_session()` — there is no `get_db()` anywhere.

---

## Audit Hash Chain

`audit_service.py` — `compute_entry_hash()`:
```
hash = SHA-256("{sequence_num}:{event_type}:{json.dumps(payload, sort_keys=True)}:{prev_hash or ''}")
```

`sequence_num` is app-managed (last + 1 per org), NOT the DB column's autoincrement.
Event types: `TOOL_ALLOW`, `TOOL_DENY`, `APPROVAL_REQUESTED`, `APPROVAL_APPROVED`, `APPROVAL_REJECTED`

---

## Python SDK — Public Interface

```python
from agr import AGRClient, EvaluationResult, AGRError, AGRAuthError, AGRRateLimitError

agr = AGRClient(api_key="agr_sk_...", base_url="https://api.agr.dev")

result: EvaluationResult = agr.evaluate(
    agent="coder-001", action="deploy", resource="production-server",
    context={"environment": "production"}
)
result.decision          # "ALLOW" | "DENY" | "APPROVAL_REQUIRED"
result.allowed           # bool
result.denied            # bool
result.requires_approval # bool
result.approval_id       # str | None
result.latency_ms        # float

# Polls GET /v1/approvals/{id} (fixed endpoint, not full list scan)
approved: bool = agr.wait_for_approval(approval_id, poll_interval=2.0, timeout=3600.0)

agr.register_agent("coder-001", metadata={"framework": "langgraph"})
```

**SDK uses synchronous `httpx.Client`** (not async). Python 3.11+.

---

## TypeScript SDK — Public Interface

```typescript
import { AGRClient } from '@agr/sdk'

const agr = new AGRClient({ apiKey: 'agr_sk_...', baseUrl: 'https://api.agr.dev' })

const result = await agr.evaluate({
  agentId: 'coder-001', action: 'deploy', resource: 'production-server',
  context: { environment: 'production' }
})
result.decision          // "ALLOW" | "DENY" | "APPROVAL_REQUIRED"
result.allowed           // boolean
result.approvalId        // string | null

const approved = await agr.waitForApproval(approvalId, { pollInterval: 2000, timeout: 3600000 })

await agr.registerAgent('coder-001', { framework: 'langgraph' })
```

Node 18+. Uses native `fetch`. Dual ESM + CJS output. camelCase interface.
Errors: `AGRAuthError` (401), `AGRRateLimitError` (429), `AGRError` (other).

---

## Testing

**Integration tests use SQLite in-memory (aiosqlite), NOT PostgreSQL.**

`conftest.py` fixtures:
- `test_org` — api_key: `agr_sk_testkey123456789012345678901234567890abcdef`
- `test_org_b` — for multi-tenant isolation tests
- `test_policies` — 3 default policies seeded
- `client` — TestClient patching both session factories
- `auth_headers`

**Implication**: RLS, JSONB operators, and audit partitioning are NOT tested at the integration level.

```bash
pytest -v                                              # all tests
pytest services/agr-api/tests/unit -v                 # unit only (no DB)
pytest services/agr-api/tests/integration -v          # integration (SQLite)
pytest services/agr-api/tests/integration/test_evaluate.py -v  # single file
```

---

## Running Locally — Complete Setup

### Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.12+ | `pyenv install 3.12` |
| Docker + Docker Compose | any recent | docker.com |
| Node.js | 18+ (TS SDK only) | nodejs.org |
| `cedar` CLI | optional | `cargo install cedar-policy-cli` |

---

### Step 1 — Clone and enter the repo

```bash
git clone https://github.com/shreejaai/agr-platform.git
cd agr-platform
```

---

### Step 2 — Create `.env` file

```bash
cp .env.example services/agr-api/.env
```

Edit `services/agr-api/.env`:

```bash
# Required
DATABASE_URL=postgresql+asyncpg://agr:password@localhost:5432/agr_dev
SECRET_KEY=$(openssl rand -hex 32)   # replace with actual output

# Defaults that work out of the box
REDIS_URL=redis://localhost:6379
ENV=development
API_BASE_URL=http://localhost:8000
TEMPORAL_HOST=                       # leave blank to disable Temporal
TEMPORAL_NAMESPACE=default

# Optional features (leave blank to disable)
RESEND_API_KEY=                      # blank = no approval emails
SLACK_BOT_TOKEN=                     # not yet used
CLERK_WEBHOOK_SECRET=                # blank = Svix verification skipped (dev-safe)
CLERK_SECRET_KEY=
CLERK_PUBLISHABLE_KEY=
```

---

### Step 3 — Start infrastructure (Postgres + Redis)

```bash
# Start only postgres and redis (not the API container — run API directly for hot reload)
docker compose up -d postgres redis

# Verify they're healthy
docker compose ps
```

---

### Step 4 — Install Python dependencies

```bash
cd services/agr-api
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

### Step 5 — Run database migrations

```bash
# From repo root
psql postgresql://agr:password@localhost:5432/agr_dev \
  -f infra/migrations/001_initial_schema.sql

psql postgresql://agr:password@localhost:5432/agr_dev \
  -f infra/migrations/002_approval_enhancements.sql

psql postgresql://agr:password@localhost:5432/agr_dev \
  -f infra/migrations/003_default_policy_trigger.sql

psql postgresql://agr:password@localhost:5432/agr_dev \
  -f infra/migrations/004_agents_table.sql

psql postgresql://agr:password@localhost:5432/agr_dev \
  -f infra/migrations/005_webhooks_table.sql

psql postgresql://agr:password@localhost:5432/agr_dev \
  -f infra/migrations/006_audit_partitioning.sql

# Or run them all at once:
for f in infra/migrations/*.sql; do
  echo "Running $f..."
  psql postgresql://agr:password@localhost:5432/agr_dev -f "$f"
done
```

---

### Step 6 — Create your first org + API key

```bash
psql postgresql://agr:password@localhost:5432/agr_dev -c "
INSERT INTO organizations (id, name, slug, api_key)
VALUES (
  gen_random_uuid(),
  'My Org',
  'my-org',
  'agr_sk_' || encode(gen_random_bytes(24), 'hex')
)
RETURNING id, api_key;
"
```

Save the `api_key` output — you'll use it as `Bearer <api_key>` in all requests.

The `on_org_created` trigger (migration 003) automatically seeds 5 default Cedar policies for this new org.

---

### Step 7 — Start the API server

```bash
cd services/agr-api
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

---

### Step 8 — Verify the setup

```bash
# Health check
curl http://localhost:8000/health

# Test evaluate (replace YOUR_API_KEY)
curl -X POST http://localhost:8000/v1/evaluate \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "test-agent",
    "action": "deploy",
    "resource": "production-server",
    "context": {"environment": "production"}
  }'
# Expected: APPROVAL_REQUIRED (matches default policy)

curl -X POST http://localhost:8000/v1/evaluate \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "test-agent",
    "action": "deploy",
    "resource": "staging-server",
    "context": {"environment": "staging"}
  }'
# Expected: ALLOW (matches default staging permit policy)
```

---

### Step 9 (Optional) — Run the Temporal worker

Only needed if `TEMPORAL_HOST` is set and you want durable approval workflows.

```bash
# In a separate terminal
cd services/agr-api
source .venv/bin/activate

# With Temporal running locally (e.g. via temporal server start-dev)
TEMPORAL_HOST=localhost:7233 python -m app.workers.approval_worker
```

Start Temporal locally:
```bash
# Install Temporal CLI: https://temporal.io/docs/cli
temporal server start-dev
# UI: http://localhost:8233
```

---

### Step 10 (Optional) — TypeScript SDK development

```bash
cd packages/agr-sdk-ts
npm install
npm test          # Jest tests
npm run build     # compile ESM + CJS to dist/
```

---

### Running Tests

```bash
cd services/agr-api
source .venv/bin/activate

# All tests (uses SQLite in-memory — no Postgres/Redis needed)
pytest -v

# Unit tests only
pytest tests/unit -v

# Integration tests only
pytest tests/integration -v

# With coverage
pytest --cov=app --cov-report=term-missing

# Lint + format check
ruff check .
ruff format --check .

# Type checking
mypy app/
```

---

### Alternative: Run everything via Docker Compose

```bash
# Builds and starts postgres + redis + agr-api together
docker compose up --build

# Migrations still need to be run manually (first time):
docker compose exec agr-api bash -c "
  for f in /app/../../infra/migrations/*.sql; do
    psql \$DATABASE_URL -f \$f
  done
"
```

---

### Common Local Dev Commands

```bash
# List orgs
psql postgresql://agr:password@localhost:5432/agr_dev \
  -c "SELECT id, name, api_key, eval_count FROM organizations;"

# View recent audit events
psql postgresql://agr:password@localhost:5432/agr_dev \
  -c "SELECT event_type, agent_id, action, resource, recorded_at FROM audit_events ORDER BY recorded_at DESC LIMIT 20;"

# View pending approvals
curl -H "Authorization: Bearer YOUR_API_KEY" \
  "http://localhost:8000/v1/approvals?status=pending"

# Flush Redis cache (invalidate all eval caches)
docker compose exec redis redis-cli FLUSHDB

# Check Redis keys for an org
docker compose exec redis redis-cli KEYS "eval:*"
```

---

## Coding Rules — Follow These Always

### Python
- Python 3.12+. Type hints on every function signature and return type. No bare `Any`.
- `ruff check .` and `ruff format .` before every commit. Line length 100.
- `mypy --strict` must pass. `exclude = ["tests/"]` in mypy config.
- Ruff ignores: `["B008", "N999"]` globally; `N802` for crewai.py; `TCH003` for routes.
- All FastAPI routes are `async def`. All DB calls use `await`. No sync SQLAlchemy anywhere.
- Use `AsyncSession` everywhere. Never call `session.commit()` in route handlers — `get_session()` handles it. Use `await session.flush()` to get DB-assigned values mid-transaction.
- Pydantic v2 for all request/response schemas. Use `model_config` not `class Config`. All schemas go in `app/schemas.py`.
- No `print()`. Use `import logging; logger = logging.getLogger(__name__)`.

### Database
- Every SQLAlchemy query touching org data must include `WHERE org_id = <org_id>`.
- Never raw SQL in application code. SQLAlchemy expressions only. (Migrations use raw SQL — fine.)
- Never UPDATE or DELETE from `audit_events`. It is append-only.
- New DB columns → new migration file (`007_...sql`, etc.). Never modify existing migrations.
- Update ORM model + schemas + tests when adding columns.

### API
- Every new route needs an integration test before the PR merges.
- All routes except UNPROTECTED_PATHS require auth via AuthMiddleware.
- Access org_id via `request.state.org_id: UUID` — no dependency injection needed.
- Status codes: 200 success, 201 creation, 204 deletion, 404 not found, 409 conflict, 429 rate limit.
- Register new routers in `main.py` with `app.include_router(router)`.
- Use `BackgroundTasks` for work that must not block the response (Redis sync, webhooks).

### Redis
- Always degrade gracefully — if Redis is down, fall back to DB values, log a warning, never raise.
- Never cache `APPROVAL_REQUIRED` results.
- Invalidate `eval:{org_id}:*` on any policy mutation (create/update/delete).

---

## Environment Variables Reference

```bash
# Required (no safe defaults for production)
DATABASE_URL=postgresql+asyncpg://agr:password@localhost:5432/agr_dev
SECRET_KEY=<openssl rand -hex 32>          # HMAC signing for email tokens

# Required with local defaults
REDIS_URL=redis://localhost:6379
ENV=development                             # development | production | test
API_BASE_URL=http://localhost:8000          # used in email approve/reject links

# Optional — empty string disables the feature
TEMPORAL_HOST=localhost:7233               # empty = Temporal disabled (DB-only approvals)
TEMPORAL_NAMESPACE=default
RESEND_API_KEY=re_...                      # empty = approval emails disabled
SLACK_BOT_TOKEN=xoxb-...                  # not yet used in code
CLERK_WEBHOOK_SECRET=whsec_...            # empty = Svix verification skipped (dev-safe)
CLERK_SECRET_KEY=sk_test_...
CLERK_PUBLISHABLE_KEY=pk_test_...
```

---

## Pricing Tiers

| Plan | Monthly Evals | Price |
|---|---|---|
| developer | 10,000 | Free |
| startup | 1,000,000 | $49/mo |
| business | unlimited | $199/mo |
| enterprise | unlimited | Custom |

`eval_limit = 0` means unlimited. Check: `org.eval_limit > 0 and eval_count >= org.eval_limit`
(Redis counter is checked first; DB is source of truth for billing.)

---

## Future Scope (Planned, Not Built)

### High Priority
1. **`GET /v1/agents/{agent_id}`** — single agent lookup, for SDK + dashboard use
2. **Slack retry on failure** — Slack notifications fire once; add retry if needed
3. **Webhook retry logic** — `webhook_service.py` fires once and logs failure; no retry/dead-letter queue
4. **`POST /v1/approvals/{id}/escalate`** — re-send email, change approver

### Architecture Hardening
5. **PyO3 Cedar bindings** — replace CLI subprocess with Python bindings when available
6. **`pg_cron` for audit partition creation** — call `ensure_audit_partitions()` monthly via cron
7. **Clerk dashboard full integration** — `clerk_secret_key` is in config but not used beyond webhook ingestion
8. **Redis connection pooling** — current impl creates a new connection per request; add a module-level persistent pool

---

## Architecture Decisions (Do Not Revisit Without Good Reason)

| Decision | Rationale |
|---|---|
| FastAPI not Go | Solo founder knows Python. FastAPI is fast enough. Swap to Go post-Series A if latency demands it. |
| Cedar not OPA | Formal verification, deny-by-default, 42x faster for this use case. |
| Temporal not custom queue | Durable suspension is the hard problem. Temporal solves it correctly. Not worth reinventing. |
| No FK on audit_events | Audit data must outlive organizations. If an org deletes their account, their audit trail must be preserved for compliance. |
| API keys not JWTs for SDK | API keys are stateless, simple to rotate, easy for developers to understand. |
| Cedar CLI → Python fallback | CLI used when available. Fallback lets development and testing proceed without cedar binary. |
| SQLite for integration tests | No PostgreSQL service needed in local test runs. Trade-off: RLS, JSONB, partitioning not tested. |
| Single schemas.py | All Pydantic models in one file — easy to find the full API surface. Split only if > ~300 lines. |
| Redis authoritative for rate limits | Avoids a DB write on every single evaluate call. Background task syncs to DB for billing. |
| Temporal graceful degradation | If TEMPORAL_HOST is unset, approval flow continues with DB-only tracking — no hard dependency. |

---

## What This Repo Does NOT Do

- **No LLM calls in the governance path.** Cedar is deterministic. The evaluate endpoint never calls an AI model.
- **No agent execution.** AGR evaluates agent actions. It does not run agents.
- **No frontend.** The dashboard is a separate repo.
- **No secrets management.** If an agent tries to read `.env` files, Cedar blocks it.
- **No real-time push.** All client SDK communication is polling or REST. Webhooks push to registered endpoints.
