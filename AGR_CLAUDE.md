# CLAUDE.md — AGR Platform

This file is read by Claude Code at the start of every session. It contains everything needed to work in this codebase without re-explanation.

**GROUND TRUTH ONLY. Every section reflects the actual code, not aspirations. Planned-but-not-built items are clearly marked `[NOT YET IMPLEMENTED]`.**

---

## What This Repo Is

**AGR (Agentic Governance Runtime)** — developer infrastructure. A drop-in governance layer for AI agent frameworks. Every agent tool call is evaluated against Cedar policies before execution. Sensitive actions (production deploys, DB drops) require human approval.

**This repo is the backend product only.** The frontend dashboard lives separately. Company Box (a separate repo) is the primary consumer of this API.

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
Cedar policy engine evaluates request (Python regex fallback — no CLI subprocess yet)
      ↓
ALLOW → return immediately, agent executes
DENY  → return immediately, agent does not execute
APPROVAL_REQUIRED → create approval_requests row in DB
                  → [NOT YET] start Temporal workflow
                  → [NOT YET] send Resend email with one-click approve/reject
                  → SDK's wait_for_approval() polls GET /v1/approvals until resolved
                  → agent executes (if approved) or aborts (if rejected)
      ↓
Every path (except rate-limited) writes a hash-chained entry to audit_events
```

The evaluate endpoint is the entire product. Everything else (policies CRUD, approval management, audit trail, dashboard) supports it.

---

## Repo Structure (Actual Files)

```
agr-platform/
├── services/
│   └── agr-api/                        # The deployed FastAPI service
│       ├── app/
│       │   ├── main.py                 # FastAPI app + CORS + AuthMiddleware + route registration
│       │   ├── config.py               # pydantic_settings.BaseSettings — reads .env
│       │   ├── database.py             # Async SQLAlchemy engine (pool_size=20) + get_session()
│       │   ├── models.py               # ORM: Organization, Policy, ApprovalRequest, AuditEvent
│       │   ├── schemas.py              # ALL Pydantic v2 request/response models (single file)
│       │   ├── routes/
│       │   │   ├── evaluate.py         # POST /v1/evaluate — core endpoint
│       │   │   ├── policies.py         # GET/POST/GET{id}/PATCH/DELETE /v1/policies
│       │   │   ├── approvals.py        # GET /v1/approvals, POST /v1/approvals/:id/approve|reject
│       │   │   ├── audit.py            # GET /v1/audit (with event_type/agent_id/date/offset filters)
│       │   │   ├── agents.py           # POST /v1/agents/register (in-memory only, no DB persistence)
│       │   │   └── health.py           # GET /health (no auth)
│       │   ├── services/
│       │   │   ├── cedar_service.py    # Load policies from DB + call policy_engine.evaluate_policies()
│       │   │   ├── approval_service.py # Create ApprovalRequest row in DB (no Temporal/email yet)
│       │   │   └── audit_service.py    # Hash-chained append-only audit logger
│       │   └── middleware/
│       │       └── auth.py             # Bearer token → org lookup → request.state.org + request.state.org_id
│       ├── scripts/
│       │   └── migrate.py              # Migration helper script
│       ├── tests/
│       │   ├── conftest.py             # SQLite in-memory test fixtures (NOT PostgreSQL)
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
│   │   └── policy_engine.py            # Python regex fallback Cedar evaluator (no CLI subprocess yet)
│   │   └── policies/
│   │       └── default.cedar           # Default policy set reference (NOT auto-loaded via trigger yet)
│   ├── agr-sdk-python/
│   │   ├── setup.py
│   │   └── agr/
│   │       ├── __init__.py             # Public: AGRClient, EvaluationResult, error types
│   │       ├── client.py               # evaluate(), wait_for_approval() (polling), register_agent()
│   │       └── plugins/
│   │           ├── __init__.py
│   │           ├── langgraph.py        # @agr_governed decorator for LangGraph tools
│   │           └── crewai.py           # AGRToolWrapper class decorator for CrewAI
│   └── agr-sdk-ts/
│       └── src/                        # TypeScript SDK [NOT YET IMPLEMENTED — placeholder only]
├── infra/
│   └── migrations/
│       └── 001_initial_schema.sql      # Full DB schema — run once on fresh DB
├── .github/
│   └── workflows/
│       └── ci.yml                      # lint → unit → integration (SQLite) — NO deploy step yet
├── docker-compose.yml                  # Local: postgres:16 + redis:7 + agr-api
├── pyproject.toml                      # ruff + mypy + pytest config
├── .env.example                        # All env vars with local defaults
└── README.md
```

---

## Tech Stack

| Layer | Technology | Status | Notes |
|---|---|---|---|
| Language | Python 3.12 | Live | Type hints everywhere, async throughout |
| API framework | FastAPI 0.115 | Live | Async, OpenAPI auto-docs at /docs |
| Policy engine | Python regex fallback | Live | Cedar CLI subprocess NOT yet wired. PyO3 planned. |
| ORM | SQLAlchemy 2.0 async | Live | AsyncSession, no sync queries |
| DB | PostgreSQL 16 | Live | RLS on all 4 tables. No partitioning yet. |
| Cache | Redis (in requirements) | NOT YET | Listed as dep, not used in code |
| Approval workflows | Temporal Cloud | NOT YET | approval_service.py creates DB row only |
| Notifications | Resend / Slack | NOT YET | No email or Slack calls exist yet |
| Auth (dashboard) | Clerk | NOT YET | SDK calls use API keys only |
| Secrets | .env / Doppler (prod) | Live | Never hardcode, never commit |
| Deploy | Railway | Live | Auto-deploys from main |
| Validation | Pydantic v2 | Live | All request/response models in schemas.py |
| Linting | ruff 0.8 | Live | Line length 100 |
| Type checking | mypy --strict | Live | Must pass on every PR |
| Testing | pytest + pytest-asyncio | Live | SQLite in-memory for integration tests |

---

## Database — Actual Schema

### organizations
```
id          UUID PK
name        TEXT NOT NULL
slug        TEXT UNIQUE (nullable in ORM — TEXT UNIQUE in SQL)
plan        TEXT DEFAULT 'developer'   -- developer|startup|business|enterprise
api_key     TEXT UNIQUE NOT NULL       -- agr_sk_ + 48 hex chars
eval_count  BIGINT DEFAULT 0
eval_limit  BIGINT DEFAULT 10000       -- 0 = unlimited
created_at  TIMESTAMPTZ
updated_at  TIMESTAMPTZ

Index: idx_organizations_api_key (api_key)
```

### policies
```
id          UUID PK
org_id      UUID FK → organizations (CASCADE DELETE)
project_id  UUID NULLABLE
agent_id    TEXT NULLABLE              -- NULL = all agents
name        TEXT NOT NULL
level       TEXT NOT NULL              -- org | project | agent
cedar_rule  TEXT NOT NULL              -- the Cedar policy statement
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
temporal_run_id TEXT NULLABLE           -- [NOT YET USED] placeholder for Temporal
expires_at      TIMESTAMPTZ NOT NULL    -- created_at + 48h
created_at      TIMESTAMPTZ

NOTE: approver_email and decision_at columns DO NOT EXIST in the ORM or SQL yet.
Indexes: idx_approval_requests_org_id, idx_approval_requests_status (org_id, status)
```

### audit_events (append-only, hash-chained)
```
id           UUID PK
org_id       UUID NOT NULL              -- NO FK intentionally — audit outlives orgs
sequence_num BIGSERIAL NOT NULL         -- app-managed per-org sequential counter
event_type   TEXT NOT NULL              -- TOOL_ALLOW|TOOL_DENY|APPROVAL_REQUESTED|APPROVAL_APPROVED|APPROVAL_REJECTED
agent_id     TEXT NOT NULL
action       TEXT NOT NULL
resource     TEXT NOT NULL
decision     TEXT NOT NULL
policy_id    UUID NULLABLE
approval_id  UUID NULLABLE
payload      JSONB NULLABLE
prev_hash    TEXT NULLABLE              -- SHA-256 of previous entry (NULL for first)
entry_hash   TEXT NOT NULL              -- SHA-256(seq:event_type:json(payload):prev_hash)
recorded_at  TIMESTAMPTZ

Indexes: idx_audit_events_org_id, idx_audit_events_org_recorded, idx_audit_events_org_type
```

**RLS:** ALL FOUR tables have RLS enabled. The app sets `SET LOCAL app.current_org = '<org_id>'`
via `set_rls_org()` in `middleware/auth.py`. However, routes also explicitly filter by `org_id`
in every SQLAlchemy query — RLS is the safety net, explicit `WHERE org_id = X` is the primary guard.

**IMPORTANT: `on_org_created` trigger does NOT exist yet.** Default policies are NOT automatically
created for new orgs. This must be done manually or via the API.

**NOTE: Audit table partitioning by month is NOT implemented.** It's a planned optimization.

---

## All API Endpoints (Actual Implementation)

### POST /v1/evaluate ← the entire product
```
Auth:    Bearer agr_sk_...
Body:    { agent_id, action, resource, context: {} }
Returns: { decision, reason, policy_id, approval_id, latency_ms, eval_id }

Decision values:
  ALLOW             → agent may execute immediately
  DENY              → agent must not execute
  APPROVAL_REQUIRED → approval_request created in DB, approval_id is non-null

Rate limit: 429 when eval_count >= eval_limit (non-zero). No audit event written on 429.
eval_count incremented via SQLAlchemy UPDATE on every non-429 call.
```

### GET /v1/policies
Query params: `active=true|false` (optional filter)
Returns: list of PolicyResponse (scoped to org, ordered by created_at desc)

### POST /v1/policies
Body: `{ name, level, cedar_rule, project_id?, agent_id? }`
level must match `^(org|project|agent)$`
Returns: PolicyResponse (201)

### GET /v1/policies/{id}
Returns: PolicyResponse (404 if not found or wrong org)

### PATCH /v1/policies/{id}
Body: `{ cedar_rule?, active?, name? }` (all optional)
cedar_rule change increments version. Returns: PolicyResponse.

### DELETE /v1/policies/{id}
Returns: 204. Hard delete.

### GET /v1/approvals
Query params: `status=pending|approved|rejected` (optional filter)
Returns: list of ApprovalResponse (scoped to org, ordered by created_at desc)

### POST /v1/approvals/{id}/approve
Body: `{ decided_by?: str, reason?: str }`
Updates status to "approved". Writes APPROVAL_APPROVED audit event.
409 if not pending. Returns: ApprovalResponse.

### POST /v1/approvals/{id}/reject
Body: `{ decided_by?: str, reason?: str }`
Updates status to "rejected". Writes APPROVAL_REJECTED audit event.
409 if not pending. Returns: ApprovalResponse.

**NOT IMPLEMENTED YET:**
- `GET /v1/approvals/{id}` — fetch single approval
- `POST /v1/approvals/{id}/decide` — unified decide endpoint

### GET /v1/audit
Query params: `event_type`, `agent_id`, `start_date`, `end_date`, `limit` (max 200, default 50), `offset` (default 0)
Returns: list of AuditEventResponse (scoped to org, ordered by sequence_num desc)

### POST /v1/agents/register
Body: `{ agent_id, metadata?: {} }`
**NOTE: No DB persistence.** Returns `{ agent_id, org_id, metadata, registered: true }` only.
In-memory registration — no agents table exists yet.

### GET /health
No auth required. Returns `{ status: "ok" }`.
Also unprotected: `/docs`, `/openapi.json`, `/redoc`

---

## Auth Middleware (Actual Behavior)

`AuthMiddleware` (Starlette `BaseHTTPMiddleware`) runs on every request:
1. Skip auth for paths in `UNPROTECTED_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}` and OPTIONS
2. Require `Authorization: Bearer agr_sk_...` header — 401 with actionable message if missing
3. Look up `Organization` by `api_key` in DB
4. Set `request.state.org_id: UUID` and `request.state.org: Organization`

Routes access org via `request.state.org_id` — there is **no** `Depends(get_current_org)` dependency.
The `set_rls_org()` function exists in `auth.py` but is **not called automatically** — routes must call it explicitly if needed (currently not called in any route).

---

## Cedar Policy Engine (Actual Behavior)

**The Cedar CLI subprocess is NOT wired up.** `policy_engine.py` uses a Python regex-based fallback.

Flow in `policy_engine.py`:
1. If no active policies → DENY (deny-by-default)
2. Iterate all policies, parse `forbid`/`permit` from cedar_rule text
3. `_check_action_match()` — regex match on `Action::"name"` or action-in-list
4. `_check_when_clause()` — regex extract `resource.attr == "val"`, `resource.attr like "pat*"`, `context.attr == "val"`
5. Special case: `forbid ... unless { context has approval_status && context.approval_status == "approved" }` → APPROVAL_REQUIRED
6. Forbid wins over permit (deny-overrides semantics)
7. No permit match → DENY

**Limitations of Python evaluator (not full Cedar spec):**
- No `principal` attribute matching beyond pattern matching
- No Cedar schema validation
- `like` patterns only support `*` glob, not Cedar's full wildcard spec
- No Cedar entity/attribute type system

**Cedar CLI integration is the next major technical work** (see Future Scope).

`cedar_service.py` loads policies via:
```python
SELECT * FROM policies WHERE org_id = ? AND active = TRUE
  [AND (agent_id IS NULL OR agent_id = ?)]  # if agent_id provided
```

---

## Python SDK — Public Interface (Actual)

```python
from agr import AGRClient, EvaluationResult, AGRError, AGRAuthError, AGRRateLimitError

# Init — reads AGR_API_KEY env var if api_key not passed
agr = AGRClient(api_key="agr_sk_...", base_url="https://api.agr.dev")
# also: timeout=10.0 (default)

# Core method (synchronous httpx)
result: EvaluationResult = agr.evaluate(
    agent="coder-001",
    action="deploy",
    resource="production-server",
    context={"environment": "production"}
)

result.decision          # "ALLOW" | "DENY" | "APPROVAL_REQUIRED"
result.allowed           # bool property
result.denied            # bool property
result.requires_approval # bool property
result.approval_id       # str | None
result.latency_ms        # float
result.eval_id           # str

# Block until human decides
# ACTUAL IMPL: polls GET /v1/approvals (full list) every poll_interval seconds
# O(n) scan — inefficient for orgs with many approvals
approved: bool = agr.wait_for_approval(
    approval_id,
    poll_interval=2.0,  # default
    timeout=3600.0      # default, raises TimeoutError
)

# Register agent — returns dict, no DB persistence
agr.register_agent("coder-001", metadata={"framework": "langgraph"})

# Context manager support
with AGRClient(api_key="...") as agr:
    result = agr.evaluate(...)
```

**SDK uses synchronous `httpx.Client`** (not async). SDK works with Python 3.11+.

**LangGraph plugin** (`agr/plugins/langgraph.py`):
```python
@agr_governed(agr, agent_id="coder-001")
@tool
def deploy_to_production(branch: str) -> str:
    return run_deploy(branch)
```

**CrewAI plugin** (`agr/plugins/crewai.py`):
```python
@AGRToolWrapper(agr, agent_id="coder-001")
class DeployTool(BaseTool):
    name = "deploy_to_production"
    def _run(self, branch: str) -> str: ...
```

---

## Pydantic Schemas (`app/schemas.py`)

All request/response models live in one file:
- `EvaluateRequest` — agent_id, action, resource, context
- `EvaluateResponse` — decision, reason, policy_id, approval_id, latency_ms, eval_id
- `PolicyCreate` — name, level (pattern: org|project|agent), cedar_rule, project_id?, agent_id?
- `PolicyUpdate` — cedar_rule?, active?, name? (all optional)
- `PolicyResponse` — full policy fields
- `ApprovalResponse` — id, org_id, agent_id, action, resource, context, status, expires_at, created_at
- `ApprovalDecisionRequest` — decided_by (default "api_user"), reason (default "")
- `AuditEventResponse` — all audit_events fields
- `AgentRegisterRequest` — agent_id, metadata
- `HealthResponse` — status
- `ErrorResponse` — error, message, upgrade_url?

---

## App Config (`app/config.py`)

Uses `pydantic_settings.BaseSettings`. Reads from `.env` file and environment:
```python
database_url: str       # postgresql+asyncpg://...
redis_url: str          # redis://localhost:6379 (not used in code yet)
secret_key: str         # openssl rand -hex 32
env: str                # development | production | test
api_base_url: str       # http://localhost:8000
temporal_host: str      # localhost:7233 (not used in code yet)
temporal_namespace: str # default (not used in code yet)
resend_api_key: str     # "" (not used in code yet)
slack_bot_token: str    # "" (not used in code yet)
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

**IMPORTANT**: `get_session()` is the correct name — there is no `get_db()` anywhere.

---

## Audit Hash Chain

`audit_service.py` — `compute_entry_hash()`:
```
hash = SHA-256("{sequence_num}:{event_type}:{json.dumps(payload, sort_keys=True)}:{prev_hash or ''}")
```

`get_last_audit_event()` fetches the most recent event per org to chain from.
`sequence_num` is app-managed (last + 1), NOT the DB BIGSERIAL (which is global, not per-org).
The `BIGSERIAL` column exists in DB but sequence_num is set by the app for per-org ordering.

Event types written by the app:
- `TOOL_ALLOW` — evaluate returned ALLOW
- `TOOL_DENY` — evaluate returned DENY
- `APPROVAL_REQUESTED` — evaluate returned APPROVAL_REQUIRED
- `APPROVAL_APPROVED` — human approved via POST .../approve
- `APPROVAL_REJECTED` — human rejected via POST .../reject

---

## Testing

**Integration tests use SQLite in-memory (aiosqlite), NOT PostgreSQL.**

`conftest.py` wires up:
- In-memory SQLite engine + session factory
- `test_org` fixture (api_key: `agr_sk_testkey123456789012345678901234567890abcdef`)
- `test_org_b` fixture (for multi-tenant isolation tests)
- `test_policies` fixture (3 default policies seeded)
- `client` fixture (patches `auth_mod.async_session_factory` and `db_mod.async_session_factory`)
- `auth_headers` fixture

**Implication**: PostgreSQL-specific features (RLS, JSONB operators, BIGSERIAL) are NOT tested.
RLS isolation is tested via application-layer `org_id` filtering in integration tests.

```bash
# Run all tests
pytest -v

# Run unit tests only (no DB)
pytest services/agr-api/tests/unit -v

# Run integration tests (SQLite, no external services needed)
pytest services/agr-api/tests/integration -v

# Run specific test
pytest services/agr-api/tests/integration/test_evaluate.py -v
```

`pytest.ini_options`: `asyncio_mode = "auto"`, `testpaths = ["services/agr-api/tests"]`

---

## Coding Rules — Follow These Always

### Python
- Python 3.12+. Type hints on every function signature and return type. No bare `Any`.
- `ruff check .` and `ruff format .` before every commit. Line length 100.
- `mypy --strict` must pass. `exclude = ["tests/"]` in mypy config — tests are excluded.
- Ruff ignores: `["B008", "N999"]` globally; `N802` for crewai.py; `TCH003` for routes.
- All FastAPI routes are `async def`. All DB calls use `await`. No sync SQLAlchemy anywhere.
- Use `AsyncSession` everywhere. Never call `session.commit()` in route handlers — `get_session()` handles it. Use `await session.flush()` to get DB-assigned values mid-transaction.
- Pydantic v2 for all request/response schemas. Use `model_config` not `class Config`. All schemas go in `app/schemas.py`.
- No `print()`. Use `import logging; logger = logging.getLogger(__name__)`.
- Error messages must be actionable (include URLs where to fix).

### Database
- Every SQLAlchemy query that touches org data must include `WHERE org_id = <org_id>`. Get org_id from `request.state.org_id`.
- Never raw SQL in application code. SQLAlchemy expressions only. (Migrations use raw SQL — fine.)
- Never UPDATE or DELETE from `audit_events`. It is append-only. Enforce at application layer.
- New DB columns → new migration file (`002_...sql`, `003_...sql`). Never modify `001_initial_schema.sql`.
- Update ORM model + schemas + tests when adding columns.

### API
- Every new route needs an integration test before the PR merges.
- All routes except `/health`, `/docs`, `/openapi.json`, `/redoc` require auth via `AuthMiddleware`.
- Access org_id via `request.state.org_id: UUID` — no dependency injection needed.
- Status codes: 200 success, 201 creation, 204 deletion, 404 not found, 409 conflict, 429 rate limit.
- Never return internal error details to client. Log then return clean message.
- Register new routers in `main.py` with `app.include_router(router)` (no prefix needed — prefix is in each router).

### SDK
- Zero internal dependencies except `httpx`. No FastAPI, no SQLAlchemy.
- Must work with Python 3.11+.
- Every error surfaces as: `AGRAuthError` (401), `AGRRateLimitError` (429), or `AGRError` (other).

---

## Environment Variables

```bash
# Required — no defaults
DATABASE_URL=postgresql+asyncpg://agr:agr_dev_password@localhost:5432/agr_dev
SECRET_KEY=<openssl rand -hex 32>

# Required with local defaults
REDIS_URL=redis://localhost:6379           # in requirements, not used in code yet
ENV=development
API_BASE_URL=http://localhost:8000
TEMPORAL_HOST=localhost:7233              # not used in code yet
TEMPORAL_NAMESPACE=default                # not used in code yet

# Optional (blank = feature disabled locally)
RESEND_API_KEY=re_...                     # not used in code yet
SLACK_BOT_TOKEN=xoxb-...                  # not used in code yet

# Not needed for SDK API calls — only for future dashboard auth
CLERK_SECRET_KEY=sk_test_...
CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_WEBHOOK_SECRET=whsec_...
```

---

## Running Locally

```bash
# 1. Start dependencies
docker compose up -d

# 2. Install Python deps
cd services/agr-api
pip install -r requirements.txt

# 3. Run migrations (first time only)
psql postgresql://agr:agr_dev_password@localhost:5432/agr_dev \
  -f ../../infra/migrations/001_initial_schema.sql

# 4. Start API
uvicorn app.main:app --reload --port 8000

# Docs: http://localhost:8000/docs
# Health: http://localhost:8000/health
```

---

## CI (GitHub Actions — `.github/workflows/ci.yml`)

On every PR and push to main:
1. `ruff check . && ruff format --check .`
2. `pytest tests/unit -v`
3. `pytest tests/integration -v` (uses SQLite, postgres service is in the CI yaml but integration tests use aiosqlite)

**No deploy step in CI yet.** Railway deploy is manual.

---

## Pricing Tiers

| Plan | Monthly Evals | Price |
|---|---|---|
| developer | 10,000 | Free |
| startup | 1,000,000 | $49/mo |
| business | unlimited | $199/mo |
| enterprise | unlimited | Custom |

`eval_limit = 0` means unlimited. Check: `org.eval_limit > 0 and org.eval_count >= org.eval_limit`.

Rate limited: HTTP 429 with body:
```json
{"error": "eval_limit_exceeded", "message": "...", "upgrade_url": "https://agr.dev/pricing"}
```
Do NOT write an audit event for rate-limited calls.

---

## Future Scope (Planned, Not Built)

These are real product roadmap items — implement them when the time comes, using the patterns already established:

### High Priority (Week 2-4)
1. **Cedar CLI subprocess** — replace `_python_evaluator` with subprocess call to `cedar-policy` CLI. The `EvaluationResult` dataclass and `evaluate_policies()` signature must stay stable.
2. **Temporal workflow integration** — in `approval_service.py`, after creating the DB row, start a Temporal workflow via the Python SDK. The workflow should suspend and wait for a `human_decision` signal.
3. **Resend email notifications** — when an approval is created, send one-click approve/reject email links. Links should be tokenized (no login required).
4. **`GET /v1/approvals/{id}`** — single approval lookup endpoint (used by SDK and dashboard).
5. **`on_org_created` trigger** — PostgreSQL trigger that inserts 3 default Cedar policies (from `default.cedar`) for every new org. Add to `002_default_policy_trigger.sql`.

### Medium Priority (Month 2)
6. **Redis policy caching** — cache Cedar evaluation results in Redis with TTL. Key: `eval:{org_id}:{hash(agent+action+resource+context)}`. Invalidate on policy change.
7. **Redis rate limiting** — move eval_count check from DB to Redis for p95 < 2ms target.
8. **Agent registration persistence** — add `agents` table, store registration metadata, enable per-agent analytics.
9. **`decision_at` and `approver_email` columns** — add to `approval_requests` via migration `002_...sql`.
10. **Webhook support** — `POST /v1/webhooks` for approval decisions (replace polling in `wait_for_approval()`).
11. **TypeScript SDK** — mirror the Python SDK interface in `packages/agr-sdk-ts/src/`.

### Architecture Hardening
12. **PyO3 Cedar bindings** — replace CLI subprocess with Python bindings when available. Drop subprocess overhead entirely.
13. **Monthly audit partitioning** — `PARTITION BY RANGE (recorded_at)` on `audit_events`. Add partition creation to a cron migration.
14. **Clerk webhook integration** — `POST /v1/clerk/webhook` to auto-create `Organization` rows when a user signs up in the dashboard.
15. **`POST /v1/approvals/{id}/decide`** — unified decide endpoint with `{ decision: "approved"|"rejected", reason: "" }` body.

---

## Architecture Decisions (Do Not Revisit Without Good Reason)

| Decision | Rationale |
|---|---|
| FastAPI not Go | Solo founder knows Python. FastAPI is fast enough. Swap to Go post-Series A if latency demands it. |
| Cedar not OPA | Formal verification, deny-by-default, 42x faster for this use case. |
| Temporal not custom queue | Durable suspension is the hard problem. Temporal solves it correctly. Not worth reinventing. |
| No FK on audit_events | Audit data must outlive organizations. If an org deletes their account, their audit trail must be preserved for compliance. |
| API keys not JWTs for SDK | API keys are stateless, simple to rotate, easy for developers to understand. JWTs add complexity for zero benefit in this context. |
| subprocess for Cedar (not PyO3) | Faster to ship. PyO3 bindings are a performance optimization for later when p95 > 2ms. |
| Python fallback evaluator (current) | Cedar CLI not installed in dev/CI. Fallback lets development and testing proceed without cedar binary. Must be replaced before production policy enforcement is relied upon. |
| SQLite for integration tests | No PostgreSQL service needed in local test runs. Trade-off: RLS and JSONB not tested. Accepted for now. |
| Single schemas.py | All Pydantic models in one file — easy to find, easy to see the full API surface. Split only if it exceeds ~300 lines. |

---

## Common Tasks

### Add a new API endpoint
1. Create or add to route file in `services/agr-api/app/routes/`
2. Add schemas to `app/schemas.py`
3. Register router in `main.py` if it's a new file
4. Write integration test in `tests/integration/test_<feature>.py`
5. Run `pytest tests/integration/test_<feature>.py` before committing

### Add a new Cedar policy to the default set
1. Edit `packages/agr-core/policies/default.cedar`
2. Test it manually via POST /v1/policies + POST /v1/evaluate
3. Once the `on_org_created` trigger exists: update the migration

### Add a new DB column
1. Create `infra/migrations/00N_description.sql` with ALTER TABLE statement
2. Update the relevant SQLAlchemy model in `services/agr-api/app/models.py`
3. Run migration against local DB
4. Update Pydantic schema in `app/schemas.py`
5. Update integration tests if response shapes change

### Debug a failing evaluate call
1. Check the eval_id in the response
2. Query `GET /v1/audit` — look for the eval_id in payload.eval_id
3. Check `decision` field — if DENY, `policy_id` tells you which policy matched
4. Check `entry_hash` chain continuity manually if tampering is suspected
5. If APPROVAL_REQUIRED and stuck: query `GET /v1/approvals?status=pending`

### Implement Temporal integration (when the time comes)
1. Add `temporalio` to `requirements.txt`
2. Create `services/agr-api/app/workflows/approval_workflow.py` — a simple workflow that suspends on `human_decision` signal
3. In `approval_service.py`, after `session.flush()`, start the workflow async (use `BackgroundTask` or a Temporal starter)
4. In `approvals.py` approve/reject endpoints, signal the workflow using `temporal_run_id`
5. Add `TEMPORAL_HOST` and `TEMPORAL_NAMESPACE` env vars (already in config, just not used)

### Publish a new SDK version
1. Bump version in `packages/agr-sdk-python/agr/__init__.py` and `setup.py`
2. `pytest packages/agr-sdk-python/tests` — must pass
3. `python -m build packages/agr-sdk-python`
4. `twine upload dist/*`

---

## What This Repo Does NOT Do

- **No LLM calls in the governance path.** Cedar is deterministic. The evaluate endpoint never calls an AI model.
- **No agent execution.** AGR evaluates agent actions. It does not run agents.
- **No frontend.** The dashboard is a separate repo. This repo exposes a JSON API only.
- **No Company Box business logic.** Company Box is a consumer. If CB needs something new, add it to the API — don't add CB-specific code here.
- **No secrets management.** If an agent tries to read `.env` files, Cedar blocks it. AGR does not store or proxy secrets.
- **No real-time push.** All client communication is polling or REST. No WebSockets, no SSE.
