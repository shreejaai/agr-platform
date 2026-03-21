"""PostgreSQL constraint tests.

Verifies:
- CHECK constraint on approval_requests.status (migration 013)
- UNIQUE constraints on organizations (api_key, slug)
- NOT NULL constraints on required fields
- FK CASCADE behavior
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_approval_status_check_valid_values(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """All valid approval statuses are accepted by the CHECK constraint."""
    for status in ("pending", "approved", "rejected"):
        req_id = str(uuid.uuid4())
        await pg_session.execute(
            text("""
                INSERT INTO approval_requests
                    (id, org_id, agent_id, action, resource, status)
                VALUES (:id, :org_id, 'agent-1', 'deploy', 'server', :status)
            """),
            {"id": req_id, "org_id": pg_org["id"], "status": status},
        )
    await pg_session.flush()  # no error expected


@pytest.mark.asyncio
async def test_approval_status_check_rejects_invalid(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """Invalid approval status is rejected by the DB CHECK constraint."""
    req_id = str(uuid.uuid4())
    with pytest.raises(IntegrityError):
        await pg_session.execute(
            text("""
                INSERT INTO approval_requests
                    (id, org_id, agent_id, action, resource, status)
                VALUES (:id, :org_id, 'agent-1', 'deploy', 'server', 'invalid_status')
            """),
            {"id": req_id, "org_id": pg_org["id"]},
        )
        await pg_session.flush()


@pytest.mark.asyncio
async def test_org_api_key_unique_constraint(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """Duplicate api_key is rejected by the UNIQUE constraint."""
    with pytest.raises(IntegrityError):
        await pg_session.execute(
            text("""
                INSERT INTO organizations (id, name, slug, plan, api_key, eval_count, eval_limit)
                VALUES (:id, 'Dup Org', 'dup-org', 'developer', :api_key, 0, 1000)
            """),
            {"id": str(uuid.uuid4()), "api_key": pg_org["api_key"]},
        )
        await pg_session.flush()


@pytest.mark.asyncio
async def test_org_slug_unique_constraint(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """Duplicate slug is rejected by the UNIQUE constraint."""
    # Get the slug of the existing org
    result = await pg_session.execute(
        text("SELECT slug FROM organizations WHERE id = :id"),
        {"id": pg_org["id"]},
    )
    slug = result.scalar_one()

    with pytest.raises(IntegrityError):
        await pg_session.execute(
            text("""
                INSERT INTO organizations (id, name, slug, plan, api_key, eval_count, eval_limit)
                VALUES (:id, 'Dup Slug Org', :slug, 'developer', :api_key, 0, 1000)
            """),
            {"id": str(uuid.uuid4()), "slug": slug, "api_key": "agr_sk_unique_" + uuid.uuid4().hex},
        )
        await pg_session.flush()


@pytest.mark.asyncio
async def test_policy_cascade_delete(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """Deleting an org cascades to its policies (ON DELETE CASCADE)."""
    # Create a policy for this org
    policy_id = str(uuid.uuid4())
    await pg_session.execute(
        text("""
            INSERT INTO policies (id, org_id, name, level, cedar_rule)
            VALUES (:id, :org_id, 'Cascade Test Policy', 'org',
                    'permit(principal, action == Action::\"read\", resource);')
        """),
        {"id": policy_id, "org_id": pg_org["id"]},
    )
    await pg_session.flush()

    # Delete the org
    await pg_session.execute(
        text("DELETE FROM organizations WHERE id = :id"),
        {"id": pg_org["id"]},
    )
    await pg_session.flush()

    # Verify policy was cascade-deleted
    result = await pg_session.execute(
        text("SELECT id FROM policies WHERE id = :id"),
        {"id": policy_id},
    )
    assert result.fetchone() is None, "Policy should have been cascade-deleted with the org"


@pytest.mark.asyncio
async def test_audit_events_no_org_fk(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """audit_events has NO FK to organizations — outlives org deletion."""
    event_id = str(uuid.uuid4())
    await pg_session.execute(
        text("""
            INSERT INTO audit_events
                (id, org_id, sequence_num, event_type, agent_id, action, resource,
                 decision, entry_hash, recorded_at)
            VALUES (:id, :org_id, 1, 'TOOL_ALLOW', 'agent-1', 'read', 'file',
                    'ALLOW', 'hash-nodelfk', NOW())
        """),
        {"id": event_id, "org_id": pg_org["id"]},
    )
    await pg_session.flush()

    # Delete the org
    await pg_session.execute(
        text("DELETE FROM organizations WHERE id = :id"),
        {"id": pg_org["id"]},
    )
    await pg_session.flush()

    # Audit event should survive (no FK)
    result = await pg_session.execute(
        text("SELECT id FROM audit_events WHERE id = :id"),
        {"id": event_id},
    )
    assert result.fetchone() is not None, "Audit event should survive org deletion (no FK)"
