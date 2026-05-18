"""Unit tests for the LangGraph plugin."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "agr-sdk-python"))
from agr.client import AGRError, EvaluationResult, PendingApprovalResult
from agr.plugins.langgraph import agr_governed


def _make_mock_client(decision: str, approval_id: str | None = None) -> MagicMock:
    client = MagicMock()
    client.evaluate.return_value = EvaluationResult(
        decision=decision,
        reason=f"Test {decision}",
        policy_id="p1",
        approval_id=approval_id,
        latency_ms=0.1,
        eval_id="e1",
    )
    return client


def test_allow_executes_tool() -> None:
    client = _make_mock_client("ALLOW")

    @agr_governed(client, agent_id="agent-1")
    def my_tool(x: int) -> int:
        return x * 2

    result = my_tool(5)
    assert result == 10
    client.evaluate.assert_called_once()


def test_deny_raises_error() -> None:
    client = _make_mock_client("DENY")

    @agr_governed(client, agent_id="agent-1")
    def my_tool(x: int) -> int:
        return x * 2

    with pytest.raises(AGRError, match="denied"):
        my_tool(5)


def test_approval_required_blocks_then_executes() -> None:
    client = _make_mock_client("APPROVAL_REQUIRED", approval_id="a1")
    client.wait_for_approval.return_value = True

    @agr_governed(client, agent_id="agent-1")
    def my_tool(x: int) -> int:
        return x * 2

    result = my_tool(5)
    assert result == 10
    client.wait_for_approval.assert_called_once_with("a1", poll_interval=2.0, timeout=3600.0)


def test_approval_rejected_raises_error() -> None:
    client = _make_mock_client("APPROVAL_REQUIRED", approval_id="a1")
    client.wait_for_approval.return_value = False

    @agr_governed(client, agent_id="agent-1")
    def my_tool(x: int) -> int:
        return x * 2

    with pytest.raises(AGRError, match="rejected"):
        my_tool(5)


def test_non_blocking_mode_returns_pending_approval_result() -> None:
    """W2.1: when mode='non_blocking', APPROVAL_REQUIRED returns a
    PendingApprovalResult instead of blocking on wait_for_approval, and
    the wrapped tool body is NOT invoked."""
    client = _make_mock_client("APPROVAL_REQUIRED", approval_id="a-pending")
    invoked: list[int] = []

    @agr_governed(client, agent_id="agent-1", mode="non_blocking")
    def my_tool(x: int) -> int:
        invoked.append(x)
        return x * 2

    result = my_tool(7)
    assert isinstance(result, PendingApprovalResult)
    assert result.approval_id == "a-pending"
    assert result.action == "my_tool"
    assert result.is_pending is True
    assert invoked == []  # body did NOT run
    client.wait_for_approval.assert_not_called()
