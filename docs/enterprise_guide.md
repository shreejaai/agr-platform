# AGR Enterprise Guide

**Date:** 2026-03-26

This guide covers enterprise-specific features: RBAC, per-org risk tuning, multi-step approvals, compliance, audit export, and webhook management.

---

## RBAC (Role-Based Access Control)

Every organization has a `role` column on its API key:

| Role | Permissions |
|------|------------|
| `admin` | Full access — create/update/delete anything |
| `operator` | Create and update resources; cannot delete or rotate secrets |
| `viewer` | Read-only — GET endpoints only |

**Setting a role** (requires admin API key):
```bash
# Via database (no API endpoint yet — set at org creation or via DB migration)
UPDATE organizations SET role = 'operator' WHERE id = '<org-uuid>';
```

**Role enforcement**: `require_role("admin")` dependency on destructive endpoints:
- `DELETE /v1/policies/{id}`
- `PUT /v1/org/risk-config`
- `POST /v1/webhooks/{id}/rotate-secret`

---

## Per-Org Risk Scoring Configuration

Override default risk weights and decision thresholds per organization.

```bash
# GET current config
GET /v1/org/risk-config

# UPDATE weights (must be admin role)
PUT /v1/org/risk-config
{
  "weight_action_severity": 0.40,
  "weight_resource_sensitivity": 0.15,
  "threshold_allow_max": 25,
  "threshold_approval_max": 65
}
```

**Constraints**:
- All weights are 0.0–1.0
- `threshold_allow_max < threshold_approval_max` (enforced server-side)
- Changes take effect on the next evaluation (no cache invalidation needed)

**Risk factors** (6 total):

| Factor | What it measures |
|--------|----------------|
| `action_severity` | How destructive the action is (drop, delete, exec = high) |
| `context_signals` | Risky context keys/values (production, admin, bulk) |
| `rate_pattern` | How close the org is to its eval rate limit |
| `agent_trust` | Agent's `trust_level` column (trusted/verified/unknown/untrusted) |
| `amount_scale` | Large numeric values in context (amounts, counts) |
| `resource_sensitivity` | How sensitive the resource name is (prod, PII, billing) |

---

## Agent Trust Levels

Register agents with a typed `trust_level` to tune risk scoring:

```bash
POST /v1/agents/register
{
  "agent_id": "finance-agent-v2",
  "name": "Finance Agent",
  "owner": "finance-team@company.com",
  "framework": "LangGraph",
  "environment": "production",
  "trust_level": "verified",
  "capabilities": ["read_transactions", "query_reports"]
}
```

| `trust_level` | Risk contribution | Use for |
|--------------|------------------|---------|
| `trusted` | 0 (no risk) | Internal, fully audited agents |
| `verified` | 5 | Reviewed agents with known behavior |
| `unknown` | 15 (default) | New or unreviewed agents |
| `untrusted` | 50 (high risk) | External or legacy agents |

---

## Multi-Step Approvals

Configure quorum-based approval flows:

```bash
# 1. Create an approval (from evaluate response)
#    approval_id returned in APPROVAL_REQUIRED decision

# 2. Add approvers
POST /v1/approvals/{id}/steps
{ "approver_email": "reviewer@company.com" }

POST /v1/approvals/{id}/steps
{ "approver_email": "manager@company.com" }

# 3. List steps
GET /v1/approvals/{id}/steps

# 4. First approver's email link resolves when quorum_type='any'
#    All approvers must approve when quorum_type='all'
```

**SLA and escalation**: Set `sla_hours` and `escalation_email` on the approval request for time-based escalation notifications (storage is wired; Temporal workflow handles auto-escalation when configured).

---

## Audit Log

### Querying

```bash
# Extended filters (Task 14)
GET /v1/audit?action=delete&decision=DENY&start_date=2026-01-01T00:00:00Z

# POST search (complex filters)
POST /v1/audit/search
{
  "decision": "APPROVAL_REQUIRED",
  "agent_id": "finance-agent-v2",
  "start_date": "2026-03-01T00:00:00Z",
  "end_date": "2026-03-26T23:59:59Z",
  "limit": 100
}
```

### Export

```bash
# Stream CSV (up to 50,000 rows)
POST /v1/audit/export
{ "decision": "DENY", "start_date": "2026-03-01T00:00:00Z" }
# Returns: Content-Disposition: attachment; filename=audit_export.csv
```

### Hash Chain Verification

```bash
GET /v1/audit/verify
# Returns: { "valid": true, "total": 12847, "first_invalid_sequence": null }
```

---

## Compliance Summary

```bash
GET /v1/compliance/summary?period_days=30
```

Returns:
```json
{
  "period_days": 30,
  "total_evaluations": 5420,
  "decisions": {"ALLOW": 4800, "DENY": 320, "APPROVAL_REQUIRED": 300},
  "high_risk_count": 87,
  "findings_by_standard": {
    "EU_AI_ACT": {"pass": 5420, "fail": 0},
    "SOC2": {"pass": 5420, "fail": 0}
  },
  "overall_pass": true
}
```

---

## Webhook Management

### Event Types (expanded in Task 17)

| Event | Triggered when |
|-------|---------------|
| `approval.approved` | Approval decision: approved |
| `approval.rejected` | Approval decision: rejected |
| `evaluation.completed` | Every evaluation completes |
| `policy.changed` | Policy created/updated/archived |
| `agent.updated` | Agent profile updated |

### Rotate Secret

```bash
# Generates new HMAC secret — old secret is immediately invalid
POST /v1/webhooks/{id}/rotate-secret
# Returns: { "id": "...", "new_secret": "agr_wh_..." }
```

### Test Delivery

```bash
# Send a test ping to verify connectivity
POST /v1/webhooks/{id}/test
# Returns: { "delivery_id": "...", "status": "success", "http_status": 200 }
```

---

## Observability

### Prometheus Metrics

Scrape `GET /metrics` (no auth required) for:

```
agr_evaluations_total{decision="ALLOW"} 4800
agr_evaluations_total{decision="DENY"} 320
agr_risk_score_bucket{le="30"} 3200
agr_approval_decisions_total{decision="approved"} 180
agr_policy_changes_total{operation="create"} 45
agr_webhook_deliveries_total{status="delivered"} 1200
```

### Recommended Alerts

```yaml
# Alert on high DENY rate
- alert: HighDenyRate
  expr: rate(agr_evaluations_total{decision="DENY"}[5m]) > 0.1

# Alert on pending approvals > 1h
- alert: StaleApprovals
  expr: agr_approval_decisions_total{decision="pending"} > 0
  for: 1h
```

---

## Policy Lifecycle Best Practices

1. **Always create as `draft`** — review before activating
2. **Use `/v1/policies/{id}/activate`** to put policies into evaluation
3. **Check conflicts** — advisory warnings in create/update responses
4. **Version history** — every PATCH creates an immutable snapshot; rollback via `/v1/policies/{id}/rollback/{version}`
5. **Archive, don't delete** — `DELETE` soft-archives; FK references in audit log are preserved
