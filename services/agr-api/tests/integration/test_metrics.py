"""W3.1 — Prometheus /metrics endpoint exposes core counters/histograms."""

import pytest
from app.config import settings
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_format(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.get("/metrics", headers=auth_headers)
    assert response.status_code == 200
    ctype = response.headers.get("content-type", "")
    assert "text/plain" in ctype
    body = response.text
    # Pre-existing core metric must be registered.
    assert "agr_evaluations_total" in body
    # New W3.1 metric series must be registered (HELP/TYPE lines emitted even at 0).
    for name in (
        "agr_evaluate_latency_ms",
        "agr_cedar_engine_mode_total",
        "agr_cedar_pool_inflight",
        "agr_approval_workflow_fallback_total",
        "agr_webhook_delivery_latency_ms",
        "agr_audit_chain_break_total",
        "agr_rate_limit_drop_total",
    ):
        assert name in body, f"missing metric {name}"


@pytest.mark.asyncio
async def test_evaluate_increments_latency_and_engine_mode(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "cedar_require_cli", False)

    await client.post(
        "/v1/evaluate",
        json={
            "agent_id": "metrics-agent",
            "action": "read",
            "resource": "docs",
            "context": {},
        },
        headers=auth_headers,
    )
    response = await client.get("/metrics", headers=auth_headers)
    body = response.text
    # After at least one evaluate call, the histogram count and engine-mode counter
    # must have non-zero samples.
    assert "agr_evaluate_latency_ms_count" in body
    assert "agr_cedar_engine_mode_total" in body
