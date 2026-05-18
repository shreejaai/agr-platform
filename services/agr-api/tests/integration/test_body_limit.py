"""Integration tests for BodySizeLimitMiddleware (W1.5)."""

import pytest
from app.config import settings
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_oversized_request_rejected_with_413(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tighten the cap so the test payload is cheap to construct.
    monkeypatch.setattr(settings, "max_request_body_bytes", 1024)

    big_blob = "x" * 4096  # 4 KB, well past the 1 KB cap
    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging",
            "context": {"blob": big_blob},
        },
        headers=auth_headers,
    )

    assert response.status_code == 413
    body = response.json()
    assert body["error"] == "payload_too_large"
    assert body["limit_bytes"] == 1024


@pytest.mark.asyncio
async def test_under_limit_request_passes_through(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Generous cap so a normal evaluate call goes through unchanged.
    monkeypatch.setattr(settings, "max_request_body_bytes", 256 * 1024)

    response = await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "coder-001",
            "action": "deploy",
            "resource": "staging",
            "context": {"environment": "staging"},
        },
        headers=auth_headers,
    )

    # Anything other than 413 means the middleware let the request through;
    # the actual evaluate response shape is exercised by other tests.
    assert response.status_code != 413
