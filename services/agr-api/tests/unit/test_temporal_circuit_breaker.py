"""W3.2 — Temporal circuit breaker unit tests."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

import pytest
from app.services import temporal_service


@pytest.fixture(autouse=True)
def _reset_breaker():
    temporal_service._reset_circuit_for_tests()
    yield
    temporal_service._reset_circuit_for_tests()


@pytest.mark.asyncio
async def test_breaker_opens_after_threshold_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """5 consecutive failures within the window must trip the breaker to open."""

    async def _no_client() -> Any:
        return None

    monkeypatch.setattr(temporal_service, "_get_client", _no_client)

    # Drive failures. start_approval_workflow returns fallback when client is None
    # AND records a failure on the breaker.
    for _ in range(temporal_service._CB_FAILURE_THRESHOLD):
        await temporal_service.start_approval_workflow(uuid4())

    assert temporal_service.get_circuit_state() == "open"

    # Next call must be short-circuited and tagged db_only_circuit_open.
    result = await temporal_service.start_approval_workflow(uuid4())
    assert result.fallback_mode == "db_only_circuit_open"
    assert result.error == "temporal_circuit_open"


@pytest.mark.asyncio
async def test_breaker_half_opens_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """After the open duration, the next call should enter half_open."""

    async def _no_client() -> Any:
        return None

    monkeypatch.setattr(temporal_service, "_get_client", _no_client)

    # Trip the breaker.
    for _ in range(temporal_service._CB_FAILURE_THRESHOLD):
        await temporal_service.start_approval_workflow(uuid4())
    assert temporal_service.get_circuit_state() == "open"

    # Fast-forward by mutating opened_at past the open duration.
    temporal_service._circuit.opened_at = (
        time.monotonic() - temporal_service._CB_OPEN_DURATION_SEC - 0.1
    )

    # First probe call should be allowed (half_open) and fail again → re-open.
    result = await temporal_service.start_approval_workflow(uuid4())
    assert result.fallback_mode == "db_only_circuit_open" or result.error == "temporal_unavailable"
    # After half_open failure breaker must be back open.
    assert temporal_service.get_circuit_state() == "open"


@pytest.mark.asyncio
async def test_breaker_resets_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful call in half_open must close the breaker."""
    # Manually put the breaker in half_open with no in-flight probe.
    temporal_service._circuit.state = "half_open"
    temporal_service._circuit.half_open_in_flight = False

    await temporal_service._circuit.record_success()
    assert temporal_service.get_circuit_state() == "closed"


@pytest.mark.asyncio
async def test_failures_outside_window_do_not_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Old failures past the rolling window must not count toward the threshold."""
    cb = temporal_service._circuit
    # Seed failures with stale timestamps.
    old = time.monotonic() - temporal_service._CB_FAILURE_WINDOW_SEC - 5
    cb.failures = [old] * (temporal_service._CB_FAILURE_THRESHOLD - 1)

    await cb.record_failure()  # one fresh failure
    assert cb.snapshot() == "closed"


def test_get_circuit_state_initial_closed() -> None:
    assert temporal_service.get_circuit_state() == "closed"


# Suppress unused-import warning from asyncio (kept for clarity in tests).
_ = asyncio
