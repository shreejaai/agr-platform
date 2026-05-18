# AGR Platform — Complete Hardening Plan

**Date:** 2026-05-18
**Owner:** Navneet
**Status:** Proposed
**Source review:** CTO-grade analysis dated 2026-05-18 (this chat)

This plan turns every issue surfaced in the architectural review into a concrete, ordered, testable workstream. Items are grouped into 5 waves so each wave is independently shippable, each PR is small, and each wave unlocks the next.

---

## Wave Map

| Wave | Theme | Why it's first |
|------|-------|----------------|
| **W1** | Decision-path safety (Cedar fallback, policy shape, constant-time, CORS) | These are correctness/security bugs in the *hot path*. Nothing else matters if `/v1/evaluate` can silently return wrong answers. |
| **W2** | Approval UX correctness (LangChain/CrewAI, SLA, escalation, reminders) | Approvals are the differentiating feature. Currently broken end-to-end inside framework plugins. |
| **W3** | Observability + resilience (metrics, circuit breakers, rate-limit safety, audit jobs) | Required before we can sell to anyone with an SRE team. |
| **W4** | Scale & infra (migrations, pagination, audit export durability, DB pool, openapi drift) | Stability under realistic load. |
| **W5** | CI/CD hardening (Postgres tests, e2e, dashboard tests, openapi diff, copilot RAG) | Long-lived quality moat + roadmap upside. |

Each task below has: **Files**, **Change**, **Tests**, **Acceptance**.

---

## WAVE 1 — Decision-Path Safety

### W1.1 — Cedar fallback must not silently degrade in production

**Severity:** 🔴 High
**Problem:** If Cedar CLI is missing, the API silently uses the regex-based Python evaluator which is not semantically equivalent. Risk: wrong ALLOW/DENY.

**Files**
- [services/agr-api/app/config.py](services/agr-api/app/config.py)
- [services/agr-api/app/main.py](services/agr-api/app/main.py)
- [services/agr-api/app/services/cedar_service.py](services/agr-api/app/services/cedar_service.py)
- [services/agr-api/app/routes/health.py](services/agr-api/app/routes/health.py)
- [services/agr-api/app/routes/evaluate.py](services/agr-api/app/routes/evaluate.py)
- [packages/agr-core/policy_engine.py](packages/agr-core/policy_engine.py)

**Change**
1. Default `cedar_require_cli = True` when `env == "production"` (override only via explicit `CEDAR_REQUIRE_CLI=false`).
2. `validate_production_settings()` fails startup if `cedar_require_cli=True` and Cedar CLI not found.
3. `/health/ready` returns `503` when `engine_mode == "python_fallback"` AND `cedar_require_cli=True`.
4. Every evaluate response already returns `engine_mode`; add `X-AGR-Engine-Mode` response header.
5. Emit structured log `event="cedar_fallback_used"` at WARN with org_id + policy_id on every fallback hit (rate-limited per minute to avoid log flood).

**Tests**
- New unit: `tests/unit/test_cedar_require_cli.py` — env=prod + no CLI → startup raises.
- New integration: `tests/integration/test_health_engine_mode.py` — force fallback, assert 503 on `/health/ready`.

**Acceptance**
- `make dev` in prod mode without Cedar CLI fails to boot.
- Dashboard shows red banner when org sees any fallback in last hour (W3.1 covers UI).

---

### W1.2 — Policy shape validation at create time

**Severity:** 🔴 High
**Problem:** Approval detection requires the exact `forbid(...) unless { context.approval_status == "approved" }` shape. Other valid Cedar policies will produce wrong behavior.

**Files**
- [services/agr-api/app/routes/policies.py](services/agr-api/app/routes/policies.py)
- [services/agr-api/app/services/policy_import_service.py](services/agr-api/app/services/policy_import_service.py)
- [packages/agr-core/policy_engine.py](packages/agr-core/policy_engine.py) (export validator)
- [services/agr-api/app/schemas.py](services/agr-api/app/schemas.py)

**Change**
1. Add `validate_policy_shape(cedar_rule) -> ValidationResult` in `policy_engine.py`. Checks:
   - Parses with Cedar CLI when available (preferred).
   - Detects approval pattern; if `forbid` + `unless` present but not the canonical shape, reject with explicit error message.
   - Detects unsupported constructs when CLI unavailable (`has`, set ops) and warns.
2. Call validator from policy create/update and from import service.
3. Return `400` with structured `{error, hint, doc_url}` on invalid shape.

**Tests**
- `tests/unit/test_policy_shape_validation.py` — table-driven good/bad samples.
- `tests/integration/test_policies.py` — invalid shape returns 400 with hint.

**Acceptance**
- All existing `examples/policy_packs/*.yaml` pass validation in CI.

---

### W1.3 — Constant-time API key comparison

**Severity:** 🟠 Medium
**Files**
- [services/agr-api/app/middleware/auth.py](services/agr-api/app/middleware/auth.py)

**Change**
- Replace all hash `==` comparisons with `hmac.compare_digest(a.encode(), b.encode())`.
- Add `_safe_eq()` helper; use for org key, scoped api key hash, AuthSession token.

**Tests**
- Existing `tests/integration/test_clerk_api_key.py` and `test_api_keys.py` must still pass; add one micro-bench style sanity test.

**Acceptance**
- Grep shows no `==` on token/hash values in `middleware/auth.py`.

---

### W1.4 — Production settings validation broadened

**Severity:** 🟠 Medium
**Files**
- [services/agr-api/app/config.py](services/agr-api/app/config.py)
- [services/agr-api/app/main.py](services/agr-api/app/main.py)

**Change**
`validate_production_settings()` extended to assert (when `env == "production"`):
- `secret_key` not the dev default (already done).
- `cors_origins != ["*"]`.
- `redis_url` non-empty.
- `database_url` not pointing at `sqlite`.
- `cedar_require_cli` True OR explicit `AGR_ALLOW_CEDAR_FALLBACK_PROD=1`.
- `webhook_timeout <= 30`.
- `temporal_host` set OR explicit `AGR_ALLOW_DB_ONLY_APPROVALS=1`.

**Tests**
- `tests/unit/test_config_prod_safety.py` — parameterized.

**Acceptance**
- Misconfigured prod boot fails with one clear actionable message per problem.

---

### W1.5 — Global request body size limit

**Severity:** 🟠 Medium
**Files**
- new `services/agr-api/app/middleware/body_limit.py`
- [services/agr-api/app/main.py](services/agr-api/app/main.py)

**Change**
- ASGI middleware enforcing `settings.max_request_body_bytes` (default 256 KB).
- Returns 413 with structured error.

**Acceptance**
- Posting 1MB body to `/v1/evaluate` returns 413.

---

## WAVE 2 — Approval UX Correctness

### W2.1 — Framework plugins: return PendingApproval, do not raise

**Severity:** 🔴 High
**Files**
- [packages/agr-langchain/tool_guard.py](packages/agr-langchain/tool_guard.py)
- [packages/agr-langchain/callback_handler.py](packages/agr-langchain/callback_handler.py)
- [packages/agr-sdk-python/agr/plugins/langgraph.py](packages/agr-sdk-python/agr/plugins/langgraph.py)
- [packages/agr-sdk-python/agr/plugins/crewai.py](packages/agr-sdk-python/agr/plugins/crewai.py)
- [packages/agr-sdk-python/agr/client.py](packages/agr-sdk-python/agr/client.py)

**Change**
1. Introduce `PendingApprovalResult` dataclass in `agr-sdk-python` (approval_id, action, resource, expires_at, dashboard_url).
2. Tool guard branching:
   - `ALLOW` → run wrapped tool.
   - `DENY` → raise `ToolException` (correct).
   - `APPROVAL_REQUIRED` → return `PendingApprovalResult` *and* expose `await_decision` helper.
3. New `AGRClient.await_decision(approval_id, *, poll_interval=2.0, timeout=3600)`.
4. Add `mode="block_until_resolved"` to `AGRToolGuard` for users who want sync semantics; defaults to non-blocking.

**Tests**
- `tests/unit/test_langgraph_plugin.py` extended for PendingApproval path.
- New integration: `tests/integration/test_approval_flow_framework.py` using a stubbed LangGraph node.

**Acceptance**
- `examples/python/03_langgraph_agent.py` and `04_crewai_agent.py` show end-to-end approval gating without exceptions.

---

### W2.2 — Honor `sla_hours`; remove hardcoded 48h

**Severity:** 🟠 Medium
**Files**
- [services/agr-api/app/services/approval_service.py](services/agr-api/app/services/approval_service.py)
- [services/agr-api/app/workflows/approval_workflow.py](services/agr-api/app/workflows/approval_workflow.py)
- [services/agr-api/app/routes/approvals.py](services/agr-api/app/routes/approvals.py)
- [services/agr-api/app/schemas.py](services/agr-api/app/schemas.py)

**Change**
1. `create_approval_request` computes `expires_at = now + timedelta(hours=approval.sla_hours or settings.default_sla_hours)`.
2. Workflow `wait_condition` timeout = `min(sla_hours, 168)`; reminder fires at 50% of SLA, not fixed 24h.
3. Workflow `execution_timeout = sla_hours + 2h` buffer; eliminates 48h vs 50h race.
4. Add `settings.default_sla_hours = 48`.

**Tests**
- `tests/unit/test_approval_service.py` parameterized: 1h, 24h, 72h SLAs.
- New workflow test using `temporalio.testing.WorkflowEnvironment`.

**Acceptance**
- Approval with `sla_hours=2` expires at exactly +2h; reminder fires at +1h.

---

### W2.3 — Real reminder notification, not log warning

**Severity:** 🟠 Medium
**Files**
- [services/agr-api/app/workflows/approval_workflow.py](services/agr-api/app/workflows/approval_workflow.py)
- [services/agr-api/app/services/notification_service.py](services/agr-api/app/services/notification_service.py)
- new activity in `services/agr-api/app/workflows/activities.py`

**Change**
1. Convert reminder branch into a real Temporal activity `send_approval_reminder(approval_id)`.
2. Activity calls `notification_service.send_reminder(...)` → Resend + Slack.
3. Add `reminder_sent_at` column via migration `031_approval_reminder_audit.sql`.

**Tests**
- Mock notification_service; assert called once when SLA halves.

**Acceptance**
- Pending approval at 50% SLA receives a reminder email/Slack with a single dashboard link.

---

### W2.4 — Escalation extends expiry

**Severity:** 🟡 Low
**Files**
- [services/agr-api/app/routes/approvals.py](services/agr-api/app/routes/approvals.py)
- [services/agr-api/app/services/approval_service.py](services/agr-api/app/services/approval_service.py)
- workflow signal handler

**Change**
- `POST /v1/approvals/{id}/escalate` extends `expires_at` by `settings.escalation_extension_hours` (default 24h) capped at 7d.
- Workflow handles `escalate` signal by re-arming wait_condition.

**Tests**
- `tests/integration/test_approvals.py` — escalate updates expiry; second escalate caps at 7d.

**Acceptance**
- UI shows new countdown after escalation.

---

### W2.5 — Tenant ↔ Clerk provisioning race fix

**Severity:** 🔴 High
**Files**
- [services/agr-api/app/routes/clerk.py](services/agr-api/app/routes/clerk.py)
- [services/agr-api/app/services/org_service.py](services/agr-api/app/services/org_service.py)
- [apps/agr-dashboard/src/app/core/auth/clerk.service.ts](apps/agr-dashboard/src/app/core/auth/clerk.service.ts)

**Change**
1. `/v1/clerk/api-key` does just-in-time provisioning:
   - Look up org by `clerk_org_id`.
   - If absent and JWT proves Clerk org membership, create org row idempotently (`ON CONFLICT (clerk_org_id) DO NOTHING`).
   - Issue scoped API key.
2. Remove the 3-retry hack from dashboard; keep one retry with 500ms backoff for transient 502s only.

**Tests**
- `tests/integration/test_clerk_api_key.py` — webhook deliberately delayed; first dashboard call still succeeds.

**Acceptance**
- New tenant can sign in and reach dashboard within 1 request, no race.

---

## WAVE 3 — Observability & Resilience

### W3.1 — Prometheus `/metrics` endpoint

**Severity:** 🔴 High (for enterprise readiness)
**Files**
- new `services/agr-api/app/observability/metrics.py`
- [services/agr-api/app/main.py](services/agr-api/app/main.py)
- [services/agr-api/app/routes/evaluate.py](services/agr-api/app/routes/evaluate.py)
- [services/agr-api/app/services/cedar_service.py](services/agr-api/app/services/cedar_service.py)
- [services/agr-api/app/services/temporal_service.py](services/agr-api/app/services/temporal_service.py)
- [services/agr-api/app/services/webhook_service.py](services/agr-api/app/services/webhook_service.py)
- [services/agr-api/app/services/audit_service.py](services/agr-api/app/services/audit_service.py)

**Change**
Add `prometheus_client` and expose at `/metrics` (no auth, but rate-limited and on a separate port if `metrics_port` set).

Counters / histograms:
- `agr_evaluate_decision_total{decision,engine_mode}`
- `agr_evaluate_latency_ms` (histogram, low-cardinality buckets)
- `agr_cedar_engine_mode_total{mode}`
- `agr_cedar_pool_inflight` (gauge)
- `agr_approval_workflow_fallback_total{mode}`
- `agr_webhook_delivery_total{status}`
- `agr_webhook_delivery_latency_ms`
- `agr_audit_chain_break_total` (incremented on verify failure)
- `agr_rate_limit_drop_total`

**Tests**
- `tests/integration/test_metrics.py` — emits, parses.

**Acceptance**
- `curl :8000/metrics` returns Prometheus exposition format.

---

### W3.2 — Circuit breaker for Temporal

**Severity:** 🟠 Medium
**Files**
- [services/agr-api/app/services/temporal_service.py](services/agr-api/app/services/temporal_service.py)

**Change**
- Add lightweight in-process circuit breaker (purepython, no dep): closed → open after 5 consecutive failures within 30s; open for 30s; half-open allows 1 probe.
- When OPEN: skip retries; immediately return `db_only_temporal_unavailable`.
- Expose state via gauge `agr_temporal_circuit_state{state}`.

**Tests**
- Unit: simulate failures; assert breaker opens, half-opens, closes.

**Acceptance**
- Temporal outage no longer adds 1.5s to every `/evaluate` triggering approvals.

---

### W3.3 — Rate-limit hard mode option (no fail-open in prod)

**Severity:** 🟠 Medium
**Files**
- [services/agr-api/app/middleware/rate_limiter.py](services/agr-api/app/middleware/rate_limiter.py)
- [services/agr-api/app/config.py](services/agr-api/app/config.py)

**Change**
- Add `rate_limit_fail_mode = "open" | "closed"` (default `open` for dev, `closed` for prod).
- When Redis fails and mode=closed: respond 503 with `Retry-After: 5`; emit metric `agr_rate_limit_redis_unavailable_total`.
- Always log CRITICAL on Redis loss.

**Acceptance**
- Prod with Redis down returns 503, not unbounded traffic.

---

### W3.4 — Compliance plugin timeout

**Severity:** 🟡 Low
**Files**
- [services/agr-api/app/services/compliance_service.py](services/agr-api/app/services/compliance_service.py)

**Change**
- Wrap each plugin in `asyncio.wait_for(plugin.check(ctx), timeout=settings.compliance_plugin_timeout_ms / 1000)`.
- Timeout treated as fail-open (advisory) but recorded as finding `severity=warning`.

**Acceptance**
- Misbehaving plugin can no longer block `/evaluate` indefinitely.

---

### W3.5 — Audit export job durability

**Severity:** 🟠 Medium
**Files**
- new `infra/migrations/032_audit_export_jobs.sql` + rollback
- [services/agr-api/app/services/audit_service.py](services/agr-api/app/services/audit_service.py)
- [services/agr-api/app/routes/audit.py](services/agr-api/app/routes/audit.py)

**Change**
1. Persist export jobs to DB (`audit_export_jobs` table: id, org_id, status, filters, started_at, finished_at, output_uri, error).
2. Replace in-memory dict with DB queries.
3. Worker picks up jobs on boot to resume incomplete exports (or marks them `failed_restart`).

**Acceptance**
- Restarting API pod mid-export does not lose the export.

---

### W3.6 — Webhook replay nonce

**Severity:** 🟡 Low
**Files**
- [services/agr-api/app/services/webhook_service.py](services/agr-api/app/services/webhook_service.py)
- docs

**Change**
- Add `X-AGR-Webhook-Id` header (UUID per delivery).
- Document that verifiers must enforce: `|now - t| < 300s` AND `id` not seen recently.
- SDKs include verifier helper using both.

---

### W3.7 — Cedar service stops walking the tree

**Severity:** 🟡 Low (cleanup)
**Files**
- [services/agr-api/app/services/cedar_service.py](services/agr-api/app/services/cedar_service.py)
- [packages/agr-core/setup.py](packages/agr-core) (add if missing)
- [services/agr-api/requirements.txt](services/agr-api/requirements.txt)

**Change**
- Make `agr-core` a real installable package (`pip install -e packages/agr-core`).
- Remove path-walking in `cedar_service.py`; just `from agr_core.policy_engine import ...`.

**Acceptance**
- Moving the file tree does not break imports.

---

## WAVE 4 — Scale & Infra

### W4.1 — Transactional migration runner

**Severity:** 🟠 Medium
**Files**
- [infra/migrate.sh](infra/migrate.sh)
- new `infra/migrations/rollback/014_down.sql`, `015_down.sql`, `030_down.sql`, `031_*`, `032_*`

**Change**
- Wrap each forward and rollback file in `BEGIN; ... COMMIT;` with `psql -v ON_ERROR_STOP=on`.
- Track applied migrations in `schema_migrations` table (filename, sha256, applied_at).
- Refuse to apply if content sha changed after first apply.

**Tests**
- New shell test in CI: fail a fake migration mid-file, assert rollback occurred.

**Acceptance**
- All 14, 15, 30 rollbacks present and tested. `make db-migrate` is idempotent.

---

### W4.2 — Audit pagination (server + UI)

**Severity:** 🔴 High
**Files**
- [services/agr-api/app/routes/audit.py](services/agr-api/app/routes/audit.py)
- [apps/agr-dashboard/src/app/pages/audit/audit.component.ts](apps/agr-dashboard/src/app/pages/audit/audit.component.ts)
- [apps/agr-dashboard/src/app/services/audit.service.ts](apps/agr-dashboard/src/app/services/audit.service.ts)

**Change**
1. Cursor-based pagination: `?after=<sequence_num>&limit=100`.
2. Response includes `next_cursor`.
3. Dashboard uses CDK virtual scroll, fetches next page at 80% scroll.

**Tests**
- `tests/integration/test_audit.py` — cursor walk yields complete ordered set.

**Acceptance**
- 50k-event org loads instantly; smooth scroll.

---

### W4.3 — DB pool tuning + PgBouncer doc

**Severity:** 🟡 Low
**Files**
- [services/agr-api/app/database.py](services/agr-api/app/database.py)
- [docs/architecture.md](docs/architecture.md)

**Change**
- Settings: `db_pool_size`, `db_max_overflow`, `db_pool_recycle` (default 1800).
- Add docs section: PgBouncer in transaction-pooling mode behind multi-pod; what session-level features (RLS `set_config`) require `SET LOCAL` (already used — confirm).

---

### W4.4 — Cedar pool autosize + pre-warm

**Severity:** 🟠 Medium
**Files**
- [packages/agr-core/policy_engine.py](packages/agr-core/policy_engine.py)
- [services/agr-api/app/services/cedar_service.py](services/agr-api/app/services/cedar_service.py)

**Change**
- Default `cedar_pool_size = max(4, os.cpu_count())`.
- Pre-warm workers in `lifespan` startup (spawn + cold-call once).
- Expose `agr_cedar_pool_size` and `agr_cedar_pool_busy` gauges.

---

### W4.5 — OpenAPI drift detection

**Severity:** 🟠 Medium
**Files**
- [scripts/export_openapi.py](scripts/export_openapi.py)
- [.github/workflows/ci.yml](.github/workflows/ci.yml)
- [openapi.json](openapi.json)

**Change**
- CI job runs `python scripts/export_openapi.py --check` — diffs against checked-in `openapi.json`. Fails if drift.
- SDK release docs reference openapi commit.

**Acceptance**
- Adding a route without regenerating fails CI.

---

## WAVE 5 — CI/CD Hardening + Copilot RAG

### W5.1 — Gate Postgres tests in CI

**Severity:** 🔴 High
**Files**
- [.github/workflows/ci.yml](.github/workflows/ci.yml)
- [services/agr-api/tests/postgres/conftest.py](services/agr-api/tests/postgres/conftest.py)

**Change**
- Spin up `postgres:16` service in CI job.
- Run `pytest tests/postgres -v`. No `continue-on-error`.

**Acceptance**
- RLS, JSONB, partitioning, constraint tests block merges.

---

### W5.2 — Wire e2e Playwright suite

**Severity:** 🟠 Medium
**Files**
- [.github/workflows/ci.yml](.github/workflows/ci.yml)
- [tests/e2e/playwright.config.ts](tests/e2e/playwright.config.ts)
- [docker-compose.test.yml](docker-compose.test.yml)

**Change**
- New CI job `e2e`: brings up compose stack, seeds fixtures, runs `npm run test:smoke` then a single domain suite (rotate per-PR via matrix).
- Fail PR if any domain smoke fails.

---

### W5.3 — Dashboard tests must be required

**Severity:** 🟠 Medium
**Files**
- [.github/workflows/ci.yml](.github/workflows/ci.yml)
- [apps/agr-dashboard/karma.conf.js](apps/agr-dashboard/karma.conf.js)

**Change**
- Remove `continue-on-error: true` from dashboard test step.
- Stabilize: switch to `ChromeHeadlessNoSandbox` (already there) + `--single-run` + `--no-progress`; fix the actual flakes (likely timer-based in approvals/copilot).
- Alternative: migrate spec runner to Vitest if Karma keeps flaking (separate PR, tracked but not in this wave).

---

### W5.4 — Copilot retrieval over org policies/audit/tests

**Severity:** 🟡 Low (roadmap upside)
**Files**
- [services/agr-api/app/services/copilot_service.py](services/agr-api/app/services/copilot_service.py)
- [services/agr-api/app/services/copilot_prompts.py](services/agr-api/app/services/copilot_prompts.py)
- new `services/agr-api/app/services/copilot_retrieval.py`
- migration `033_copilot_embeddings.sql` (pgvector extension)

**Change**
1. Enable `pgvector` extension.
2. Embed each policy + each policy test suite case + recent audit event summaries; store in `policy_embeddings` table.
3. On copilot turn: retrieve top-k for the user's query, splice into the prompt as `<org_context>` block.
4. Strict tenant filtering: all retrieval queries include `org_id = :org_id` *and* rely on RLS.

**Acceptance**
- Copilot can answer "why did agent X get denied yesterday on deploy_prod?" using actual org data.

---

### W5.5 — Anomaly detection: embedding-based, advisory

**Severity:** 🟡 Low
**Files**
- [services/agr-api/app/services/anomaly_service.py](services/agr-api/app/services/anomaly_service.py)

**Change**
- Add advisory signal: cosine distance of current `(agent_id, action, resource)` embedding vs trailing 30d distribution.
- Threshold breach emits compliance finding `severity=info`, never blocks.

---

## Cross-Cutting Definitions of Done

For every PR in this plan:
1. `make lint` clean.
2. `make typecheck` clean (mypy 0 errors).
3. Targeted tests added; full suite green.
4. If touches DB → migration + rollback + Postgres test.
5. If touches API shape → `openapi.json` regenerated.
6. If touches SDK contract → SDK tests + version bump.
7. If touches frontend → component test + manual screenshot in PR.
8. CHANGELOG entry under correct semver bucket.

---

## Suggested PR Ordering (smallest, mergeable units)

| Order | PR Title | Wave |
|-------|----------|------|
| 1 | `fix(auth): constant-time API key comparison` | W1.3 |
| 2 | `feat(config): broaden production safety validation` | W1.4 |
| 3 | `feat(api): request body size limit middleware` | W1.5 |
| 4 | `feat(cedar): require CLI in production + readiness` | W1.1 |
| 5 | `feat(policy): shape validator at create/import` | W1.2 |
| 6 | `fix(clerk): just-in-time org provisioning` | W2.5 |
| 7 | `feat(sdk-py): PendingApprovalResult + framework plugins` | W2.1 |
| 8 | `feat(approvals): honor sla_hours + workflow timing` | W2.2 |
| 9 | `feat(approvals): real reminder notifications` | W2.3 |
| 10 | `feat(approvals): escalation extends expiry` | W2.4 |
| 11 | `feat(obs): prometheus /metrics endpoint` | W3.1 |
| 12 | `feat(temporal): circuit breaker` | W3.2 |
| 13 | `feat(rate-limit): hard-mode for production` | W3.3 |
| 14 | `feat(compliance): per-plugin execution timeout` | W3.4 |
| 15 | `feat(audit): durable export jobs (migration 032)` | W3.5 |
| 16 | `feat(webhooks): delivery id + replay docs` | W3.6 |
| 17 | `refactor(cedar): proper package import` | W3.7 |
| 18 | `feat(infra): transactional migration runner + missing rollbacks` | W4.1 |
| 19 | `feat(audit): cursor pagination + dashboard virtual scroll` | W4.2 |
| 20 | `feat(db): pool tuning + pgbouncer docs` | W4.3 |
| 21 | `feat(cedar): pool autosize + prewarm + metrics` | W4.4 |
| 22 | `ci: openapi drift detection` | W4.5 |
| 23 | `ci: gate Postgres tests` | W5.1 |
| 24 | `ci: wire e2e Playwright suite` | W5.2 |
| 25 | `ci: remove dashboard continue-on-error` | W5.3 |
| 26 | `feat(copilot): retrieval over org policies/audit` | W5.4 |
| 27 | `feat(anomaly): embedding-based advisory signal` | W5.5 |

---

## Out of Scope (intentionally)

- Multi-region active-active.
- Read replica routing.
- pgvector → dedicated vector DB migration.
- Karma → Vitest migration (track separately).
- Cedar custom schema authoring UI (would be Wave 6).

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| W1.1 breaks existing self-hosted users without Cedar CLI | Honor `AGR_ALLOW_CEDAR_FALLBACK_PROD=1` for one minor version; emit deprecation banner. |
| W2.1 changes plugin return type (breaking) | Major version bump for `agr-langchain` and `agr-sdk-python`; provide compat shim for one minor. |
| W3.1 metrics endpoint leaks tenant counts | No per-org labels in exposition (only mode/decision dimensions). |
| W4.1 schema_migrations hashing breaks existing dirs | One-time backfill script computes hashes for already-applied files. |
| W5.1 Postgres CI doubles run time | Cache image; reuse for integration + postgres jobs. |

---

## Tracking

Create a GitHub milestone **"AGR Hardening — 2026-05"** with one issue per PR above. Each issue links here.
