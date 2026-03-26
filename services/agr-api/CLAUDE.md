# AGR API — Developer Context

FastAPI async backend. Python 3.12, SQLAlchemy 2.0, Pydantic v2, PostgreSQL 16, Redis 7.

---

## Critical Patterns (never deviate)

```python
# Org access — NO Depends(), use request.state
org_id: uuid.UUID = request.state.org_id
org: Organization = request.state.org

# Session — flush, never commit in routes
session.add(obj)
await session.flush()
await session.refresh(obj)

# Hard delete — flush required
await session.delete(obj)
await session.flush()

# Soft delete (policies only — preserves audit FK)
obj.active = False
await session.flush()

# get_session() — NOT get_db()
```

## Route Rules
- New file in `app/routes/` → register in `app/main.py`
- New schemas → `app/schemas.py` (single file, all schemas)
- Unprotected route → add to `UNPROTECTED_PATHS` in `app/middleware/auth.py`
- `/import` and `/export` routes declared BEFORE `/{id}` in the router

## Database
- RLS on ALL 6 tables — `SET LOCAL app.current_org_id` via bindparam (never string interpolation)
- `audit_events` has NO FK to organizations (intentional)
- Migrations: `infra/migrations/NNN_*.sql`, numbered from 015 onward
- New migration: add to `infra/migrate.sh` + write `infra/migrations/rollback/NNN_down.sql`

## Key Files
- `app/schemas.py` — ALL Pydantic schemas
- `app/config.py` — pydantic_settings.BaseSettings (reads .env)
- `app/database.py` — `get_session()` dependency
- `app/middleware/auth.py` — AuthMiddleware + `set_rls_org()`
- `app/services/risk_service.py` — 0-100 risk scoring, 5 weighted factors
- `app/services/audit_service.py` — SHA-256 hash-chained audit log

## Decision Flow: POST /v1/evaluate
Redis cache (60s) → Cedar/Python policy engine → Risk scoring → Compliance hooks → Audit

Decision values: `ALLOW` | `DENY` | `APPROVAL_REQUIRED`
Rate limit: 429 when `org.eval_limit > 0 and org.eval_count >= org.eval_limit`
APPROVAL_REQUIRED is never cached.

## Test Commands
```bash
# From repo root
pytest services/agr-api/tests/ -q --ignore=services/agr-api/tests/postgres  # 158 tests
pytest services/agr-api/tests/unit -v
pytest services/agr-api/tests/integration -v

ruff check .
ruff format --check .
mypy services/agr-api/app   # must be 0 errors
```

## Test Fixtures (SQLite in-memory)
- `test_org` — `agr_sk_testkey123456789012345678901234567890abcdef`
- `test_org_b` — multi-tenant isolation
- `test_policies` — 3 default policies
- `client`, `auth_headers`
