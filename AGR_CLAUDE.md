# CLAUDE.md — AGR Platform

This file is read by Claude Code at the start of every session. It contains everything needed to work in this codebase without re-explanation.

**GROUND TRUTH ONLY. Every section reflects the actual code, not aspirations. Planned-but-not-built items are clearly marked `[NOT YET IMPLEMENTED]`.**

---

## What This Repo Is

**AGR (Agentic Governance Runtime)** — developer infrastructure. A drop-in governance layer for AI agent frameworks. Every agent tool call is evaluated against Cedar policies before execution. Sensitive actions (production deploys, DB drops) require human approval.

**This repo is a full-stack monorepo:** FastAPI backend (`services/agr-api/`) + Angular 17 dashboard (`apps/agr-dashboard/`).

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
├── apps/
│   └── agr-dashboard/                  # Angular 17 standalone dashboard
│       ├── src/
│       │   ├── app/
│       │   │   ├── app.component.ts    # Root — calls clerk.init()
│       │   │   ├── app.config.ts       # provideRouter + provideHttpClient(withInterceptors)
│       │   │   ├── app.routes.ts       # Lazy routes — authGuard + apiKeyGuard
│       │   │   ├── core/
│       │   │   │   ├── auth/
│       │   │   │   │   ├── clerk.service.ts       # @clerk/clerk-js singleton wrapper (signals)
│       │   │   │   │   ├── auth.guard.ts          # CanActivateFn — Clerk signed-in
│       │   │   │   │   └── api-key.guard.ts       # CanActivateFn — agr_sk_ key in localStorage
│       │   │   │   ├── http/
│       │   │   │   │   ├── api-key.interceptor.ts # Injects Bearer <key> on /v1/ requests
│       │   │   │   │   └── error.interceptor.ts   # Redirects to /settings on 401
│       │   │   │   └── models/                    # TypeScript interfaces (mirrors schemas.py)
│       │   │   │       ├── approval.model.ts
│       │   │   │       ├── policy.model.ts
│       │   │   │       ├── audit-event.model.ts
│       │   │   │       ├── agent.model.ts
│       │   │   │       └── webhook.model.ts
│       │   │   ├── layout/
│       │   │   │   ├── shell/shell.component.ts    # Flex layout: sidebar + router-outlet
│       │   │   │   └── sidebar/sidebar.component.ts # Nav, user email, API key warning
│       │   │   ├── pages/
│       │   │   │   ├── login/login.component.ts    # Clerk sign-in flow
│       │   │   │   ├── home/home.component.ts      # Stat cards + recent audit events
│       │   │   │   ├── approvals/approvals.component.ts  # List + inline approve/reject
│       │   │   │   ├── policies/policies.component.ts    # CRUD + enable/disable toggle
│       │   │   │   ├── audit/audit.component.ts    # Filtered table + pagination
│       │   │   │   ├── agents/agents.component.ts  # Register + list, API key reveal
│       │   │   │   ├── webhooks/webhooks.component.ts    # Create + list + delete
│       │   │   │   └── settings/settings.component.ts    # API key storage
│       │   │   ├── services/                       # HttpClient-based Observables
│       │   │   │   ├── api-key.service.ts           # localStorage signal wrapper
│       │   │   │   ├── approval.service.ts
│       │   │   │   ├── policy.service.ts
│       │   │   │   ├── audit.service.ts
│       │   │   │   ├── agent.service.ts
│       │   │   │   └── webhook.service.ts
│       │   │   └── shared/
│       │   │       ├── components/
│       │   │       │   ├── badge/badge.component.ts       # 10 colour variants
│       │   │       │   └── stat-card/stat-card.component.ts
│       │   │       └── pipes/relative-time.pipe.ts        # Intl.RelativeTimeFormat
│       │   ├── environments/
│       │   │   ├── environment.ts          # clerkPublishableKey, apiBase: '/v1'
│       │   │   └── environment.prod.ts
│       │   ├── index.html
│       │   ├── main.ts                     # bootstrapApplication(AppComponent, appConfig)
│       │   └── styles.css                  # Tailwind + .btn-primary .card .input .table-*
│       ├── angular.json
│       ├── package.json                    # Angular 17.3, @clerk/clerk-js, Tailwind
│       ├── tailwind.config.js              # Dark slate/indigo palette
│       ├── proxy.conf.json                 # Dev: /v1 → http://localhost:8000
│       ├── nginx.conf                      # Prod: SPA fallback + /v1/ proxy to agr-api:8000
│       ├── Dockerfile                      # Node 20 build → nginx 1.27 serve
│       └── tsconfig.json                   # strict, ES2022, moduleResolution: bundler
├── services/
│   └── agr-api/                        # The deployed FastAPI service
│       ├── app/
│       │   ├── main.py                 # FastAPI app + CORS + AuthMiddleware + all routers; lifespan: onprem license check + org bootstrap
│       │   ├── config.py               # pydantic_settings.BaseSettings — reads .env; includes deployment_mode / license_key / onprem_org_name
│       │   ├── license.py              # Ed25519 license validator (onprem mode only) — validates AGR_LICENSE_KEY on startup
│       │   ├── database.py             # Async SQLAlchemy engine (pool_size=20) + get_session()
│       │   ├── models.py               # ORM: Organization, Policy, ApprovalRequest, AuditEvent, Agent, Webhook
│       │   ├── schemas.py              # ALL Pydantic v2 request/response models (single file)
│       │   ├── routes/
│       │   │   ├── evaluate.py         # POST /v1/evaluate — core endpoint (Redis cache + rate limit)
│       │   │   ├── policies.py         # GET/POST/GET{id}/PATCH/DELETE /v1/policies
│       │   │   ├── approvals.py        # Full approval endpoints + email one-click flow + escalate
│       │   │   ├── audit.py            # GET /v1/audit (with filters) + GET /v1/audit/verify
│       │   │   ├── org.py              # GET /v1/org/me — org profile + eval usage
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
│       │       └── auth.py             # Bearer token → org lookup → request.state.org + request.state.org_id; error messages adapt to deployment_mode
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
│       │       ├── test_multi_tenant.py
│       │       ├── test_agents.py           # includes GET /v1/agents/{id} + cross-org
│       │       ├── test_webhooks.py         # 11 tests: CRUD, isolation, auth
│       │       └── test_clerk_webhook.py    # org creation, 5 default policies, idempotency
│       ├── requirements.txt
│       ├── Dockerfile          # 3-stage: python:builder + rust:slim (Cedar CLI) + python:runtime
│       ├── Dockerfile.onprem   # 4-stage: deps + cedar-builder + cython-build + runtime (no .py source)
│       ├── setup_cython.py     # Cython compilation config (used by Dockerfile.onprem)
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
│       ├── 006_audit_partitioning.sql  # Convert audit_events to monthly RANGE partitions
│       ├── 007_pg_cron_audit_partitions.sql  # pg_cron job: create next month's audit partition
│       ├── 008_webhook_deliveries.sql  # webhook_deliveries DLQ table + RLS
│       ├── 009_agent_active.sql        # agents.active column
│       ├── 010_eval_week.sql           # organizations.eval_week_start + eval_limit=100 default
│       ├── 011_indexes.sql             # Composite indexes: audit org+time, approvals org+status, deliveries webhook+time
│       ├── 012_token_version.sql       # approval_requests.token_version INTEGER DEFAULT 0
│       ├── 013_status_check.sql        # CHECK constraint: status IN ('pending','approved','rejected','escalated')
│       └── rollback/                         # Rollback scripts 001_down.sql – 013_down.sql
├── infra/migrate.sh                    # Runs migrations 001–013 (used by docker-compose migrate service)
├── .github/
│   └── workflows/
│       └── ci.yml                      # 4 jobs: lint-and-test, build-dashboard, test-ts-sdk, publish (ghcr.io on merge to main)
├── docker-compose.yml                  # postgres:16 + redis:7 + migrate + agr-api + agr-dashboard
│                                       # profile "temporal": temporal-worker service
├── docker-compose.onprem.yml           # On-prem self-hosted deployment (uses ghcr.io images, single-tenant)
├── tools/
│   ├── generate_keypair.py             # One-time Ed25519 key pair generator (run once, store private key in vault)
│   └── generate_license.py            # Issue signed license keys per customer
├── pyproject.toml                      # ruff + mypy + pytest config
├── .env.example
├── .env.onprem.example                 # Template for on-prem client deployments
└── README.md
```

---

## Tech Stack

| Layer | Technology | Status | Notes |
|---|---|---|---|
| Language | Python 3.12 | Live | Type hints everywhere, async throughout |
| API framework | FastAPI 0.115 | Live | Async, OpenAPI auto-docs at /docs |
| Policy engine | Cedar CLI → Python fallback | Live | `shutil.which("cedar")` first; Python regex if no binary. Cedar binary compiled in Docker (rust:slim stage). |
| ORM | SQLAlchemy 2.0 async | Live | AsyncSession, no sync queries |
| DB | PostgreSQL 16 | Live | RLS on all 6 tables. Monthly partitioning on audit_events. |
| Cache | Redis 7 (redis.asyncio) | Live | 60s eval cache, org-scoped invalidation on policy change |
| Rate limiting | Redis INCR + DB fallback | Live | Atomic Redis counter; DB synced via BackgroundTask |
| Approval workflows | Temporal (temporalio SDK) | Live | Graceful degradation if TEMPORAL_HOST unset |
| Email notifications | Resend REST API | Live | No-ops if RESEND_API_KEY blank; one-click HMAC-signed links |
| Webhook push | httpx + HMAC-SHA256 | Live | Fires on approve/reject; Stripe-style signature header; every attempt recorded in webhook_deliveries |
| Webhook DLQ | webhook_deliveries table | Live | Dead-letter queue; manual retry via POST /v1/webhooks/{id}/deliveries/{id}/retry |
| Auth (dashboard) | Clerk webhook + Backend API | Live | POST /v1/clerk/webhook → create org; GET /v1/clerk/api-key → auto API key fetch |
| Secrets | .env / Doppler (prod) | Live | pydantic_settings reads .env |
| Deploy (SaaS) | Docker Compose / manual | Live | No auto-deploy configured; merge to main, deploy manually |
| Deploy (On-Prem) | ghcr.io private images + docker-compose.onprem.yml | Live | CI publishes :latest and :onprem-latest to ghcr.io on every merge to main |
| On-Prem licensing | Ed25519 signed license keys | Live | `app/license.py` validates on startup; `tools/generate_license.py` issues keys; `DEPLOYMENT_MODE=onprem` activates single-tenant bootstrap |
| Validation | Pydantic v2 | Live | All request/response models in schemas.py |
| Linting | ruff 0.8 | Live | Line length 100 |
| Type checking | mypy --strict | Live | Must pass on every PR. tests/ excluded. |
| Testing | pytest + pytest-asyncio | Live | SQLite in-memory for integration tests |
| TypeScript SDK | native fetch, ESM+CJS | Live | Node 18+, camelCase interface |
| Dashboard | Angular 17 standalone, Tailwind CSS | Live | OnPush, signals, inject(), no NgModules |
| Dashboard auth (identity) | @clerk/clerk-js (vanilla JS) | Live | Wrapped in ClerkService singleton; no official Angular SDK |
| Dashboard auth (API) | agr_sk_ in localStorage | Live | apiKeyInterceptor injects Bearer header on /v1/ requests |

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
eval_limit  BIGINT DEFAULT 100         -- 0 = unlimited; developer plan = 100/week
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
status          TEXT DEFAULT 'pending'  -- pending|approved|rejected|escalated
                                        -- CHECK constraint: approval_status_check (migration 013)
approver_email  TEXT NULLABLE           -- set from EvaluateRequest.approver_email
decision_at     TIMESTAMPTZ NULLABLE    -- set when approve/reject is called
temporal_run_id TEXT NULLABLE           -- Temporal workflow ID (null if Temporal not configured)
expires_at      TIMESTAMPTZ NOT NULL    -- created_at + 48h
token_version   INTEGER NOT NULL DEFAULT 0  -- incremented on escalate; v2 email tokens embed this
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

### webhook_deliveries (append-only DLQ — migration 008)
```
id          UUID PK
webhook_id  UUID FK → webhooks (CASCADE DELETE)
org_id      UUID NOT NULL              -- for RLS; no FK (outlives webhook if needed)
event       TEXT NOT NULL
payload     JSONB NOT NULL             -- full payload that was sent
status      TEXT NOT NULL              -- pending | delivered | failed
http_status INTEGER NULLABLE           -- HTTP response code from receiver
attempts    INTEGER NOT NULL DEFAULT 0
last_error  TEXT NULLABLE              -- last exception or non-2xx description
created_at  TIMESTAMPTZ NOT NULL

Indexes: idx_webhook_deliveries_webhook_id, idx_webhook_deliveries_org_id
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

### GET /v1/webhooks/{id}/deliveries
Returns: list of WebhookDeliveryResponse — last 50 delivery attempts, newest first.
404 if webhook not found or wrong org.

### POST /v1/webhooks/{id}/deliveries/{delivery_id}/retry
Re-fires a failed delivery. Creates a new WebhookDelivery record (preserves history).
Returns: WebhookDeliveryResponse for the new attempt.
404 if delivery not found or wrong org.

### GET /v1/clerk/api-key (no agr_sk_ auth — uses Clerk session JWT)
Body: `Authorization: Bearer <clerk_session_jwt>`
Verifies the Clerk session via Clerk Backend API (requires `CLERK_SECRET_KEY`).
Finds the org whose `slug = clerk_user_id`, returns the org's `api_key`.
Used by the dashboard to auto-populate the API key after login.
Returns 503 if `CLERK_SECRET_KEY` not configured; 404 if org not created yet.

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
1. Skip auth for `UNPROTECTED_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/v1/approvals/decide", "/v1/clerk/webhook", "/v1/clerk/api-key"}` and OPTIONS
2. Require `Authorization: Bearer agr_sk_...` header — 401 with actionable message if missing
3. Error messages adapt to `settings.deployment_mode`: saas messages reference `dashboard.agr.dev`; onprem messages say "Contact your AGR administrator"
4. Look up `Organization` by `api_key` in DB
5. Set `request.state.org_id: UUID` and `request.state.org: Organization`

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
- `WebhookDeliveryResponse` — id, webhook_id, org_id, event, payload, status, http_status, attempts, last_error, created_at
- `ClerkApiKeyResponse` — api_key, org_id, org_name
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
slack_bot_token: str       # Slack Bot Token — empty = no Slack notifications
slack_channel_id: str      # Slack channel ID, e.g. C0123456789 — empty = no Slack notifications
clerk_webhook_secret: str  # ""  (empty = Svix verification skipped in dev)
clerk_secret_key: str      # ""  (for future dashboard auth)
clerk_publishable_key: str # ""  (for future dashboard auth)
deployment_mode: str       # "saas" (default) | "onprem" — controls license check + bootstrap + auth error messages
license_key: str           # ""  — required when deployment_mode=="onprem"; Ed25519-signed token issued by Shreeja AI
onprem_org_name: str       # "My Organization" — org name shown in dashboard/logs for auto-bootstrapped onprem org
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

### Step 10 — Run the Angular dashboard

```bash
cd apps/agr-dashboard
npm install
npm start         # http://localhost:4200 (proxies /v1 → localhost:8000)
```

On first load:
1. Sign in with Clerk (or skip if Clerk keys are blank — dashboard will still render)
2. Go to **Settings** and paste your `agr_sk_` API key
3. All pages (Approvals, Policies, Audit, Agents, Webhooks) become available

Build for production:
```bash
npm run build -- --configuration production
# Output: dist/agr-dashboard/browser/
```

---

### Step 11 (Optional) — TypeScript SDK development

```bash
cd packages/agr-sdk-ts
npm install
npm test          # Jest tests
npm run build     # compile ESM + CJS to dist/
```

---

### Dashboard Angular Patterns

- **All components** are standalone (no NgModules). `imports: [...]` per component.
- **Change detection**: `ChangeDetectionStrategy.OnPush` everywhere. Use signals to trigger updates.
- **DI**: `inject()` function, not constructor injection.
- **Control flow**: Angular 17 `@for`, `@if`, `@else` — NOT `*ngFor` / `*ngIf`.
- **HTTP interceptors**: Functional (`HttpInterceptorFn`) — registered in `appConfig` via `withInterceptors([...])`.
- **Route guards**: Functional (`CanActivateFn`) — `authGuard` (Clerk), `apiKeyGuard` (agr_sk_ key).
- **Models** live in `src/app/core/models/`. Services live in `src/app/services/`. Shared components in `src/app/shared/`.
- **API calls** return `Observable<T>`. Subscribe in `ngOnInit`, update signals in callbacks.
- No `async` pipe — components subscribe manually and write to signals to keep OnPush working.

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
# Builds and starts postgres + redis + agr-api + agr-dashboard (port 4200)
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

## Development Workflow & Deployment Rules

**These rules govern EVERY code change — features, bug fixes, refactors, migrations, dashboard updates. Follow them without exception.**

---

### Rule 1 — Branch Before You Touch Code

Every change, no matter how small, happens on a branch. Never commit directly to `main`.

| Change type | Branch prefix | Example |
|---|---|---|
| New feature | `feature/` | `feature/slack-notifications` |
| Bug fix | `fix/` | `fix/audit-hash-chain-corrupt` |
| Refactor (no behaviour change) | `refactor/` | `refactor/cedar-service-cleanup` |
| Database migration | `migration/` | `migration/008-add-org-timezone` |
| Dependency / infra update | `chore/` | `chore/upgrade-fastapi-0116` |
| Hotfix to production | `hotfix/` | `hotfix/429-wrong-status-code` |

```bash
git checkout main && git pull origin main
git checkout -b feature/my-feature
```

---

### Rule 2 — Commit Message Format

Every commit message must follow this format:

```
<type>(<scope>): <short description>

[optional body — explain WHY, not WHAT]

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

**Types:** `feat` · `fix` · `refactor` · `chore` · `test` · `docs` · `migration`

**Scopes:** `api` · `dashboard` · `sdk-ts` · `sdk-python` · `infra` · `ci`

**Examples:**
```
feat(api): add GET /v1/org/me endpoint with eval usage

fix(dashboard): label-has-associated-control ESLint errors in 5 components

migration(infra): add org_timezone column (008_add_org_timezone.sql)

chore(ci): upgrade Node 20 → 24, pin action versions
```

**Rules:**
- Description is imperative mood, lowercase, no period
- Max 72 characters on first line
- Never commit directly: always commit on a branch, then PR

---

### Rule 3 — Quality Gates (Run Before Every Commit)

**All of these must pass before pushing. CI will catch failures — fix them locally first.**

#### Python (services/agr-api + packages/)
```bash
cd services/agr-api && source .venv/bin/activate
ruff check .                    # linting — zero errors
ruff format --check .           # formatting — zero diffs
mypy app/                       # strict type check — zero errors
pytest tests/unit -v            # unit tests — all pass
pytest tests/integration -v     # integration tests — all pass
```

#### TypeScript SDK (packages/agr-sdk-ts)
```bash
cd packages/agr-sdk-ts
npm run typecheck               # tsc --noEmit — zero errors
npm test                        # jest — all pass
npm run build                   # must compile without errors
```

#### Angular Dashboard (apps/agr-dashboard)
```bash
cd apps/agr-dashboard
npm run lint                    # eslint — zero errors
npm run build -- --configuration production  # must compile
```

**If any gate fails: fix it on the same branch before opening the PR. Do not open a PR with known failures.**

---

### Rule 4 — What Must Change Together

When you add or change a feature, ALL of the following must be updated in the SAME PR:

| Changed | Also update |
|---|---|
| New API endpoint | Schema in `schemas.py` · ORM model if new columns · Integration test · `openapi.json` if maintained · `AGR_CLAUDE.md` endpoints section |
| New DB column | New migration file (`00N_name.sql`) · ORM model (`models.py`) · Schema (`schemas.py`) · Rollback script (`rollback/00N_down.sql`) · Tests |
| New config var | `config.py` (pydantic field with default) · `.env.example` · `AGR_CLAUDE.md` env var reference · `docker-compose.yml` if used at runtime · `docker-compose.onprem.yml` if relevant to on-prem |
| New Python dependency | `requirements.txt` · verify no `pip install --user` pollution |
| New TS SDK public method | Type in `types.ts` · Export in `index.ts` · Test in `__tests__/client.test.ts` |
| New Angular page/service | Route in `app.routes.ts` · Nav link in `sidebar.component.ts` · Model in `core/models/` |
| Breaking API change | Dashboard service updated · TS SDK updated · Python SDK updated — ALL in same PR |

---

### Rule 5 — Database Migrations

**Migrations are permanent. They cannot be modified once merged to main.**

- Migration files are numbered sequentially: `008_name.sql`, `009_name.sql`, etc.
- Always write the rollback script `rollback/00N_down.sql` in the same PR
- Migrations must be idempotent: use `IF NOT EXISTS`, `IF EXISTS`, `ON CONFLICT DO NOTHING`
- Never drop a column in the same migration that adds data depending on it
- `audit_events` is append-only and partitioned — any schema change to it requires special care (must apply to parent table AND existing partitions)
- Test migrations locally before pushing:
  ```bash
  psql postgresql://agr:password@localhost:5432/agr_dev -f infra/migrations/00N_name.sql
  # verify it works, then test rollback:
  psql postgresql://agr:password@localhost:5432/agr_dev -f infra/migrations/rollback/00N_down.sql
  ```

---

### Rule 6 — CI Must Pass Before Merge

The CI pipeline has three mandatory jobs + one publish job. **All three test jobs must be green before merging to `main`.**

| Job | Trigger | What it checks |
|---|---|---|
| `lint-and-test` | PR + push to main | ruff lint + format · Python unit tests · Python integration tests |
| `build-dashboard` | PR + push to main | Angular ESLint · Angular production build |
| `test-ts-sdk` | PR + push to main | TS typecheck · Jest tests · TS SDK build |
| `publish` | push to main only (after tests pass) | Builds + pushes `agr-api:latest`, `agr-api:onprem-latest`, `agr-dashboard:latest` to `ghcr.io/shreejaai/` |

The `publish` job is **not** a merge gate — it runs after merge, not before.

If CI fails:
1. Read the error output carefully — do not guess
2. Reproduce the failure locally using the quality gate commands (Rule 3)
3. Fix it on the same branch
4. Push — CI re-runs automatically

---

### Rule 7 — PR Checklist (Open a PR for Every Branch)

Before marking a PR ready for review (or merging if solo):

- [ ] Branch name follows Rule 1 naming
- [ ] All commits follow Rule 2 message format
- [ ] All quality gates pass locally (Rule 3)
- [ ] All affected files updated together (Rule 4)
- [ ] Migration + rollback written if DB changed (Rule 5)
- [ ] CI is green (Rule 6)
- [ ] `AGR_CLAUDE.md` updated if: new endpoint added, new config var, new dependency, architecture decision changed
- [ ] No secrets, `.env` files, or credentials in the diff

PR description must include:
```
## What
<1-3 bullet points describing the change>

## Why
<the motivation — bug it fixes, feature it enables>

## Test plan
<what was tested and how>
```

---

### Rule 8 — Deployment Process

**SaaS deployment is manual. Images are built automatically by CI and pushed to ghcr.io.**

```
Branch → PR → CI passes (all 3 test jobs) → Merge to main
  → CI publish job pushes:
      ghcr.io/shreejaai/agr-api:latest          (SaaS image)
      ghcr.io/shreejaai/agr-api:onprem-latest   (on-prem Cython-compiled image)
      ghcr.io/shreejaai/agr-dashboard:latest
  → Pull and deploy manually on your server
```

**SaaS — deploy to your server:**
```bash
# On your production server
docker pull ghcr.io/shreejaai/agr-api:latest
docker pull ghcr.io/shreejaai/agr-dashboard:latest
docker compose up -d --no-build agr-api agr-dashboard
```

**On-prem — ship to a client:**
```bash
# Client receives: docker-compose.onprem.yml + .env.onprem (with their LICENSE_KEY)
# Client runs:
docker compose -f docker-compose.onprem.yml --env-file .env.onprem up -d
# Client copies API key from first-boot logs:
docker compose -f docker-compose.onprem.yml logs agr-api | grep "API Key"
```

**Issuing a license key for a new client:**
```bash
# From repo root (private key from 1Password)
python tools/generate_license.py \
  --private-key "<b64_private_key>" \
  --org "Client Name" \
  --expiry 2027-03-20 \
  --evals 1000000
```

**Database migrations on production:**
Migrations do NOT run automatically. After merging a migration:
```bash
psql $DATABASE_URL -f infra/migrations/00N_name.sql
```

---

### Rule 9 — Hotfix Process

For a critical production bug that cannot wait for a normal PR cycle:

```bash
git checkout main && git pull origin main
git checkout -b hotfix/short-description

# Make the minimal fix — no refactoring, no unrelated changes
# Run quality gates
# Commit with: fix(scope): <description>

git push origin hotfix/short-description
# Open PR, add "HOTFIX" label, merge as soon as CI passes
```

A hotfix PR must contain ONLY the fix. No cleanup, no improvements. Those go in a separate PR.

---

### Rule 10 — What Claude Must Never Do

- **Never commit directly to `main`** — always a branch + PR
- **Never skip CI** — if CI is failing for unrelated reasons, fix the underlying issue; do not bypass
- **Never modify an existing migration file** — create a new one
- **Never commit `.env`, secrets, or API keys** — check the diff before every commit
- **Never open a PR with failing tests** — fix them first
- **Never make a "quick fix" that skips the quality gates** — ruff format failures ARE CI failures
- **Never deploy by pushing directly to Railway** — always merge to main and let CI gate the deploy
- **Never `git push --force` to main** — destructive and irreversible
- **Never amend a commit that has already been pushed to a shared branch**

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
SLACK_BOT_TOKEN=xoxb-...                  # empty = Slack notifications disabled
CLERK_WEBHOOK_SECRET=whsec_...            # empty = Svix verification skipped (dev-safe)
CLERK_SECRET_KEY=sk_test_...
CLERK_PUBLISHABLE_KEY=pk_test_...

# On-prem mode (ignored in saas mode)
DEPLOYMENT_MODE=onprem                    # "saas" (default) | "onprem"
LICENSE_KEY=<issued by generate_license.py>  # required when DEPLOYMENT_MODE=onprem; app refuses to start without it
ONPREM_ORG_NAME=Acme Corp                # org name for auto-bootstrapped org (shown in dashboard + logs)
```

---

## Pricing Tiers

| Plan | Evals | Reset | Price |
|---|---|---|---|
| developer | 100 | Weekly (auto-reset every 7 days) | Free |
| startup | 1,000,000 | Monthly | $49/mo |
| business | unlimited | — | $199/mo |
| enterprise | unlimited | — | Custom |

`eval_limit = 0` means unlimited. Check: `org.eval_limit > 0 and eval_count >= org.eval_limit`

Weekly reset: `eval_week_start` column records when the current week began. On every `/v1/evaluate`
call, if `now - eval_week_start >= 7 days` (or `eval_week_start` is NULL), `eval_count` is reset
to 0 and `eval_week_start` is updated. Redis counter is checked first; DB is source of truth.

---

---

## On-Prem Deployment (Enterprise Tier)

### How It Works

`DEPLOYMENT_MODE=onprem` activates single-tenant mode. Each client gets one isolated deployment (their own Postgres, their own org).

```
Client server:
  docker compose -f docker-compose.onprem.yml --env-file .env.onprem up -d
    ↓
  AGR API starts → app/license.py validates LICENSE_KEY (Ed25519 signature + expiry)
    ↓ (first boot only)
  _onprem_bootstrap() creates one Organization + seeds 5 default policies
  Prints API key to Docker logs ONCE — ops team copies it
    ↓
  Client uses AGR normally via API key
```

### License Key System

```
You (Shreeja AI):
  1. Generated key pair once with tools/generate_keypair.py
     → Private key: stored in 1Password (NEVER committed)
     → Public key:  baked into services/agr-api/app/license.py as AGR_PUBLIC_KEY_B64

  2. Issue per-client license with tools/generate_license.py:
       python tools/generate_license.py --private-key <b64> --org "Acme" --expiry 2027-01-01
     → Sends client a string like: eyJvcmciOi....<sig>

Client:
  Sets LICENSE_KEY=eyJvcmciOi... in .env.onprem
  App validates on startup — refuses to start if expired or tampered
```

### On-Prem vs SaaS Differences

| Behaviour | SaaS (`DEPLOYMENT_MODE=saas`) | On-Prem (`DEPLOYMENT_MODE=onprem`) |
|---|---|---|
| Org creation | Clerk webhook POST /v1/clerk/webhook | Auto-bootstrapped on first start |
| Auth errors | "Check https://dashboard.agr.dev/settings" | "Contact your AGR administrator" |
| Clerk dependency | Required for dashboard login | Not required |
| DB tenancy | Multi-tenant (many orgs per DB) | Single-tenant (one org per deployment) |
| Startup check | None | License validation (hard stop if invalid) |
| Docker image | `ghcr.io/shreejaai/agr-api:latest` | `ghcr.io/shreejaai/agr-api:onprem-latest` |
| Source code | `.py` files in image | Compiled to `.so` (Cython), `.py` removed |

### Code Protection

`Dockerfile.onprem` uses a 4-stage build:
1. `deps` — install Python packages
2. `cedar-builder` — compile Cedar CLI from Rust
3. `cython-build` — compile `app/**/*.py` → `.so` native binaries (except `__init__.py`, `main.py`, `config.py`, workers, workflows)
4. `runtime` — lean final image with `.so` files only; `.py` source is not present

The public key (`AGR_PUBLIC_KEY_B64` in `license.py`) is safe to bake into the image — it can only verify signatures, not create them.

---

## Future Scope (Planned, Not Built)

### Architecture Hardening
1. **PyO3 Cedar bindings** — replace CLI subprocess with Python bindings when available

## Recently Implemented (formerly Future Scope)

- **On-prem enterprise tier** — `DEPLOYMENT_MODE=onprem` activates single-tenant self-hosted mode with Ed25519 license validation, auto org bootstrap, Cython-compiled distribution image, and `docker-compose.onprem.yml` for clients.
- **Webhook DLQ** — `webhook_deliveries` table records every delivery attempt; manual retry via `POST /v1/webhooks/{id}/deliveries/{delivery_id}/retry`.
- **Clerk Backend API verification** — `GET /v1/clerk/api-key` verifies Clerk session JWT via Clerk Backend API; auto-populates API key in dashboard after login.
- **Temporal worker in docker-compose** — `temporal-worker` service added under `profiles: ["temporal"]`; uses `host.docker.internal:7233` to reach host Temporal.
- **Cedar CLI in Docker** — `rust:slim` build stage compiles `cedar-policy-cli`; binary available at `/usr/local/bin/cedar` in the runtime image.
- **ghcr.io CI publish** — CI `publish` job builds and pushes `agr-api:latest`, `agr-api:onprem-latest`, `agr-dashboard:latest` to `ghcr.io/shreejaai/` on every merge to main.
- **`POST /v1/approvals/{id}/escalate`** — updates `approver_email`, resends notification email. Returns 409 if not pending.
- **`GET /v1/audit/verify`** — walks all audit events in sequence order, re-computes SHA-256 hashes, returns `{valid, total, first_invalid_sequence}`.
- **Slack retry on failure** — `send_approval_slack()` retries 3× with exponential backoff (1s, 2s delays). Uses real HMAC tokens for approve/reject buttons.
- **Rollback migrations** — `infra/migrations/rollback/001_down.sql` through `013_down.sql` written.

### Production Hardening (PRs #6 and #7 — 2026-03-21)

All 30 identified production issues resolved across two PRs:

**Security**
- XSS: `html.escape()` on all user fields in approval confirm page and email HTML
- Cross-tenant: `list_deliveries` now filters `WebhookDelivery.org_id == org_id`
- Webhook secret masked (`agr_wh_••••••••`) on all GET responses; revealed only on POST creation
- CORS origins configurable via `CORS_ORIGINS` env var (not hardcoded `*`)
- Auth error JSON built with `json.dumps()` — hint text can't break JSON structure
- Webhook URLs validated for `http`/`https` scheme only (rejects `javascript:`, `data:` etc.)
- Email subject strips `\r\n` to prevent header injection

**Race Conditions & Correctness**
- Audit hash-chain: `SELECT FOR UPDATE` on sequence number query
- Weekly eval reset: single atomic SQL `UPDATE ... WHERE eval_week_start < threshold`
- Redis rate-limit seed: atomic `SET NX` replaces `exists()+set()` TOCTOU pair
- Approval decisions: `SELECT FOR UPDATE` in `_load_pending` prevents concurrent approve race
- Approval expiry enforced at decision time — returns 410 on expired requests

**Token Security**
- v2 email tokens include `token_version` in HMAC: `{id}:{decision}:{expires}:{version}:{sig}`
- Escalation increments `token_version` — old approver links invalidated immediately
- Legacy v1 tokens (4-part) still accepted for in-flight emails (backward compat)
- Rate limit on `POST /v1/approvals/decide`: max 10 attempts per approval per 5 min

**Reliability**
- `fire_approval_webhook` opens its own DB session — safe as `BackgroundTask`
- `escalate_approval` sends email as `BackgroundTask` — no longer blocks response
- Webhook retry aborts immediately on permanent 4xx (401/403/404) — no wasted retries

**Observability**
- `RequestLoggingMiddleware` + `ContextVar` propagates request ID to every log line
- `X-Request-ID` response header on every response
- `GET /health/ready` readiness probe — returns 503 if DB or Redis is down

**Validation**
- `EvaluateRequest.context` capped at 50 keys (DoS guard)
- Control chars (incl. null bytes) stripped from `agent_id`, `action`, `resource`
- Basic Cedar rule structure validated: must start with `permit`/`forbid`, end with `;`, balanced parens
- `approval_requests.status` has DB-level `CHECK` constraint (migration 013)
- `eval_week_start` set to `datetime.now(UTC)` on org creation (Clerk + on-prem bootstrap)

**DB Indexes (migration 011)**
- `idx_audit_org_time` — `audit_events(org_id, recorded_at DESC)`
- `idx_approvals_org_status` — `approval_requests(org_id, status)`
- `idx_delivery_webhook_time` — `webhook_deliveries(webhook_id, created_at DESC)`

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
- **No LLM in the dashboard.** The Angular dashboard is a pure REST client — no AI calls.
- **No secrets management.** If an agent tries to read `.env` files, Cedar blocks it.
- **No real-time push.** All client SDK communication is polling or REST. Webhooks push to registered endpoints.
