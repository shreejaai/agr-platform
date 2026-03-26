# CLAUDE.md — AGR Platform

**GROUND TRUTH ONLY. Every section reflects actual code. Planned-but-not-built items marked `[NOT YET IMPLEMENTED]`.**

> Sub-directory context files exist for deep work:
> - `services/agr-api/CLAUDE.md` — API patterns, routes, tests, DB rules
> - `apps/agr-dashboard/CLAUDE.md` — Angular patterns, auth flow, commands

---

## What This Repo Is

**AGR (Agentic Governance Runtime)** — drop-in governance layer for AI agent frameworks. Every agent tool call is evaluated against Cedar policies before execution. Sensitive actions require human approval.

**Full-stack monorepo:** FastAPI backend (`services/agr-api/`) + Angular 17 dashboard (`apps/agr-dashboard/`).
**Owner:** Navneet — solo founder, Shreeja AI (`shreejaai.com`)

---

## How It Works (Mental Model)

```
Agent calls a tool
      ↓
POST /v1/evaluate
      ↓
Redis cache (60s TTL) → HIT: return cached, write audit
                      → MISS: continue below
      ↓
Cedar policy engine (Cedar CLI if on PATH, else Python regex fallback)
      ↓ ALLOW only (DENY/APPROVAL_REQUIRED final from Cedar)
Risk scoring (0-100, 5 factors) — can upgrade ALLOW → APPROVAL_REQUIRED or DENY
      ↓
Compliance hooks (advisory, fail-open) — EU AI Act, SOC2, ISO42001
      ↓
ALLOW             → agent executes
DENY              → agent blocked
APPROVAL_REQUIRED → DB row created → Temporal workflow → Resend email (if configured)
      ↓
Hash-chained audit event written (every path except 429)
```

---

## Repo Structure (key paths)

```
services/agr-api/          # FastAPI backend
  app/
    main.py                # App entry, CORS, AuthMiddleware, all routers
    config.py              # pydantic_settings.BaseSettings
    database.py            # get_session() — NOT get_db()
    models.py              # SQLAlchemy ORM: 6 tables
    schemas.py             # ALL Pydantic v2 schemas (single file)
    routes/                # One file per resource
    services/              # Business logic
    middleware/auth.py     # Bearer → org lookup → request.state.org
  tests/
    unit/                  # 158 tests total, SQLite in-memory
    integration/
    postgres/              # Requires PG_TEST_URL

apps/agr-dashboard/        # Angular 17 standalone
  src/app/
    core/auth/             # ClerkService, authGuard, apiKeyGuard
    core/http/             # api-key.interceptor, error.interceptor
    pages/                 # Feature pages
    services/              # HttpClient Observable services

packages/
  agr-core/                # policy_engine.py — Cedar CLI + Python fallback
  agr-sdk-python/          # AGRClient: evaluate(), wait_for_approval(), etc.
  agr-sdk-ts/              # TypeScript SDK (ESM+CJS)

infra/migrations/          # 001–015 forward + rollback/
```

---

## Development Rules

**Branch prefixes:** `feature/` `fix/` `refactor/` `migration/` `chore/` `hotfix/`

**Every PR must pass:**
```bash
ruff check .
ruff format --check .
mypy services/agr-api/app    # 0 errors
pytest services/agr-api/tests/ --ignore=.../postgres   # 158 tests
```

**Commit format:**
```
<type>(<scope>): <description>

<body>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

**New migration:** `NNN_*.sql` (next after 015) → add to `infra/migrate.sh` → write rollback in `infra/migrations/rollback/`

---

## Tech Stack (Live)

| Layer | Technology |
|-------|-----------|
| API | FastAPI 0.115, Python 3.12, async throughout |
| Policy | Cedar CLI → Python regex fallback |
| ORM | SQLAlchemy 2.0 async |
| DB | PostgreSQL 16, RLS on all 6 tables |
| Cache | Redis 7 (60s eval cache + rate limiting) |
| Workflows | Temporal (graceful degradation if unset) |
| Email | Resend (no-ops if key blank) |
| Auth | Clerk (dashboard) + agr_sk_ Bearer (API) |
| Dashboard | Angular 17, Tailwind, @clerk/clerk-js |

---

## What Is NOT Yet Implemented

- Cedar CLI subprocess wired end-to-end (Python regex fallback only)
- Temporal actual durable workflows (DB-only fallback when TEMPORAL_HOST unset)
- Rollback scripts for migrations 014 and 015
- `openapi.json` auto-generation in CI

---

## Docker Compose (local dev)

```bash
docker compose up --build    # API :8000, Dashboard :4200
docker compose up -d postgres redis   # infra only (for local Python dev)
```

DB credentials: `agr_svc_usr` / see `.env` / DB: `agr_platform`
