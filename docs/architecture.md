# AGR Platform — Architecture Reference

**Date:** 2026-03-26
**Version:** 0.1.0

---

## System Overview

AGR (Agentic Governance Runtime) is a **drop-in governance layer** for AI agent frameworks. Every agent tool call is evaluated against Cedar policies before execution.

```
Agent Framework (LangGraph / CrewAI / custom)
        │
        │  POST /v1/evaluate
        ▼
┌─────────────────────────────────────────────────┐
│              AGR API (FastAPI)                  │
│                                                 │
│  AuthMiddleware → Redis cache → Cedar engine    │
│       → Risk scoring → Compliance hooks         │
│       → Audit log                               │
└────────────────┬────────────────────────────────┘
                 │
         ┌───────┴───────┐
         ▼               ▼
    PostgreSQL 16      Redis 7
    (RLS + hash        (eval cache
     chain audit)      + rate limit)
```

---

## Decision Flow

```
POST /v1/evaluate
        │
        ├─ Redis cache HIT? → return cached + write audit
        │
        ▼ MISS
Cedar policy engine
  ├─ Cedar CLI (if on PATH)
  └─ Python regex fallback
        │
        ▼ (if Cedar ALLOW)
Risk Scoring (0–100, 6 weighted factors)
  ├─ action_severity  (0.30)
  ├─ context_signals  (0.20)
  ├─ rate_pattern     (0.15)
  ├─ agent_trust      (0.15)  ← uses agents.trust_level column
  ├─ amount_scale     (0.10)
  └─ resource_sensitivity (0.10)
        │
        ├─ score > threshold_approval_max → DENY
        ├─ score > threshold_allow_max   → APPROVAL_REQUIRED
        └─ else                          → ALLOW (Cedar wins)
        │
        ▼
Compliance hooks (advisory, fail-open)
  └─ AuditTrailCompliancePlugin
        │
        ▼
Audit event (SHA-256 hash-chained, sequence per org)
        │
        ├─ ALLOW          → agent executes
        ├─ DENY           → agent blocked
        └─ APPROVAL_REQUIRED
                │
                ▼
        Temporal workflow (DB fallback if TEMPORAL_HOST unset)
                │
                ├─ Resend email (approve/reject links, HMAC-signed)
                └─ Slack Block Kit (if configured)
```

---

## Authentication

All API routes require `Authorization: Bearer agr_sk_<key>`.

**`AuthMiddleware`** (`app/middleware/auth.py`):
1. Extracts Bearer token
2. Looks up `Organization` by `api_key`
3. Sets `request.state.org`, `request.state.org_id`, `request.state.role`
4. Calls `SET LOCAL app.current_org_id` for PostgreSQL RLS

**RBAC roles**: `admin` | `operator` | `viewer`
Role enforcement via `require_role(min_role)` dependency in `app/dependencies.py`.

---

## Tenant Isolation

Two-layer defense:
1. **RLS** — PostgreSQL Row Level Security on all 6 tables (`SET LOCAL app.current_org_id`)
2. **Explicit WHERE** — every route adds `Model.org_id == org_id` in all queries

See [`docs/tenant_isolation_audit.md`](tenant_isolation_audit.md) for full audit.

---

## Database Schema

| Table | Purpose | RLS |
|-------|---------|-----|
| `organizations` | Org + API key + RBAC role | API key auth |
| `policies` | Cedar policy rules + lifecycle state | `app.current_org_id` |
| `policy_versions` | Immutable policy snapshots | (via CASCADE) |
| `approval_requests` | Pending human approvals | `app.current_org_id` |
| `approval_steps` | Multi-step quorum approvers | `app.current_org_id` |
| `agents` | Registered agent profiles + trust_level | `app.current_org_id` |
| `org_risk_configs` | Per-org risk weight overrides | `app.current_org_id` |
| `webhooks` | Push notification endpoints | `app.current_org_id` |
| `webhook_deliveries` | Delivery attempt log | `app.current_org_id` |
| `audit_events` | Hash-chained immutable audit log | `app.current_org_id` |
| `copilot_conversations` | AI assistant history | `app.current_org_id` |
| `copilot_messages` | Conversation messages | (via FK) |

---

## Policy Lifecycle

```
draft → active → archived
```

- **draft**: created but not evaluated by Cedar
- **active**: included in Cedar evaluation
- **archived**: soft-deleted, never re-activated

Version history is captured in `policy_versions` before every content-changing PATCH.

---

## Risk Scoring

Six weighted factors, configurable per-org via `GET/PUT /v1/org/risk-config`:

| Factor | Default Weight | Source |
|--------|---------------|--------|
| `action_severity` | 0.30 | Action name keywords |
| `context_signals` | 0.20 | Context key/value patterns |
| `rate_pattern` | 0.15 | Org eval usage vs. limit |
| `agent_trust` | 0.15 | `agents.trust_level` column |
| `amount_scale` | 0.10 | Numeric values in context |
| `resource_sensitivity` | 0.10 | Resource name keywords |

---

## Observability

- **`GET /health`** — liveness probe (always 200)
- **`GET /health/ready`** — readiness probe (DB + Redis + Cedar CLI)
- **`GET /metrics`** — Prometheus text format:
  - `agr_evaluations_total{decision}`
  - `agr_risk_score` histogram
  - `agr_approval_decisions_total{decision}`
  - `agr_policy_changes_total{operation}`
  - `agr_webhook_deliveries_total{status}`
- **Structured logging** — JSON-compatible with request_id injection
- **Audit chain verify** — `GET /v1/audit/verify` walks SHA-256 hash chain

---

## Migrations

Forward migrations: `infra/migrations/001_*.sql` → `023_*.sql`
Rollbacks: `infra/migrations/rollback/NNN_down.sql`
Runner: `infra/migrate.sh`

New migration checklist:
1. Create `infra/migrations/NNN_*.sql`
2. Create `infra/migrations/rollback/NNN_down.sql`
3. Add to `infra/migrate.sh`
4. Update ORM models in `app/models.py`
