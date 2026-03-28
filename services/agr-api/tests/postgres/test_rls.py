"""PostgreSQL RLS (Row-Level Security) isolation tests.

Verifies that org A cannot read org B's data at the database level,
independent of application-layer filtering.
"""

from __future__ import annotations

import uuid

import pytest
from app.database import set_session_rls
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _set_rls_org(session: AsyncSession, org_id: str) -> None:
    """Set the RLS context variable for the current session."""
    await session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    await session.execute(text(f"SET LOCAL app.current_org = '{org_id}'"))


@pytest.mark.asyncio
async def test_rls_policies_org_isolation(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
    pg_org_b: dict[str, str],
) -> None:
    """Org A policies are not visible when RLS is set to Org B."""
    policy_id = str(uuid.uuid4())

    # Insert policy for Org A
    await pg_session.execute(
        text("""
            INSERT INTO policies (id, org_id, name, level, cedar_rule)
            VALUES (:id, :org_id, 'Org A Policy', 'org',
                    'permit(principal, action == Action::\"read\", resource);')
        """),
        {"id": policy_id, "org_id": pg_org["id"]},
    )
    await pg_session.flush()

    # Query as Org B — should see nothing due to RLS
    await _set_rls_org(pg_session, pg_org_b["id"])
    result = await pg_session.execute(
        text("SELECT id FROM policies WHERE id = :id"),
        {"id": policy_id},
    )
    rows = result.fetchall()
    assert len(rows) == 0, "RLS failed: Org B can see Org A's policy"


@pytest.mark.asyncio
async def test_rls_policies_own_org_visible(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """Org A policies ARE visible when RLS is set to Org A."""
    policy_id = str(uuid.uuid4())
    await pg_session.execute(
        text("""
            INSERT INTO policies (id, org_id, name, level, cedar_rule)
            VALUES (:id, :org_id, 'RLS Test Policy', 'org',
                    'permit(principal, action == Action::\"read\", resource);')
        """),
        {"id": policy_id, "org_id": pg_org["id"]},
    )
    await pg_session.flush()

    await _set_rls_org(pg_session, pg_org["id"])
    result = await pg_session.execute(
        text("SELECT id FROM policies WHERE id = :id"),
        {"id": policy_id},
    )
    rows = result.fetchall()
    assert len(rows) == 1, "RLS failed: Org A cannot see its own policy"


@pytest.mark.asyncio
async def test_set_session_rls_sets_both_context_keys(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """Application helper sets both modern and legacy org context keys."""
    await set_session_rls(pg_session, uuid.UUID(pg_org["id"]))

    result = await pg_session.execute(
        text("""
            SELECT
                current_setting('app.current_org_id', true),
                current_setting('app.current_org', true)
        """)
    )
    current_org_id, current_org = result.one()

    assert current_org_id == pg_org["id"]
    assert current_org == pg_org["id"]


@pytest.mark.asyncio
async def test_rls_audit_events_org_isolation(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
    pg_org_b: dict[str, str],
) -> None:
    """Audit events for Org A are not visible to Org B via RLS."""
    event_id = str(uuid.uuid4())
    await pg_session.execute(
        text("""
            INSERT INTO audit_events
                (id, org_id, sequence_num, event_type, agent_id, action, resource,
                 decision, entry_hash, recorded_at)
            VALUES (:id, :org_id, 1, 'TOOL_ALLOW', 'agent-1', 'read', 'file',
                    'ALLOW', 'hash123', NOW())
        """),
        {"id": event_id, "org_id": pg_org["id"]},
    )
    await pg_session.flush()

    await _set_rls_org(pg_session, pg_org_b["id"])
    result = await pg_session.execute(
        text("SELECT id FROM audit_events WHERE id = :id"),
        {"id": event_id},
    )
    rows = result.fetchall()
    assert len(rows) == 0, "RLS failed: Org B can see Org A's audit events"


@pytest.mark.asyncio
async def test_rls_approval_requests_isolation(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
    pg_org_b: dict[str, str],
) -> None:
    """Approval requests for Org A are not visible to Org B via RLS."""
    req_id = str(uuid.uuid4())
    await pg_session.execute(
        text("""
            INSERT INTO approval_requests
                (id, org_id, agent_id, action, resource, status)
            VALUES (:id, :org_id, 'agent-1', 'deploy', 'server', 'pending')
        """),
        {"id": req_id, "org_id": pg_org["id"]},
    )
    await pg_session.flush()

    await _set_rls_org(pg_session, pg_org_b["id"])
    result = await pg_session.execute(
        text("SELECT id FROM approval_requests WHERE id = :id"),
        {"id": req_id},
    )
    rows = result.fetchall()
    assert len(rows) == 0, "RLS failed: Org B can see Org A's approval requests"
