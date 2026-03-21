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
ALLOW → continue below  (DENY/APPROVAL_REQUIRED is final from Cedar)
      ↓
Risk scoring engine (app/services/risk_service.py):
  Computes 0-100 risk score from 5 weighted factors (action severity, context signals,
  rate pattern, agent trust, amount/scale). Configurable thresholds (default: allow≤30,
  approval≤70, deny>70). Can upgrade Cedar ALLOW → APPROVAL_REQUIRED or DENY.
  Cedar DENY always wins. Disabled via RISK_SCORING_ENABLED=false.
      ↓
Compliance hooks (app/services/compliance_service.py):
  Advisory only — never blocks. Runs ComplianceRegistry plugins (fail-open per plugin).
  Built-in: AuditTrailCompliancePlugin (EU AI Act Art.13, SOC2 CC6.1, ISO42001 §8.4).
  Findings included in response and audit payload.
      ↓
ALLOW             → return immediately, agent executes
DENY              → return immediately, agent does not execute
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
│       │   │   │   │   ├── clerk.service.ts       # @clerk/clerk-js wrapper; fetchApiKey() public, 3 retries, FetchKeyResult
│       │   │   │   │   ├── auth.guard.ts          # CanActivateFn — Clerk signed-in
│       │   │   │   │   └── api-key.guard.ts       # CanActivateFn — agr_sk_ key in localStorage
│       │   │   │   ├── http/
│       │   │   │   │   ├── api-key.interceptor.ts # Injects Bearer <key> on /v1/ — skips if Authorization already set
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
│       │   │   │   ├── policies/policies.component.ts    # CRUD + enable/disable toggle; bulk Import (JSON/YAML, drag-and-drop modal with dry-run preview and confirm step); Export (downloads agr_policies_YYYY-MM-DD.json)
│       │   │   │   ├── audit/audit.component.ts    # Filtered table + pagination
│       │   │   │   ├── agents/agents.component.ts  # Register + list, API key reveal
│       │   │   │   ├── webhooks/webhooks.component.ts    # Create + list + delete
│       │   │   │   └── settings/settings.component.ts    # API key auto-fetch + manual paste
│       │   │   ├── services/                       # HttpClient-based Observables
│       │   │   │   ├── api-key.service.ts           # localStorage signal wrapper
│       │   │   │   ├── approval.service.ts
│       │   │   │   ├── policy.service.ts
│       │   │   │   ├── audit.service.ts
│       │   │   │   ├── agent.service.ts
│       │   │   │   ├── org.service.ts
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
│       │   ├── main.py                 # FastAPI app + CORS + AuthMiddleware + all routers; lifespan: validate_production_settings + compliance registry + onprem license check + org bootstrap
│       │   ├── config.py               # pydantic_settings.BaseSettings — reads .env; validate_production_settings() guards weak key + wildcard CORS in production
│       │   ├── license.py              # Ed25519 license validator (onprem mode only)
│       │   ├── database.py             # Async SQLAlchemy engine (pool_size=20, echo=False) + get_session()
│       │   ├── models.py               # ORM: Organization, Policy, ApprovalRequest, AuditEvent, Agent, Webhook, WebhookDelivery
│       │   ├── schemas.py              # ALL Pydantic v2 request/response models (single file); webhook events validated via @field_validator
│       │   ├── routes/
│       │   │   ├── evaluate.py         # POST /v1/evaluate — core endpoint (Redis cache + rate limit + BackgroundTasks)
│       │   │   ├── policies.py         # GET/POST/GET{id}/PATCH/DELETE /v1/policies; DELETE is soft-delete (active=False); GET/PATCH filter active=True
│       │   │   ├── approvals.py        # Full approval endpoints + email one-click (FOR UPDATE on POST decide) + escalate
│       │   │   ├── audit.py            # GET /v1/audit (with filters) + GET /v1/audit/verify (paginated 1000/page, max 100k)
│       │   │   ├── org.py              # GET /v1/org/me — org profile + eval usage
│       │   │   ├── agents.py           # POST /v1/agents/register, GET /v1/agents, GET/DELETE /v1/agents/{id}
│       │   │   ├── webhooks.py         # POST/GET/GET{id}/DELETE /v1/webhooks; GET deliveries + retry
│       │   │   ├── clerk.py            # POST /v1/clerk/webhook + GET /v1/clerk/api-key (auto-provisions org if missing)
│       │   │   └── health.py           # GET /health (no auth)
│       │   ├── services/
│       │   │   ├── cedar_service.py    # Load active policies from DB + call policy_engine.evaluate_policies()
│       │   │   ├── approval_service.py # create_approval_request() — Slack sent via BackgroundTasks (not inline)
│       │   │   ├── audit_service.py    # Hash-chained audit logger; payload capped at 64 KB with truncation warning
│       │   │   ├── compliance_service.py  # CompliancePlugin ABC + ComplianceRegistry; SystemExit/KeyboardInterrupt re-raised
│       │   │   ├── compliance_plugins/
│       │   │   │   └── audit_trail_check.py  # Built-in: EU AI Act Art.13, SOC2 CC6.1, ISO42001 §8.4
│       │   │   ├── notification_service.py # HMAC-signed email tokens (v1/v2) + Resend email delivery
│       │   │   ├── org_service.py      # seed_default_policies() — 5 default Cedar rules
│       │   │   ├── policy_import_service.py  # import/export; 1 MB YAML cap; duplicate name check within batch
│       │   │   ├── redis_service.py    # Eval cache + rate limiting; cache invalidation uses async scan_iter + batched UNLINK (500/batch)
│       │   │   ├── risk_service.py     # Deterministic risk scoring (0-100), 5 weighted factors
│       │   │   ├── temporal_service.py # Lazy Temporal client; retries connection after failure (not cached permanently)
│       │   │   └── webhook_service.py  # HMAC-SHA256 signed delivery; timeout from settings.webhook_timeout; logs malformed events
│       │   ├── workflows/
│       │   │   └── approval_workflow.py # Temporal ApprovalWorkflow — 48h wait + human_decision signal
│       │   ├── workers/
│       │   │   └── approval_worker.py  # Standalone Temporal worker process
│       │   └── middleware/
│       │       ├── auth.py             # Bearer → org lookup; SET LOCAL uses parameterized bindparam (not string interpolation); UNPROTECTED_PATHS includes /v1/clerk/api-key
│       │       └── logging_mw.py       # Request ID ContextVar; reset in finally block (not lost on exception)
│       ├── scripts/
│       │   └── migrate.py
│       ├── tests/
│       │   ├── conftest.py             # SQLite in-memory fixtures (NOT PostgreSQL)
│       │   ├── unit/
│       │   │   ├── test_audit_hash.py
│       │   │   ├── test_langgraph_plugin.py
│       │   │   ├── test_policy_engine.py
│       │   │   └── test_sdk_client.py
│       │   ├── integration/
│       │   │   ├── test_evaluate.py
│       │   │   ├── test_approvals.py
│       │   │   ├── test_policies.py
│       │   │   ├── test_multi_tenant.py
│       │   │   ├── test_agents.py
│       │   │   ├── test_webhooks.py
│       │   │   └── test_clerk_webhook.py
│       │   └── postgres/               # Real PostgreSQL tests (require PG_TEST_URL)
│       │       ├── test_rls.py
│       │       ├── test_audit_partitioning.py
│       │       ├── test_jsonb_operations.py
│       │       └── test_constraints.py
│       ├── requirements.txt
│       ├── Dockerfile          # 3-stage: python:builder + rust:slim (Cedar CLI) + python:runtime
│       ├── Dockerfile.onprem   # 4-stage: deps + cedar-builder + cython-build + runtime (no .py source)
│       └── setup_cython.py     # Cython compilation config (used by Dockerfile.onprem only)
├── packages/
│   ├── agr-core/
│   │   ├── __init__.py
│   │   ├── policy_engine.py            # Cedar CLI subprocess + Python regex fallback; warns on empty policy list
│   │   └── policies/
│   │       └── default.cedar           # 5 default Cedar policies (mirrored in org_service.py)
│   ├── agr-sdk-python/
│   │   ├── setup.py
│   │   └── agr/
│   │       ├── __init__.py
│   │       ├── client.py               # evaluate(), wait_for_approval(), register_agent()
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
│   ├── migrate.sh                      # Runs migrations 001–015; credentials in PSQL connection string
│   └── migrations/
│       ├── 001_initial_schema.sql      # Core schema: orgs, policies, approval_requests, audit_events + RLS
│       ├── 002_approval_enhancements.sql # approver_email, decision_at, temporal_run_id columns
│       ├── 003_default_policy_trigger.sql # PostgreSQL trigger: on_org_created → seed 5 default policies
│       ├── 004_agents_table.sql        # agents table + RLS
│       ├── 005_webhooks_table.sql      # webhooks table + RLS
│       ├── 006_audit_partitioning.sql  # Convert audit_events to monthly RANGE partitions; INSERT from legacy runs AFTER partitions created
│       ├── 007_pg_cron_audit_partitions.sql  # pg_cron job: create next month's audit partition (skipped if pg_cron unavailable)
│       ├── 008_webhook_deliveries.sql  # webhook_deliveries DLQ table + RLS
│       ├── 009_agent_active.sql        # agents.active column
│       ├── 010_eval_week.sql           # organizations.eval_week_start + eval_limit=100 default
│       ├── 011_indexes.sql             # Composite indexes: audit org+time, approvals org+status, deliveries webhook+time
│       ├── 012_token_version.sql       # approval_requests.token_version INTEGER DEFAULT 0
│       ├── 013_status_check.sql        # CHECK constraint: status IN ('pending','approved','rejected','escalated')
│       ├── 014_audit_sequence_per_org.sql  # UNIQUE INDEX on audit_events(org_id, sequence_num, recorded_at)
│       ├── 015_audit_agent_index.sql   # INDEX on audit_events(org_id, agent_id) for agent_id filter queries
│       └── rollback/                   # Rollback scripts 001_down.sql – 013_down.sql (014 and 015 rollbacks not yet written)
├── .github/
│   └── workflows/
│       └── ci.yml                      # 4 jobs: lint-and-test, build-dashboard, test-ts-sdk, publish (ghcr.io on merge to main)
├── docker-compose.yml                  # postgres:16 + redis:7 + migrate + agr-api + agr-dashboard
│                                       # DB: agr_svc_usr / agr_platform; profile "temporal": temporal-worker
├── docker-compose.onprem.yml           # On-prem self-hosted deployment (uses ghcr.io images, single-tenant)
├── docker-compose.test.yml             # Isolated postgres:5433 + redis:6380 for PostgreSQL integration tests
├── .env                                # Root-level Docker Compose overrides (gitignored) — CLERK_*, ENV, CORS_ORIGINS
├── examples/
│   ├── README.md
│   ├── curl/          # 12 curl scripts (00_setup through 12_full_demo)
│   ├── python/        # 7 Python SDK examples + requirements.txt
│   ├── node/          # 3 TypeScript SDK examples
│   └── policy_packs/  # 6 policy pack files (finance, devops, data_access, security, starter)
├── tools/
│   ├── generate_keypair.py             # One-time Ed25519 key pair generator
│   └── generate_license.py            # Issue signed license keys per customer
├── pyproject.toml                      # ruff + mypy + pytest config
├── .env.example
├── .env.onprem.example
├── openapi.json                        # Manually maintained OpenAPI 3.1.0 spec
└── README.md
```

---

## Tech Stack

| Layer | Technology | Status | Notes |
|---|---|---|---|
| Language | Python 3.12 | Live | Type hints everywhere, async throughout |
| API framework | FastAPI 0.115 | Live | Async, OpenAPI auto-docs at /docs |
| Policy engine | Cedar CLI → Python fallback | Live | `shutil.which("cedar")` first; Python regex if no binary. Cedar binary compiled in Docker (rust:slim stage). |
| ORM | SQLAlchemy 2.0 async | Live | AsyncSession, no sync queries. `echo=False` always. |
| DB | PostgreSQL 16 | Live | RLS on all 6 tables. Monthly partitioning on audit_events. |
| Cache | Redis 7 (redis.asyncio) | Live | 60s eval cache, org-scoped invalidation on policy change |
| Rate limiting | Redis INCR + DB fallback | Live | Atomic Redis counter; DB synced via BackgroundTask |
| Approval workflows | Temporal (temporalio SDK) | Live | Graceful degradation if TEMPORAL_HOST unset |
| Email notifications | Resend REST API | Live | No-ops if RESEND_API_KEY blank; one-click HMAC-signed links |
| Webhook push | httpx + HMAC-SHA256 | Live | Fires on approve/reject; Stripe-style signature header; every attempt recorded in webhook_deliveries |
| Webhook DLQ | webhook_deliveries table | Live | Dead-letter queue; manual retry via POST /v1/webhooks/{id}/deliveries/{id}/retry |
| Auth (dashboard) | Clerk webhook + Backend API | Live | POST /v1/clerk/webhook → create org; GET /v1/clerk/api-key → auto-provisions org + returns API key |
| Secrets | .env / root .env (Docker Compose) | Live | pydantic_settings reads .env; root .env overrides Docker Compose vars |
| Deploy (SaaS) | Docker Compose / manual | Live | No auto-deploy configured; merge to main, deploy manually |
| Deploy (On-Prem) | ghcr.io private images + docker-compose.onprem.yml | Live | CI publishes :latest and :onprem-latest to ghcr.io on every merge to main |
| On-Prem licensing | Ed25519 signed license keys | Live | `app/license.py` validates on startup; `tools/generate_license.py` issues keys |
| Validation | Pydantic v2 | Live | All request/response models in schemas.py |
| Linting | ruff 0.8 | Live | Line length 100 |
| Type checking | mypy --strict | Live | Must pass on every PR. tests/ excluded. |
| Testing | pytest + pytest-asyncio | Live | SQLite in-memory for integration tests |
| TypeScript SDK | native fetch, ESM+CJS | Live | Node 18+, camelCase interface |
| Dashboard | Angular 17 standalone, Tailwind CSS | Live | OnPush, signals, inject(), no NgModules |
| Dashboard auth (identity) | @clerk/clerk-js (vanilla JS) | Live | Wrapped in ClerkService singleton |
| Dashboard auth (API) | agr_sk_ in localStorage | Live | apiKeyInterceptor injects Bearer header on /v1/ requests; skips override if request already has Authorization |

---

## Database — Actual Schema

### organizations
```
id              UUID PK
name            TEXT NOT NULL
slug            TEXT UNIQUE (nullable)   -- stores Clerk user_id
plan            TEXT DEFAULT 'developer' -- developer|startup|business|enterprise
api_key         TEXT UNIQUE NOT NULL     -- agr_sk_ + 48 hex chars
eval_count      BIGINT DEFAULT 0
eval_limit      BIGINT DEFAULT 100       -- 0 = unlimited; developer plan = 100/week
eval_week_start TIMESTAMPTZ
created_at      TIMESTAMPTZ
updated_at      TIMESTAMPTZ

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
active      BOOLEAN DEFAULT TRUE       -- soft-delete: DELETE sets active=False; GET/PATCH filter active=True
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
approver_email  TEXT NULLABLE
decision_at     TIMESTAMPTZ NULLABLE
temporal_run_id TEXT NULLABLE
expires_at      TIMESTAMPTZ NOT NULL    -- created_at + 48h
token_version   INTEGER NOT NULL DEFAULT 0  -- incremented on escalate
created_at      TIMESTAMPTZ

Indexes: idx_approval_requests_org_id, idx_approvals_org_status (org_id, status)
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
payload      JSONB NULLABLE             -- capped at 64 KB; oversized payloads truncated with warning log
prev_hash    TEXT NULLABLE
entry_hash   TEXT NOT NULL              -- SHA-256(seq:event_type:json(payload):prev_hash)
recorded_at  TIMESTAMPTZ NOT NULL

Primary Key: (id, recorded_at) — required for partitioning
PARTITION BY RANGE (recorded_at) — monthly child tables auto-created
RLS enabled (inherited by all partitions)

Indexes: idx_audit_org_time (org_id, recorded_at DESC)
         idx_audit_events_org_agent (org_id, agent_id)          -- migration 015
         idx_audit_events_org_seq_unique UNIQUE (org_id, sequence_num, recorded_at) -- migration 014
```

### agents
```
id          UUID PK
org_id      UUID FK → organizations (CASCADE DELETE)
agent_id    TEXT NOT NULL
active      BOOLEAN DEFAULT TRUE
metadata    JSONB NULLABLE             -- name, description, framework stored here
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
org_id      UUID NOT NULL
event       TEXT NOT NULL
payload     JSONB NOT NULL
status      TEXT NOT NULL              -- pending | delivered | failed
http_status INTEGER NULLABLE
attempts    INTEGER NOT NULL DEFAULT 0
last_error  TEXT NULLABLE
created_at  TIMESTAMPTZ NOT NULL

Indexes: idx_delivery_webhook_time (webhook_id, created_at DESC)
RLS enabled
```

**RLS:** ALL SIX tables have RLS enabled. `set_rls_org()` in `auth.py` sets `SET LOCAL app.current_org_id = :org_id` via parameterized bindparam (never string interpolation). Routes also explicitly filter by `org_id` in every SQLAlchemy query — RLS is the safety net, explicit `WHERE org_id = X` is the primary guard.

**Default policies:** Migration 003 adds a PostgreSQL trigger `on_org_created`. `org_service.seed_default_policies()` provides the same seeding at the app layer for Clerk webhooks, auto-provisioning, and SQLite tests.

---

## All API Endpoints (Actual Implementation)

### POST /v1/evaluate ← the entire product
```
Auth:    Bearer agr_sk_...
Body:    { agent_id, action, resource, context: {}, approver_email?: str }
Returns: { decision, reason, policy_id, approval_id, latency_ms, eval_id,
           risk_score?, risk_level?, risk_factors?, compliance_findings? }

Decision values:
  ALLOW             → agent may execute immediately
  DENY              → agent must not execute
  APPROVAL_REQUIRED → approval_request created in DB

Rate limit: 429 when Redis eval counter >= eval_limit (non-zero). No audit event on 429.
Cache: Redis 60s TTL on ALLOW/DENY. APPROVAL_REQUIRED never cached.
```

### GET /v1/policies
Query params: `active=true|false`
Returns: list of PolicyResponse (scoped to org, ordered by created_at desc)

### POST /v1/policies
Body: `{ name, level, cedar_rule, project_id?, agent_id? }`
Returns: PolicyResponse (201). Invalidates Redis eval cache for org.

### GET /v1/policies/{id}
Returns: PolicyResponse (404 if not found, wrong org, or soft-deleted)

### PATCH /v1/policies/{id}
Body: `{ cedar_rule?, active?, name? }`
Returns: PolicyResponse. 404 if soft-deleted. cedar_rule change increments version.

### DELETE /v1/policies/{id}
**Soft-delete** — sets `active=False`, does NOT remove the row (preserves audit FK integrity).
Returns: 204.

### POST /v1/policies/import
Body: `{ policies: [PolicyImportItem], dry_run?: bool, overwrite?: bool }`
Duplicate names within the same import list are rejected with 400.
Also accepts YAML (`Content-Type: application/x-yaml`, max 1 MB) and raw Cedar text.
Returns: `{ dry_run, total, created, updated, skipped, errors, results }`
**IMPORTANT**: Route declared BEFORE `/{policy_id}` in policies.py.

### GET /v1/policies/export
Query params: `active_only=true|false` (default false)
**IMPORTANT**: Route declared BEFORE `/{policy_id}` in policies.py.

### GET /v1/approvals
Query params: `status=pending|approved|rejected`
Returns: list of ApprovalResponse (scoped to org)

### GET /v1/approvals/{id}
Returns: ApprovalResponse

### POST /v1/approvals/{id}/approve | /reject | /decide | /escalate
Uses `SELECT FOR UPDATE` (`_load_pending()`) to prevent concurrent double-decision races.

### GET /v1/approvals/decide (no auth)
Query param: `token=<hmac_signed_token>` — renders HTML confirmation page.

### POST /v1/approvals/decide (no auth)
Accepts token via hidden POST form field (not URL query param — prevents token leakage in server logs).
Falls back to query param for Slack button links.
Uses `SELECT FOR UPDATE` on the approval row to serialize concurrent email link clicks.

### GET /v1/audit
Query params: `event_type`, `agent_id`, `start_date`, `end_date`, `limit` (max 200, default 50), `offset`
Covered by `idx_audit_org_time` for time-range queries and `idx_audit_events_org_agent` for agent_id filter.

### GET /v1/audit/verify
Verifies the hash chain by recomputing SHA-256 for each event.
**Paginated**: fetches in batches of 1000, stops at `limit` (default + max: 100,000 events).
Returns: `{ valid, total, first_invalid_sequence }`

### GET /v1/org/me
Returns: `{ id, name, plan, eval_count, eval_limit, eval_week_start }`

### POST /v1/agents/register
Body: `{ agent_id, metadata?: {} }` — upserts on (org_id, agent_id).

### GET /v1/agents
Returns: list of AgentResponse (scoped to org)

### GET /v1/agents/{id}
Returns: AgentResponse (404 if not found or wrong org)

### DELETE /v1/agents/{id}
Hard delete. Returns 204.

### POST /v1/webhooks
Body: `{ url, events?: [...] }` — events validated via Pydantic `@field_validator`.
Valid events: `approval.approved`, `approval.rejected`

### GET/DELETE /v1/webhooks/{id}
DELETE returns 204.

### GET /v1/webhooks/{id}/deliveries
Returns last 50 delivery attempts.

### POST /v1/webhooks/{id}/deliveries/{delivery_id}/retry
Re-fires a failed delivery. Creates a new WebhookDelivery record.

### GET /v1/clerk/api-key (no agr_sk_ auth — uses Clerk session JWT)
`Authorization: Bearer <clerk_session_jwt>`
1. Verifies the Clerk session via Clerk Backend API (`CLERK_SECRET_KEY` required — returns 503 if not set)
2. Looks up org by `slug = clerk_user_id`
3. **If org not found**: auto-provisions org + seeds 5 default policies using Clerk user profile data
   (handles local dev where Clerk webhooks can't reach localhost)
4. Returns `{ api_key, org_id, org_name }`

Rate-limited: 10 requests/IP/minute via Redis (fails open if Redis unavailable).

### POST /v1/clerk/webhook (no auth)
Handles Clerk `user.created` event → creates Organization + seeds 5 default policies.
Svix signature verified if `CLERK_WEBHOOK_SECRET` set. Idempotent on duplicate slug.

### GET /health
No auth. Returns `{ status: "ok" }`.

**UNPROTECTED_PATHS:**
`/health`, `/health/ready`, `/docs`, `/openapi.json`, `/redoc`,
`/v1/approvals/decide`, `/v1/clerk/webhook`, `/v1/clerk/api-key`

---

## Auth Middleware (Actual Behavior)

`AuthMiddleware` (`middleware/auth.py`):
1. Skip auth for `UNPROTECTED_PATHS` and OPTIONS
2. Require `Authorization: Bearer agr_sk_...` header — 401 if missing or wrong format
3. Error messages adapt to `settings.deployment_mode`: saas → reference `dashboard.agr.dev`; onprem → "Contact your AGR administrator"
4. Look up `Organization` by `api_key` in DB
5. Set `request.state.org_id: UUID` and `request.state.org: Organization`

**SQL injection prevention**: `SET LOCAL app.current_org_id` uses `text(...).bindparams(org_id=str(org_id))` — never string interpolation.

Routes access org via `request.state.org_id` — there is **no** `Depends(get_current_org)` dependency.

---

## Dashboard — API Key Auto-Fetch Flow

```
App bootstrap (APP_INITIALIZER)
  └─ ClerkService.init()
       └─ if clerk.user AND no key in localStorage → fetchApiKey()

Settings page (ngOnInit)
  └─ if no key in localStorage → fetchFromClerk() [auto-triggers on load]
  └─ "Fetch API Key Automatically" button → fetchFromClerk()
  └─ "Refresh from Clerk" button (when key exists) → fetchFromClerk()

fetchApiKey() in ClerkService:
  - Gets Clerk session JWT via clerk.session.getToken()
  - Calls GET /v1/clerk/api-key with Authorization: Bearer <jwt>
  - Retries up to 3 times with 2s delay (handles webhook latency on first signup)
  - Returns FetchKeyResult: { ok: true } | { ok: false, reason: 'not_signed_in' | 'clerk_not_configured' | 'org_not_found' | 'error' }

apiKeyInterceptor:
  - Adds Authorization: Bearer <agr_sk_> on all /v1/ requests
  - SKIPS override if request already has Authorization header set
    (prevents clobbering the Clerk JWT when calling /v1/clerk/api-key)
```

---

## Cedar Policy Engine (Actual Behavior)

`evaluate_policies()` in `packages/agr-core/policy_engine.py`:

1. Warns if no active policies (all actions DENY by default)
2. Try `shutil.which("cedar")` — if found, use Cedar CLI subprocess
3. Fall back to Python regex evaluator

**Python fallback limitations:** No principal attribute matching, no Cedar schema validation, `like` only supports `*` glob, no Cedar entity/attribute type system.

---

## Python SDK (`packages/agr-sdk-python/`)

### Methods
```
evaluate(agent, action, resource, context={}, approver_email=None) -> EvaluationResult
wait_for_approval(approval_id, timeout=3600, poll_interval=5) -> bool
register_agent(agent_id, metadata={}) -> dict
import_policies(policies=[], overwrite=False, dry_run=False) -> dict
    # Bulk import PolicyImportItem dicts. Returns PolicyImportResponse.
export_policies(active_only=True) -> list[dict]
    # Export all org policies. Returns list of PolicyImportItem-compatible dicts.
```

### EvaluationResult fields
```
decision: str                         # "ALLOW" | "DENY" | "APPROVAL_REQUIRED"
reason: str | None
policy_id: str | None
approval_id: str | None
requires_approval: bool               # True when decision == "APPROVAL_REQUIRED"
latency_ms: float | None
eval_id: str | None
risk_score: int | None                # 0-100 risk score (None if risk scoring disabled)
risk_level: str | None                # "LOW" | "MEDIUM" | "HIGH"
risk_factors: dict | None             # factor breakdown e.g. {"action_severity": 40}
compliance_findings: list | None      # [{plugin, compliant, findings, framework}]
```

### Exports from `__init__.py`
```
AGRClient, EvaluationResult, AGRError, AGRAuthError, AGRRateLimitError
```

### Plugins
- `agr.plugins.langgraph` — `@agr_governed(agr_client=agr, agent_id=...)` decorator for LangGraph tools
- `agr.plugins.crewai` — `AGRToolWrapper` class decorator for CrewAI tools

---

## TypeScript SDK (`packages/agr-sdk-ts/`)

### Methods
```typescript
evaluate(request: EvaluationRequest): Promise<EvaluationResult>
waitForApproval(approvalId: string, timeoutMs?: number): Promise<boolean>
registerAgent(agentId: string, metadata?: Record<string, unknown>): Promise<AgentApiResponse>
importPolicies(request: PolicyImportRequest): Promise<PolicyImportResponse>
exportPolicies(activeOnly?: boolean): Promise<PolicyImportItem[]>
```

### EvaluationResult fields
```typescript
decision: string
reason: string | null
policyId: string | null
approvalId: string | null
requiresApproval: boolean
latencyMs: number | null
evalId: string | null
riskScore: number | null
riskLevel: string | null
riskFactors: Record<string, number> | null
complianceFindings: ComplianceFinding[] | null
```

### Exported types from `index.ts`
```
AGRClient, EvaluationResult, AGRError, AGRAuthError, AGRRateLimitError,
ComplianceFinding, PolicyImportItem, PolicyImportRequest, PolicyImportResponse, PolicyImportResult
```

---

## App Config (`app/config.py`)

Uses `pydantic_settings.BaseSettings`. Reads from `.env`:
```python
database_url: str          # postgresql+asyncpg://...
redis_url: str             # redis://localhost:6379
secret_key: str            # openssl rand -hex 32  (used for HMAC token signing)
env: str                   # development | production | test
api_base_url: str          # http://localhost:8000
temporal_host: str         # empty string = Temporal disabled
temporal_namespace: str    # default
resend_api_key: str        # "" = email disabled
slack_bot_token: str       # "" = no Slack notifications
slack_channel_id: str      # "" = no Slack notifications
clerk_webhook_secret: str  # "" = Svix verification skipped (dev-safe)
clerk_secret_key: str      # required for GET /v1/clerk/api-key to work
clerk_publishable_key: str # "" (used in dashboard build args)
deployment_mode: str       # "saas" (default) | "onprem"
license_key: str           # required when deployment_mode=="onprem"
onprem_org_name: str       # "My Organization"
risk_thresholds_allow_max: int     # 30
risk_thresholds_approval_max: int  # 70
risk_scoring_enabled: bool         # True
webhook_timeout: float             # 10.0 — configurable per-attempt delivery timeout (seconds)
cors_origins: list[str]            # ["*"] default; must be restricted in production
```

**`validate_production_settings()`** — called at startup when `env == "production"`:
- Raises `RuntimeError` if `secret_key` contains `"dev-secret-key"`
- Raises `RuntimeError` if `cors_origins == ["*"]`

---

## Database Connection (`app/database.py`)

```python
engine = create_async_engine(
    settings.database_url,
    echo=False,   # SQL query logging disabled — was echo=(env=="development"), removed for cleaner logs
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

`sequence_num` is app-managed (last + 1 per org). Enforced unique by migration 014.
Payload capped at **64 KB** — oversized payloads truncated to `{ _truncated, _original_size_bytes, eval_id }`.
`audit_service.get_last_audit_event()` uses `SELECT FOR UPDATE` to serialize concurrent writes per org.

---

## Security Fixes Applied (2026-03)

These were identified in a full code audit and fixed:

| Severity | Fix |
|----------|-----|
| CRITICAL | SQL injection in `SET LOCAL app.current_org = '{org_id}'` → parameterized bindparam |
| CRITICAL | Weak dev secret key allowed in production → `validate_production_settings()` guard |
| CRITICAL | Slack notification sent before DB transaction commit → deferred to BackgroundTasks |
| CRITICAL | HMAC token exposed in URL query param → hidden POST form field |
| CRITICAL | `/v1/clerk/api-key` unauthenticated + enumerable → Redis rate limit (10 req/min/IP) |
| HIGH | `GET /v1/audit/verify` loaded all rows into memory → paginated (1000/page, 100k cap) |
| HIGH | `IntegrityError` handler too broad in Clerk webhook → slug-specific detection (Postgres + SQLite) |
| HIGH | Email link decide handler had no `FOR UPDATE` lock → double-decision race condition |
| HIGH | Migration 006 INSERT from legacy ran before partitions created → fixed ordering |
| HIGH | Missing unique index on `(org_id, sequence_num)` → migration 014 |
| HIGH | Webhook service silently skipped malformed events column → warning log added |
| MEDIUM | ContextVar not reset on exception in logging middleware → moved to `finally` block |
| MEDIUM | Hard delete on policies broke audit FK references → soft-delete (active=False) |
| MEDIUM | Webhook event type validated only in route handler → `@field_validator` in Pydantic schemas |
| MEDIUM | `SystemExit`/`KeyboardInterrupt` swallowed in compliance registry → re-raised |
| MEDIUM | YAML import had no size limit → 1 MB cap before `yaml.safe_load()` |
| MEDIUM | Bulk import allowed duplicate names within same batch → upfront duplicate check |
| MEDIUM | Missing `session.flush()` after `session.delete()` in agent + webhook DELETE endpoints |
| MEDIUM | Missing index on `audit_events(org_id, agent_id)` → migration 015 |
| LOW | Webhook timeout hardcoded → `settings.webhook_timeout` |
| LOW | Redis cache invalidation materialised all keys → async `scan_iter` + batched `UNLINK` (500/batch) |
| LOW | Temporal connection failure cached permanently → retry on next call |
| LOW | Audit JSONB payload unbounded → 64 KB cap with truncation |
| LOW | Empty policy list denied silently → warning log in policy_engine.py |
| LOW | Angular interceptor clobbered Clerk JWT with agr_sk_ key → skip override if Authorization already set |

---

## Docker Compose Setup

### Credentials (docker-compose.yml)
```
DB user:     agr_svc_usr
DB password: gKHTwJOC7SbVHUQw1hLfUcjLaJtnZvYfR_M2hixl
DB name:     agr_platform
SECRET_KEY:  4e993a8cbcb458e9823be7cc7215d42a57e1e56a3f90e8cdaa9334e9930d8dbf
```

### Root `.env` file (project root — gitignored)
Docker Compose auto-loads this file. Used for secrets that override compose defaults:
```bash
CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
CLERK_WEBHOOK_SECRET=whsec_...   # optional; blank = skip Svix verification
```
**Note**: Variables in `.env` are only injected into containers if listed in the service's `environment:` block in `docker-compose.yml` using `${VAR}` syntax.

### Services
```
postgres    — port 5432, volume: pgdata
redis       — port 6379
migrate     — one-shot, runs all 015 migrations then exits
agr-api     — port 8000, depends on postgres+redis+migrate healthy
agr-dashboard — port 4200, depends on agr-api healthy
```

---

## Testing

**Integration tests use SQLite in-memory (aiosqlite), NOT PostgreSQL.**

`conftest.py` fixtures:
- `test_org` — api_key: `agr_sk_testkey123456789012345678901234567890abcdef`
- `test_org_b` — for multi-tenant isolation tests
- `test_policies` — 3 default policies seeded
- `client` — TestClient patching both session factories
- `auth_headers`

```bash
# From repo root
pytest services/agr-api/tests/ -q --ignore=services/agr-api/tests/postgres  # 158 tests
pytest services/agr-api/tests/unit -v
pytest services/agr-api/tests/integration -v

ruff check .
ruff format --check .
mypy services/agr-api/app   # 39 source files, 0 issues
```

### PostgreSQL Integration Tests
Requires `PG_TEST_URL` env var. Auto-skip if unavailable.
```bash
docker compose -f docker-compose.test.yml up -d postgres-test
PG_TEST_URL=postgresql+asyncpg://agr_test:agr_test_password@localhost:5433/agr_test \
  pytest services/agr-api/tests/postgres/ -v
```

---

## Running Locally — Complete Setup

### Option A — Full Docker Compose (recommended)

```bash
git clone https://github.com/shreejaai/agr-platform.git
cd agr-platform

# Create root .env with Clerk keys
cat > .env <<EOF
CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
EOF

# Build and start everything (migrations run automatically via migrate service)
docker compose up --build

# API: http://localhost:8000
# Dashboard: http://localhost:4200
```

**First login flow:**
1. Open http://localhost:4200 → sign in with Clerk
2. Dashboard navigates to Settings, auto-fetches your `agr_sk_` key from the API
3. Key is stored in localStorage — all pages become available

### Option B — Local Python (hot reload)

```bash
# Start infra only
docker compose up -d postgres redis

# Install deps
cd services/agr-api
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run migrations (new DB credentials)
PGPASSWORD=gKHTwJOC7SbVHUQw1hLfUcjLaJtnZvYfR_M2hixl \
  psql -h localhost -U agr_svc_usr -d agr_platform \
  -f ../../infra/migrations/001_initial_schema.sql
# ... repeat for 002 through 015, or:
for i in $(seq -w 1 15); do
  f=$(ls ../../infra/migrations/0${i}_*.sql 2>/dev/null | head -1)
  [ -f "$f" ] && psql postgresql://agr_svc_usr:gKHTwJOC7SbVHUQw1hLfUcjLaJtnZvYfR_M2hixl@localhost:5432/agr_platform -f "$f"
done

# Update .env for local run
echo "DATABASE_URL=postgresql+asyncpg://agr_svc_usr:gKHTwJOC7SbVHUQw1hLfUcjLaJtnZvYfR_M2hixl@localhost:5432/agr_platform" >> .env

uvicorn app.main:app --reload --port 8000
```

### Common Commands

```bash
# List orgs
docker exec agr-platform-postgres-1 psql -U agr_svc_usr -d agr_platform \
  -c "SELECT id, name, api_key, eval_count FROM organizations;"

# View recent audit events
docker exec agr-platform-postgres-1 psql -U agr_svc_usr -d agr_platform \
  -c "SELECT event_type, agent_id, action, decision, recorded_at FROM audit_events ORDER BY recorded_at DESC LIMIT 20;"

# Flush Redis eval cache
docker compose exec redis redis-cli FLUSHDB

# Check logs
docker compose logs agr-api --tail=50 -f
docker compose logs agr-dashboard --tail=20
```

---

## Development Workflow & Deployment Rules

### Rule 1 — Branch Before You Touch Code

Every change happens on a branch. Never commit directly to `main`.

| Change type | Branch prefix |
|---|---|
| New feature | `feature/` |
| Bug fix | `fix/` |
| Refactor | `refactor/` |
| DB migration | `migration/` |
| Infra/deps | `chore/` |
| Hotfix | `hotfix/` |

### Rule 2 — Commit Message Format

```
<type>(<scope>): <short description>

<body — what changed and why>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `migration`

### Rule 3 — Every PR Must Pass

- `ruff check .` — zero warnings
- `ruff format --check .` — no reformatting needed
- `mypy services/agr-api/app` — zero errors
- `pytest services/agr-api/tests/ --ignore=.../postgres` — all pass (currently 158)

### Rule 4 — New Migration Rules

- Filename: `NNN_snake_case_description.sql` (next number in sequence, currently at 015)
- Must be idempotent (`IF NOT EXISTS`, `IF EXISTS`)
- Add to `infra/migrate.sh`
- Add rollback script in `infra/migrations/rollback/NNN_down.sql`

### Rule 5 — New Routes

- Create new file in `app/routes/`
- Register router in `app/main.py`
- Add request/response schemas to `app/schemas.py`
- Add to `UNPROTECTED_PATHS` in `app/middleware/auth.py` if no agr_sk_ auth needed

### Rule 6 — Session Patterns

```python
# Correct — always use flush(), never commit() in routes
session.add(obj)
await session.flush()
await session.refresh(obj)

# Correct — soft delete
obj.active = False
await session.flush()

# Correct — hard delete
await session.delete(obj)
await session.flush()   # explicit flush required

# Correct — org access (no Depends)
org_id: uuid.UUID = request.state.org_id
org: Organization = request.state.org
```

---

## What Is NOT Yet Implemented

- Cedar CLI subprocess wired end-to-end (policy_engine.py is Python regex fallback only)
- Temporal actual durable workflows (graceful DB-only fallback when TEMPORAL_HOST unset)
- Webhook dead-letter queue manual replay UI in dashboard
- Rollback scripts for migrations 014 and 015
- `openapi.json` auto-generation in CI
