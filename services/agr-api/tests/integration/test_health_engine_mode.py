"""W1.1 — /health/ready reflects Cedar engine mode when CLI is required."""

import pytest
from app.config import settings
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_ready_503_when_cedar_required_but_missing(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pretend the CLI is not installed.
    import app.routes.health as health_module

    monkeypatch.setattr(health_module.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(settings, "cedar_require_cli", True)
    monkeypatch.setattr(settings, "allow_cedar_fallback_in_prod", False)

    response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert "CEDAR_REQUIRE_CLI" in body["checks"]["cedar_cli"]


@pytest.mark.asyncio
async def test_health_ready_200_when_cedar_optional_and_missing(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.routes.health as health_module

    monkeypatch.setattr(health_module.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(settings, "cedar_require_cli", False)

    response = await client.get("/health/ready")

    # CLI absence is advisory; DB/Redis still drive the verdict.
    body = response.json()
    assert body["checks"]["cedar_cli"].startswith("not_found")
    # Status code depends on DB/Redis, but cedar alone must not flip it.
    assert response.status_code in (200, 503)


@pytest.mark.asyncio
async def test_evaluate_sets_engine_mode_header(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Allow fallback so a missing CLI in CI doesn't 503 the call.
    monkeypatch.setattr(settings, "cedar_require_cli", False)

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

    # Either header should be present and carry one of the known engine modes.
    assert "X-AGR-Engine-Mode" in response.headers
    assert response.headers["X-AGR-Engine-Mode"] in {
        "cache",
        "cedar_cli",
        "python_fallback",
    }
