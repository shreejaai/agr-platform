"""PostgreSQL JSONB operations tests.

Verifies JSONB columns work correctly for:
- agent metadata storage and queries
- approval context storage and queries
- audit event payload queries
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_agent_metadata_jsonb_storage(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """Agent metadata stored as JSONB is queryable."""
    agent_id = str(uuid.uuid4())
    metadata = '{"framework": "langchain", "version": "0.2", "tags": ["prod", "v2"]}'

    await pg_session.execute(
        text("""
            INSERT INTO agents (id, org_id, agent_id, metadata)
            VALUES (:id, :org_id, :agent_id, :metadata::jsonb)
        """),
        {"id": agent_id, "org_id": pg_org["id"], "agent_id": "test-agent-001", "metadata": metadata},
    )
    await pg_session.flush()

    # Query by JSONB field
    result = await pg_session.execute(
        text("""
            SELECT metadata->>'framework' AS framework
            FROM agents
            WHERE id = :id
        """),
        {"id": agent_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "langchain"


@pytest.mark.asyncio
async def test_approval_context_jsonb_query(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """Approval request context JSONB field is queryable by key."""
    req_id = str(uuid.uuid4())
    context = '{"environment": "production", "version": "2.1.0", "risk_level": "high"}'

    await pg_session.execute(
        text("""
            INSERT INTO approval_requests
                (id, org_id, agent_id, action, resource, context, status)
            VALUES (:id, :org_id, 'agent-1', 'deploy', 'server', :context::jsonb, 'pending')
        """),
        {"id": req_id, "org_id": pg_org["id"], "context": context},
    )
    await pg_session.flush()

    # Query by JSONB key
    result = await pg_session.execute(
        text("""
            SELECT context->>'environment', context->>'risk_level'
            FROM approval_requests
            WHERE id = :id
        """),
        {"id": req_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "production"
    assert row[1] == "high"


@pytest.mark.asyncio
async def test_audit_payload_jsonb_containment(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """Audit event payload JSONB supports @> containment queries."""
    event_id = str(uuid.uuid4())
    payload = '{"eval_id": "abc123", "risk_score": 45, "risk_level": "medium", "cached": false}'

    await pg_session.execute(
        text("""
            INSERT INTO audit_events
                (id, org_id, sequence_num, event_type, agent_id, action, resource,
                 decision, payload, entry_hash, recorded_at)
            VALUES (:id, :org_id, 10, 'TOOL_ALLOW', 'agent-1', 'read', 'file',
                    'ALLOW', :payload::jsonb, 'hash-jsonb-test', NOW())
        """),
        {"id": event_id, "org_id": pg_org["id"], "payload": payload},
    )
    await pg_session.flush()

    # JSONB containment query — find events with risk_level = medium
    result = await pg_session.execute(
        text("""
            SELECT id FROM audit_events
            WHERE payload @> '{"risk_level": "medium"}'::jsonb
              AND id = :id
        """),
        {"id": event_id},
    )
    row = result.fetchone()
    assert row is not None, "JSONB @> containment query failed"


@pytest.mark.asyncio
async def test_jsonb_null_context_allowed(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """Approval requests with NULL context are valid (context is optional)."""
    req_id = str(uuid.uuid4())
    await pg_session.execute(
        text("""
            INSERT INTO approval_requests
                (id, org_id, agent_id, action, resource, status)
            VALUES (:id, :org_id, 'agent-1', 'read', 'file', 'pending')
        """),
        {"id": req_id, "org_id": pg_org["id"]},
    )
    await pg_session.flush()

    result = await pg_session.execute(
        text("SELECT context FROM approval_requests WHERE id = :id"),
        {"id": req_id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] is None
