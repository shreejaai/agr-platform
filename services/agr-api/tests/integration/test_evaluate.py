"""Integration tests for POST /v1/evaluate — the core endpoint."""

from datetime import UTC, datetime, timedelta

import pytest
from app.config import settings as app_settings
from app.models import AuditEvent, Organization, Policy
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_evaluate_allow_staging_deploy(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /v1/evaluate returns ALLOW for staging deploy."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "ALLOW"
    assert data["eval_id"]
    assert data["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_evaluate_deny_production_db_drop(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /v1/evaluate returns DENY for production db.drop."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "db.drop",
            "resource": "production-db",
            "context": {"environment": "production"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "DENY"


@pytest.mark.asyncio
async def test_evaluate_approval_required_production_deploy(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """POST /v1/evaluate returns APPROVAL_REQUIRED for production deploy."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "production-server",
            "context": {"environment": "production"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "APPROVAL_REQUIRED"
    assert data["approval_id"] is not None
    assert "requires human approval" in data["reason"]


@pytest.mark.asyncio
async def test_evaluate_returns_401_without_auth(client: AsyncClient) -> None:
    """POST /v1/evaluate returns 401 without Authorization header."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "server",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_evaluate_returns_401_with_invalid_key(client: AsyncClient) -> None:
    """POST /v1/evaluate returns 401 with invalid API key."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "server",
        },
        headers={"Authorization": "Bearer agr_sk_invalidkey"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_evaluate_returns_429_when_limit_exceeded_in_hard_limit_mode(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    """POST /v1/evaluate returns 429 when soft enforcement is disabled."""
    await db_session.execute(
        update(Organization)
        .where(Organization.id == test_org.id)
        .values(
            eval_count=10000,
            eval_limit=10000,
            eval_soft_limit_enabled=False,
            eval_week_start=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db_session.commit()

    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 429
    data = response.json()
    # HTTPException wraps detail in {"detail": {...}}
    detail = data["detail"]
    assert detail["error"] == "eval_limit_exceeded"
    assert "upgrade_url" in detail


@pytest.mark.asyncio
async def test_evaluate_soft_limit_warns_without_blocking(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        update(Organization)
        .where(Organization.id == test_org.id)
        .values(
            eval_count=2,
            eval_limit=2,
            eval_soft_limit_enabled=True,
            eval_warning_threshold_pct=50,
            eval_week_start=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db_session.commit()

    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "soft-limit-agent",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["X-AGR-Usage-State"] == "exceeded"
    assert response.headers["X-AGR-Usage-Warning"]


@pytest.mark.asyncio
async def test_evaluate_writes_audit_event(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_org: Organization,
) -> None:
    """POST /v1/evaluate creates a valid audit event."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200

    result = await db_session.execute(select(AuditEvent).where(AuditEvent.org_id == test_org.id))
    events = result.scalars().all()
    assert len(events) >= 1
    event = events[0]
    assert event.event_type == "TOOL_ALLOW"
    assert event.agent_id == "coder-001"
    assert event.entry_hash
    assert len(event.entry_hash) == 64


@pytest.mark.asyncio
async def test_evaluate_hash_chain_valid(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_org: Organization,
) -> None:
    """Two consecutive evaluations produce a valid hash chain."""
    await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "a1",
            "action": "deploy",
            "resource": "s1",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "a2",
            "action": "deploy",
            "resource": "s2",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )

    result = await db_session.execute(
        select(AuditEvent).where(AuditEvent.org_id == test_org.id).order_by(AuditEvent.sequence_num)
    )
    events = result.scalars().all()
    assert len(events) >= 2

    first = events[0]
    second = events[1]
    assert first.prev_hash is None
    assert second.prev_hash == first.entry_hash


@pytest.mark.asyncio
async def test_evaluate_deny_default_no_policies(
    client: AsyncClient,
    db_session: AsyncSession,
    test_org: Organization,
    auth_headers: dict[str, str],
) -> None:
    """Evaluate with no matching policies returns DENY (safe default)."""
    await db_session.execute(select(Policy).where(Policy.org_id == test_org.id))
    # Delete all policies for this org
    from sqlalchemy import delete

    await db_session.execute(delete(Policy).where(Policy.org_id == test_org.id))
    await db_session.commit()

    response = await client.post(
        "/v1/evaluate",
        json={"agent_id": "a1", "action": "unknown", "resource": "r1"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "DENY"


@pytest.mark.asyncio
async def test_evaluate_trace_allow(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """decision_trace is present and correct on an ALLOW response."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "ALLOW"
    trace = data["decision_trace"]
    assert trace is not None
    assert trace["policy_source"] == "python_fallback"
    assert trace["cedar_decision"] == "ALLOW"
    assert trace["risk_override"] is False


@pytest.mark.asyncio
async def test_evaluate_returns_enriched_compliance_findings(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "bot",
            "action": "*",
            "resource": "*",
            "context": {},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    findings = response.json()["compliance_findings"]
    assert findings is not None

    cc61 = next(finding for finding in findings if finding["rule_id"] == "CC6.1")
    assert cc61["passed"] is False
    assert cc61["severity_level"] == "medium"
    assert 0 <= cc61["compliance_score"] < 100
    assert cc61["remediation_steps"][0] == (
        "Replace wildcard or empty actions with the exact operation name being requested."
    )


@pytest.mark.asyncio
async def test_evaluate_trace_deny_no_policies(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_org: Organization,
) -> None:
    """decision_trace shows policy_source=no_policies when no policies exist."""
    from sqlalchemy import delete

    await db_session.execute(delete(Policy).where(Policy.org_id == test_org.id))
    await db_session.commit()

    response = await client.post(
        "/v1/evaluate",
        json={"agent_id": "coder-001", "action": "read", "resource": "docs"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    trace = data["decision_trace"]
    assert trace["cedar_decision"] == "DENY"
    assert trace["policy_source"] == "no_policies"
    assert trace["risk_override"] is False


@pytest.mark.asyncio
async def test_evaluate_trace_approval_required(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """decision_trace reflects APPROVAL_REQUIRED without risk override."""
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "production-server",
            "context": {"environment": "production"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "APPROVAL_REQUIRED"
    trace = data["decision_trace"]
    assert trace["cedar_decision"] == "APPROVAL_REQUIRED"
    assert trace["risk_override"] is False


@pytest.mark.asyncio
async def test_evaluate_trace_risk_override(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """decision_trace marks risk_override=True when risk scoring changes the decision."""
    import app.routes.evaluate as evaluate_module
    from app.services.risk_service import RiskResult

    monkeypatch.setattr(
        evaluate_module,
        "compute_risk_score",
        lambda **kwargs: RiskResult(score=95, level="critical", factors={}),
    )
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    trace = data["decision_trace"]
    assert trace["cedar_decision"] == "ALLOW"
    assert trace["risk_override"] is True
    assert trace["risk_score"] == 95
    assert trace["risk_level"] == "critical"
    assert data["decision"] != "ALLOW"


@pytest.mark.asyncio
async def test_evaluate_returns_python_fallback_engine_mode_when_cedar_missing(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("policy_engine._find_cedar_cli", lambda: None)

    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["X-AGR-Engine"] == "python_fallback"
    assert response.json()["engine_mode"] == "python_fallback"


@pytest.mark.asyncio
async def test_evaluate_sets_engine_header(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["X-AGR-Engine"] in {"cedar_cli", "python_fallback", "cache"}


@pytest.mark.asyncio
async def test_evaluate_require_cli_returns_503_when_fallback_used(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("policy_engine._find_cedar_cli", lambda: None)
    original = app_settings.cedar_require_cli
    app_settings.cedar_require_cli = True
    try:
        response = await client.post(
            "/v1/evaluate",
            json={
                "agent_id": "coder-001",
                "action": "deploy",
                "resource": "staging-server",
                "context": {"environment": "staging"},
            },
            headers=auth_headers,
        )
    finally:
        app_settings.cedar_require_cli = original

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Cedar CLI unavailable. Set CEDAR_REQUIRE_CLI=false to allow fallback."
    )


@pytest.mark.asyncio
async def test_evaluate_replays_same_idempotency_key(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.routes.evaluate as evaluate_module

    store: dict[tuple[str, str], dict[str, object]] = {}

    async def fake_get(org_id, key):
        return store.get((str(org_id), key))

    async def fake_set(org_id, key, response_dict, ttl=86400):
        store[(str(org_id), key)] = response_dict

    monkeypatch.setattr(evaluate_module, "get_idempotent_response", fake_get)
    monkeypatch.setattr(evaluate_module, "set_idempotent_response", fake_set)

    headers = {**auth_headers, "Idempotency-Key": "idem-123"}
    first = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=headers,
    )
    second = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["eval_id"] == second.json()["eval_id"]
    assert second.json()["idempotency_replayed"] is True
    assert second.headers["X-Idempotency-Replayed"] == "true"


@pytest.mark.asyncio
async def test_evaluate_different_idempotency_keys_return_fresh_responses(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.routes.evaluate as evaluate_module

    store: dict[tuple[str, str], dict[str, object]] = {}

    async def fake_get(org_id, key):
        return store.get((str(org_id), key))

    async def fake_set(org_id, key, response_dict, ttl=86400):
        store[(str(org_id), key)] = response_dict

    monkeypatch.setattr(evaluate_module, "get_idempotent_response", fake_get)
    monkeypatch.setattr(evaluate_module, "set_idempotent_response", fake_set)

    first = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers={**auth_headers, "Idempotency-Key": "idem-a"},
    )
    second = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging-server",
            "context": {"environment": "staging"},
        },
        headers={**auth_headers, "Idempotency-Key": "idem-b"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["eval_id"] != second.json()["eval_id"]
    assert second.json()["idempotency_replayed"] is False
