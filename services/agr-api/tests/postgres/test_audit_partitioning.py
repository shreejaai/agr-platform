"""PostgreSQL audit partitioning tests.

Verifies that the audit_events table is partitioned by month,
partitions exist for the current and future months,
and that data is inserted into the correct partition.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_audit_events_is_partitioned(pg_session: AsyncSession) -> None:
    """Verify audit_events is a range-partitioned table."""
    result = await pg_session.execute(
        text("""
            SELECT relkind FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = 'audit_events'
              AND n.nspname = current_schema()
        """)
    )
    row = result.fetchone()
    assert row is not None, "audit_events table not found"
    assert row[0] == "p", f"Expected relkind='p' (partitioned), got '{row[0]}'"


@pytest.mark.asyncio
async def test_current_month_partition_exists(pg_session: AsyncSession) -> None:
    """Current month's audit partition must exist after migrations."""
    now = datetime.now(UTC)
    expected_name = f"audit_events_{now.year}_{now.month:02d}"

    result = await pg_session.execute(
        text("""
            SELECT relname FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = :name AND n.nspname = current_schema()
        """),
        {"name": expected_name},
    )
    row = result.fetchone()
    assert row is not None, f"Expected partition '{expected_name}' not found — check migration 006"


@pytest.mark.asyncio
async def test_audit_insert_routes_to_correct_partition(
    pg_session: AsyncSession,
    pg_org: dict[str, str],
) -> None:
    """Insert into audit_events and verify it lands in the current month partition."""
    now = datetime.now(UTC)
    expected_partition = f"audit_events_{now.year}_{now.month:02d}"
    event_id = str(uuid.uuid4())

    await pg_session.execute(
        text("""
            INSERT INTO audit_events
                (id, org_id, sequence_num, event_type, agent_id, action, resource,
                 decision, entry_hash, recorded_at)
            VALUES (:id, :org_id, 99, 'TOOL_ALLOW', 'agent-partition-test', 'read',
                    'resource', 'ALLOW', 'hash-partition-test', :now)
        """),
        {"id": event_id, "org_id": pg_org["id"], "now": now},
    )
    await pg_session.flush()

    # Verify the row exists in the expected partition directly
    result = await pg_session.execute(
        text(f"SELECT id FROM {expected_partition} WHERE id = :id"),  # noqa: S608
        {"id": event_id},
    )
    row = result.fetchone()
    assert row is not None, f"Row not found in partition {expected_partition}"


@pytest.mark.asyncio
async def test_future_partitions_exist(pg_session: AsyncSession) -> None:
    """Migration 006 pre-creates 12 months ahead — verify at least 3 future partitions exist."""
    now = datetime.now(UTC)
    missing = []

    for months_ahead in (1, 2, 3):
        # Compute year/month for future months
        month = now.month + months_ahead
        year = now.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        name = f"audit_events_{year}_{month:02d}"
        result = await pg_session.execute(
            text("""
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = :name AND n.nspname = current_schema()
            """),
            {"name": name},
        )
        if not result.fetchone():
            missing.append(name)

    assert not missing, f"Expected future partitions not found: {missing}"


@pytest.mark.asyncio
async def test_create_audit_partition_function_exists(pg_session: AsyncSession) -> None:
    """The create_audit_partition() helper function must exist."""
    result = await pg_session.execute(
        text("""
            SELECT proname FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE p.proname = 'create_audit_partition'
              AND n.nspname = current_schema()
        """)
    )
    row = result.fetchone()
    assert row is not None, "create_audit_partition() function not found after migrations"
