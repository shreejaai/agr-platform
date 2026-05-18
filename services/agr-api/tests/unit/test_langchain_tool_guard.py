"""W2.1 — AGRToolGuard (LangChain) non-blocking + blocking semantics.

The legacy guard raised ToolException on APPROVAL_REQUIRED, which forced
LangChain agents into a dead-end whenever a sensitive tool needed
human sign-off. The new guard:

- DENY        → still raises ToolException.
- ALLOW       → wrapped tool runs as before.
- APPROVAL_REQUIRED + mode='non_blocking' (default) →
    returns PendingApprovalResult to the agent; wrapped tool is NOT run.
- APPROVAL_REQUIRED + mode='block_until_resolved' →
    polls AGR until decided; on approve runs the tool, on reject raises.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "agr-sdk-python"))
sys.path.insert(0, str(ROOT / "packages" / "agr-langchain"))

# Import via fully-qualified path: packages/agr-langchain/tool_guard.py
import importlib.util  # noqa: E402

from agr.client import EvaluationResult, PendingApprovalResult  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "agr_langchain_tool_guard",
    ROOT / "packages" / "agr-langchain" / "tool_guard.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
AGRToolGuard = _mod.AGRToolGuard
ToolException = _mod.ToolException


def _eval(decision: str, approval_id: str | None = None) -> EvaluationResult:
    return EvaluationResult(
        decision=decision,
        reason=f"test-{decision}",
        policy_id="p1",
        approval_id=approval_id,
        latency_ms=0.1,
        eval_id="e1",
    )


def _make_inner_tool() -> MagicMock:
    tool = MagicMock()
    tool.name = "transfer_funds"
    tool.description = "move money"
    tool._run.return_value = "ran"
    return tool


def test_allow_runs_wrapped_tool() -> None:
    client = MagicMock()
    client.evaluate.return_value = _eval("ALLOW")
    inner = _make_inner_tool()
    guard = AGRToolGuard(agr_client=client, wrapped_tool=inner, agent_id="agent-1")

    assert guard._run("acct-1") == "ran"
    inner._run.assert_called_once()


def test_deny_raises_tool_exception() -> None:
    client = MagicMock()
    client.evaluate.return_value = _eval("DENY")
    inner = _make_inner_tool()
    guard = AGRToolGuard(agr_client=client, wrapped_tool=inner, agent_id="agent-1")

    with pytest.raises(ToolException, match="blocked"):
        guard._run("acct-1")
    inner._run.assert_not_called()


def test_non_blocking_returns_pending_approval_result() -> None:
    client = MagicMock()
    client.evaluate.return_value = _eval("APPROVAL_REQUIRED", approval_id="ap-77")
    inner = _make_inner_tool()
    guard = AGRToolGuard(
        agr_client=client, wrapped_tool=inner, agent_id="agent-1", mode="non_blocking"
    )

    out = guard._run("acct-1")
    assert isinstance(out, PendingApprovalResult)
    assert out.approval_id == "ap-77"
    assert out.action == "transfer_funds"
    inner._run.assert_not_called()
    client.wait_for_approval.assert_not_called()


def test_block_until_resolved_runs_tool_on_approve() -> None:
    client = MagicMock()
    client.evaluate.return_value = _eval("APPROVAL_REQUIRED", approval_id="ap-99")
    client.wait_for_approval.return_value = True
    inner = _make_inner_tool()
    guard = AGRToolGuard(
        agr_client=client,
        wrapped_tool=inner,
        agent_id="agent-1",
        mode="block_until_resolved",
    )

    assert guard._run("acct-1") == "ran"
    client.wait_for_approval.assert_called_once()
    inner._run.assert_called_once()


def test_block_until_resolved_raises_on_reject() -> None:
    client = MagicMock()
    client.evaluate.return_value = _eval("APPROVAL_REQUIRED", approval_id="ap-99")
    client.wait_for_approval.return_value = False
    inner = _make_inner_tool()
    guard = AGRToolGuard(
        agr_client=client,
        wrapped_tool=inner,
        agent_id="agent-1",
        mode="block_until_resolved",
    )

    with pytest.raises(ToolException, match="rejected"):
        guard._run("acct-1")
    inner._run.assert_not_called()
