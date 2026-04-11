"""Tests for org-level no_policy_action fallback behaviour.

Covers:
  1. no policy + deny  → DENY
  2. no policy + allow → ALLOW for a low-risk action
  3. no policy + approval_required → APPROVAL_REQUIRED
  4. no policy + allow + high-risk action → risk scoring escalates ALLOW → APPROVAL_REQUIRED
  5. no policy + allow + compliance enforce block → DENY from compliance layer
  6. decision_trace includes no_policy_action field
  7. audit event payload includes no_policy_fallback=True, no_policy_action markers
  8. matched policy ignores no_policy_action (regression guard)
"""

import pytest
from app.models import Organization, Policy
from app.services.compliance_service import (
    ComplianceContext,
    ComplianceFinding,
    CompliancePlugin,
    get_registry,
)
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession


class _AlwaysBlockPlugin(CompliancePlugin):
    """Test-only plugin — always produces a high-severity blocking finding.

    Used to verify the compliance enforcement path in no_policy_action tests.
    Does NOT depend on risk score, enforcement_mode DB rows, or severity_level
    enrichment thresholds.
    """

    enforcement_mode = "enforce"
    blocks_on_finding = True

    @property
    def name(self) -> str:
        return "test_always_block"

    async def check(self, ctx: ComplianceContext) -> list[ComplianceFinding]:
        return [
            ComplianceFinding(
                plugin=self.name,
                plugin_id="test_always_block",
                standard="TEST",
                rule_id="TEST-BLOCK",
                severity="critical",
                severity_level="critical",
                message="Test-only block — always fires when registered.",
                passed=False,
            )
        ]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Low-risk body: read_file is in the read-like actions bucket (score ~5)
# with empty context. Expected raw score ≪ allow_max=30. Won't be escalated.
_LOW_RISK_BODY = {
    "agent_id": "test-agent",
    "action": "read_file",
    "resource": "config.yaml",
    "context": {},
}

# High-risk body: db.drop on production-db with environment=production.
# action_severity score = 90 (DROP hits _HIGH_SEVERITY_ACTIONS).
# Weighted contribution from action alone: 90 * 0.30 = 27.
# Context (environment key + "production" value): 30 * 0.20 = 6.
# Total ≥ 33 > allow_max (30) → at minimum APPROVAL_REQUIRED.
_HIGH_RISK_BODY = {
    "agent_id": "test-agent",
    "action": "db.drop",
    "resource": "production-db",
    "context": {"environment": "production"},
}


async def _set_no_policy_action(
    db_session: AsyncSession,
    org: Organization,
    mode: str,
) -> None:
    """Update org.no_policy_action and commit so auth middleware sees the change."""
    await db_session.execute(
        update(Organization)
        .where(Organization.id == org.id)
        .values(no_policy_action=mode)
    )
    await db_session.commit()


async def _deactivate_all_policies(
    db_session: AsyncSession, org: Organization
) -> None:
    """Archive all org policies so load_active_policies returns nothing.

    Must update BOTH active AND state because load_active_policies filters
    by state='active', not the boolean active column.
    """
    await db_session.execute(
        update(Policy)
        .where(Policy.org_id == org.id)
        .values(active=False, state="archived")
    )
    await db_session.commit()




# ---------------------------------------------------------------------------
# Test 1: no policy + deny → DENY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_deny(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    """No matching policy + deny mode → DENY (same as pre-030 safe default)."""
    await _deactivate_all_policies(db_session, test_org)
    await _set_no_policy_action(db_session, test_org, "deny")

    resp = await client.post("/v1/evaluate", json=_LOW_RISK_BODY, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "DENY"


# ---------------------------------------------------------------------------
# Test 2: no policy + allow → ALLOW for low-risk action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_allow_low_risk(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    """No matching policy + allow mode → ALLOW when risk score is below allow_max=30."""
    await _deactivate_all_policies(db_session, test_org)
    await _set_no_policy_action(db_session, test_org, "allow")

    resp = await client.post("/v1/evaluate", json=_LOW_RISK_BODY, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "ALLOW"


# ---------------------------------------------------------------------------
# Test 3: no policy + approval_required → APPROVAL_REQUIRED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_approval_required(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    """No matching policy + approval_required mode → APPROVAL_REQUIRED + approval_id."""
    await _deactivate_all_policies(db_session, test_org)
    await _set_no_policy_action(db_session, test_org, "approval_required")

    resp = await client.post("/v1/evaluate", json=_LOW_RISK_BODY, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "APPROVAL_REQUIRED"
    assert data.get("approval_id") is not None


# ---------------------------------------------------------------------------
# Test 4: no policy + allow + high-risk action → risk escalates to APPROVAL_REQUIRED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_allow_high_risk_escalated(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    """No matching policy + allow mode + high-risk action → risk escalates decision.

    db.drop on production-db yields action_severity ≈ 27 + context ≈ 6 = score > 30.
    Default thresholds: allow_max=30, approval_max=70.
    Score 30 < x < 70 → APPROVAL_REQUIRED.
    """
    await _deactivate_all_policies(db_session, test_org)
    await _set_no_policy_action(db_session, test_org, "allow")

    resp = await client.post("/v1/evaluate", json=_HIGH_RISK_BODY, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Risk scoring must have escalated the ALLOW to something more restrictive
    assert data["decision"] in ("APPROVAL_REQUIRED", "DENY"), (
        f"Expected risk escalation from ALLOW, got {data['decision']!r}"
    )
    # Confirm the decision_trace reflects risk was computed
    trace = data.get("decision_trace") or {}
    assert trace.get("risk_score") is not None, "risk_score missing from decision_trace"
    assert int(trace["risk_score"]) > 30, (  # type: ignore[arg-type]
        f"Expected score > allow_max=30, got {trace['risk_score']}"
    )


# ---------------------------------------------------------------------------
# Test 5: no policy + allow + compliance enforce block → DENY
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_allow_compliance_block(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    """No matching policy + allow + compliance enforcement → compliance blocks → DENY.

    Registers _AlwaysBlockPlugin (enforcement_mode='enforce', severity_level='critical')
    for the duration of this test, then de-registers it to leave registry clean.
    The compliance layer must override the ALLOW from no_policy_action with DENY.
    """
    await _deactivate_all_policies(db_session, test_org)
    await _set_no_policy_action(db_session, test_org, "allow")

    registry = get_registry()
    block_plugin = _AlwaysBlockPlugin()
    registry.register(block_plugin)
    try:
        resp = await client.post(
            "/v1/evaluate",
            json=_LOW_RISK_BODY,
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "DENY", (
            "Compliance enforcement block should override ALLOW → DENY"
        )
        reason = data.get("reason") or ""
        assert "Compliance" in reason or "compliance" in reason, (
            f"Expected compliance block reason, got: {reason!r}"
        )
    finally:
        # Remove test-only plugin so it doesn't bleed into other tests
        registry._plugins = [p for p in registry._plugins if p is not block_plugin]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Test 6: decision_trace contains no_policy_action field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_decision_trace_field(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    """decision_trace.no_policy_action is set when no policy matches."""
    await _deactivate_all_policies(db_session, test_org)
    await _set_no_policy_action(db_session, test_org, "deny")

    resp = await client.post("/v1/evaluate", json=_LOW_RISK_BODY, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    trace = data.get("decision_trace") or {}
    assert trace.get("no_policy_action") == "deny", (
        f"Expected decision_trace.no_policy_action='deny', got: {trace!r}"
    )


# ---------------------------------------------------------------------------
# Test 7: audit payload includes no-policy markers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_audit_markers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    """Audit event payload captures no_policy_fallback=True and no_policy_action."""
    from app.models import AuditEvent
    from sqlalchemy import select

    await _deactivate_all_policies(db_session, test_org)
    await _set_no_policy_action(db_session, test_org, "deny")

    resp = await client.post("/v1/evaluate", json=_LOW_RISK_BODY, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["decision"] == "DENY"

    result = await db_session.execute(
        select(AuditEvent).order_by(AuditEvent.recorded_at.desc()).limit(1)
    )
    event = result.scalar_one_or_none()
    assert event is not None
    payload = event.payload or {}
    assert payload.get("no_policy_fallback") is True, (
        "Audit payload missing no_policy_fallback=True"
    )
    assert payload.get("no_policy_action") == "deny", (
        f"Audit payload no_policy_action mismatch: {payload!r}"
    )


# ---------------------------------------------------------------------------
# Test 8: matched policy ignores no_policy_action (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matched_policy_ignores_no_policy_action(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
    db_session: AsyncSession,
) -> None:
    """When a Cedar policy matches, no_policy_action has no effect on the decision.

    test_policies includes a forbid for db.drop on production.
    Setting no_policy_action='allow' must NOT override that forbid.
    """
    await _set_no_policy_action(db_session, test_org, "allow")

    resp = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "db.drop",
            "resource": "production-db",
            "context": {"environment": "production"},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # Must be DENY from the matched forbid policy — not ALLOW from no_policy_action
    assert data["decision"] == "DENY"
