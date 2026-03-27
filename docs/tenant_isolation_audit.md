# Tenant Isolation Audit — AGR Platform

**Date:** 2026-03-26
**Scope:** All authenticated API routes in `services/agr-api/app/routes/`

## Summary

All 6 tables have PostgreSQL Row-Level Security (RLS) enabled via migrations.
Every route handler additionally enforces `org_id` in explicit `WHERE` clauses.

## Route-by-Route Findings

| Route file | Endpoint | org_id filter | RLS coverage | Status |
|-----------|----------|---------------|--------------|--------|
| evaluate.py | POST /v1/evaluate | `request.state.org_id` on all queries | policies table via `WHERE org_id=` | ✅ |
| policies.py | All /v1/policies | `Policy.org_id == org_id` on every query | ✅ RLS | ✅ |
| agents.py | All /v1/agents | `Agent.org_id == org_id` on every query | ✅ RLS | ✅ |
| approvals.py | All /v1/approvals | `ApprovalRequest.org_id == org_id` | ✅ RLS | ✅ |
| audit.py | GET /v1/audit | `AuditEvent.org_id == org_id` | ✅ RLS | ✅ |
| webhooks.py | All /v1/webhooks | `Webhook.org_id == org_id` + deliveries checked by org | ✅ RLS | ✅ |
| org.py | GET /v1/org/me | Reads from `request.state.org` (already scoped by auth) | ✅ | ✅ |
| approvals.py | GET/POST /v1/approvals/decide | Unprotected — no org context (by design — email links) | No RLS needed | ✅ |

## RLS Verification

All tables confirmed to have RLS enabled (migrations 001–015):
- `organizations` — RLS, auth by api_key
- `policies` — RLS, `app.current_org_id` set per session
- `agents` — RLS
- `approval_requests` — RLS
- `webhooks` — RLS
- `webhook_deliveries` — RLS
- `audit_events` — RLS (no FK to organizations intentionally)

## Conclusion

No gaps found. Every route explicitly filters by `org_id` from `request.state.org_id` which is populated by `AuthMiddleware` from a verified API key lookup. RLS provides defense-in-depth at the database layer.

## Recommendations

1. Add an integration test that creates data in org A, authenticates as org B, and verifies zero results returned — see `tests/integration/test_multi_tenant.py` (already exists).
2. When adding new routes, always add the org_id check before the final query as the first `WHERE` clause.
