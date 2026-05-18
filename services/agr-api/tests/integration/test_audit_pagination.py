"""W4.2 — cursor pagination on /v1/audit."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from app.models import Organization
    from httpx import AsyncClient


async def _seed_events(client: AsyncClient, auth_headers: dict[str, str], count: int) -> None:
    for i in range(count):
        resp = await client.post(
            "/v1/evaluate",
            json={
                "agent_id": "cursor-bot",
                "action": "deploy",
                "resource": f"server-{i}",
                "context": {"environment": "staging"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_audit_cursor_pagination_yields_complete_ordered_set(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
) -> None:
    await _seed_events(client, auth_headers, 5)

    seen: list[int] = []
    cursor: str | None = None
    pages = 0
    while True:
        params = {"limit": "2"}
        if cursor is not None:
            params["after"] = cursor
        resp = await client.get("/v1/audit", params=params, headers=auth_headers)
        assert resp.status_code == 200
        events = resp.json()
        if not events:
            break
        pages += 1
        seen.extend(e["sequence_num"] for e in events)
        cursor = resp.headers.get("X-AGR-Next-Cursor")
        if cursor is None:
            break
        assert pages < 10, "runaway pagination"

    # Strictly decreasing — page order is newest-first, and each page continues.
    assert len(seen) >= 5
    assert seen == sorted(seen, reverse=True)
    assert len(set(seen)) == len(seen)


@pytest.mark.asyncio
async def test_audit_cursor_omits_header_on_last_page(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_org: Organization,
) -> None:
    await _seed_events(client, auth_headers, 2)
    resp = await client.get("/v1/audit", params={"limit": 50}, headers=auth_headers)
    assert resp.status_code == 200
    assert "X-AGR-Next-Cursor" not in resp.headers
    assert len(resp.json()) >= 2
