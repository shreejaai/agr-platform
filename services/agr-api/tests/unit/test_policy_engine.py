"""Unit tests for Cedar policy evaluation — 20 scenarios."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "agr-core"))
from policy_engine import EvaluationResult, evaluate_policies


def _make_policy(policy_id: str, rule: str) -> dict[str, str]:
    return {"id": policy_id, "cedar_rule": rule}


# --- No policies → DENY ---


def test_no_policies_returns_deny() -> None:
    result = evaluate_policies([], "agent-1", "deploy", "server", {})
    assert result.decision == "DENY"
    assert "No active policies" in result.reason


# --- Simple permit ---


def test_permit_staging_deploy() -> None:
    policy = _make_policy(
        "p1",
        """
permit(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "staging" };
    """,
    )
    result = evaluate_policies([policy], "agent-1", "deploy", "server", {"environment": "staging"})
    assert result.decision == "ALLOW"
    assert result.policy_id == "p1"


def test_permit_no_match_returns_deny() -> None:
    policy = _make_policy(
        "p1",
        """
permit(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "staging" };
    """,
    )
    result = evaluate_policies(
        [policy], "agent-1", "deploy", "server", {"environment": "production"}
    )
    assert result.decision == "DENY"


# --- Simple forbid ---


def test_forbid_production_db_drop() -> None:
    policy = _make_policy(
        "p2",
        """
forbid(principal, action in [Action::"db.drop", Action::"db.truncate"], resource)
when { resource has environment && resource.environment == "production" };
    """,
    )
    result = evaluate_policies(
        [policy], "agent-1", "db.drop", "mydb", {"environment": "production"}
    )
    assert result.decision == "DENY"
    assert result.policy_id == "p2"


def test_forbid_db_truncate_production() -> None:
    policy = _make_policy(
        "p2",
        """
forbid(principal, action in [Action::"db.drop", Action::"db.truncate"], resource)
when { resource has environment && resource.environment == "production" };
    """,
    )
    result = evaluate_policies(
        [policy], "agent-1", "db.truncate", "mydb", {"environment": "production"}
    )
    assert result.decision == "DENY"


def test_forbid_not_matching_environment() -> None:
    policy = _make_policy(
        "p2",
        """
forbid(principal, action in [Action::"db.drop", Action::"db.truncate"], resource)
when { resource has environment && resource.environment == "production" };
    """,
    )
    result = evaluate_policies([policy], "agent-1", "db.drop", "mydb", {"environment": "staging"})
    assert result.decision == "DENY"  # no permit found → default deny


# --- Approval required ---


def test_approval_required_production_deploy() -> None:
    policy = _make_policy(
        "p3",
        """
forbid(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "production" }
unless { context has approval_status && context.approval_status == "approved" };
    """,
    )
    result = evaluate_policies(
        [policy], "agent-1", "deploy", "server", {"environment": "production"}
    )
    assert result.decision == "APPROVAL_REQUIRED"
    assert result.requires_approval is True
    assert result.policy_id == "p3"


def test_approval_already_approved() -> None:
    policy = _make_policy(
        "p3",
        """
forbid(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "production" }
unless { context has approval_status && context.approval_status == "approved" };
    """,
    )
    result = evaluate_policies(
        [policy],
        "agent-1",
        "deploy",
        "server",
        {"environment": "production", "approval_status": "approved"},
    )
    assert result.decision == "ALLOW"  # unless clause satisfied → forbid doesn't apply


# --- Forbid overrides permit ---


def test_forbid_overrides_permit() -> None:
    permit = _make_policy(
        "p1",
        """
permit(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "production" };
    """,
    )
    forbid = _make_policy(
        "p2",
        """
forbid(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "production" };
    """,
    )
    result = evaluate_policies(
        [permit, forbid], "agent-1", "deploy", "server", {"environment": "production"}
    )
    assert result.decision == "DENY"


# --- Multiple policies ---


def test_multiple_policies_permit_wins_when_no_forbid() -> None:
    p1 = _make_policy(
        "p1",
        """
permit(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "staging" };
    """,
    )
    p2 = _make_policy(
        "p2",
        """
forbid(principal, action == Action::"db.drop", resource)
when { resource has environment && resource.environment == "production" };
    """,
    )
    result = evaluate_policies([p1, p2], "agent-1", "deploy", "server", {"environment": "staging"})
    assert result.decision == "ALLOW"
    assert result.policy_id == "p1"


def test_unrelated_forbid_doesnt_affect_permit() -> None:
    p1 = _make_policy(
        "p1",
        """
permit(principal, action == Action::"fs.write", resource)
when { resource has path && resource.path == "/src/main.py" };
    """,
    )
    p2 = _make_policy(
        "p2",
        """
forbid(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "production" };
    """,
    )
    result = evaluate_policies([p1, p2], "agent-1", "fs.write", "file", {"path": "/src/main.py"})
    assert result.decision == "ALLOW"


# --- Path-like patterns ---


def test_forbid_env_file_write() -> None:
    policy = _make_policy(
        "p4",
        """
forbid(principal, action in [Action::"fs.write", Action::"fs.delete"], resource)
when { resource has path && resource.path like "*.env*" };
    """,
    )
    result = evaluate_policies([policy], "agent-1", "fs.write", "file", {"path": "app/.env.local"})
    assert result.decision == "DENY"


def test_forbid_secrets_file() -> None:
    policy = _make_policy(
        "p4",
        """
forbid(principal, action in [Action::"fs.write", Action::"fs.delete"], resource)
when { resource has path && resource.path like "*secrets*" };
    """,
    )
    result = evaluate_policies(
        [policy], "agent-1", "fs.write", "file", {"path": "/config/secrets.json"}
    )
    assert result.decision == "DENY"


def test_permit_src_write() -> None:
    policy = _make_policy(
        "p5",
        """
permit(principal, action == Action::"fs.write", resource)
when { resource has path && resource.path like "/src/*" };
    """,
    )
    result = evaluate_policies([policy], "agent-1", "fs.write", "file", {"path": "/src/app.py"})
    assert result.decision == "ALLOW"


def test_permit_tests_write() -> None:
    policy = _make_policy(
        "p5",
        """
permit(principal, action == Action::"fs.write", resource)
when { resource has path && resource.path like "/tests/*" };
    """,
    )
    result = evaluate_policies(
        [policy], "agent-1", "fs.write", "file", {"path": "/tests/test_main.py"}
    )
    assert result.decision == "ALLOW"


# --- Latency ---


def test_latency_is_recorded() -> None:
    policy = _make_policy(
        "p1",
        """
permit(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "staging" };
    """,
    )
    result = evaluate_policies([policy], "agent-1", "deploy", "server", {"environment": "staging"})
    assert result.latency_ms >= 0


# --- Edge cases ---


def test_action_not_in_any_policy() -> None:
    policy = _make_policy(
        "p1",
        """
permit(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "staging" };
    """,
    )
    result = evaluate_policies([policy], "agent-1", "unknown_action", "res", {})
    assert result.decision == "DENY"


def test_empty_context_with_when_clause() -> None:
    policy = _make_policy(
        "p1",
        """
permit(principal, action == Action::"deploy", resource)
when { resource has environment && resource.environment == "staging" };
    """,
    )
    result = evaluate_policies([policy], "agent-1", "deploy", "server", {})
    assert result.decision == "DENY"


def test_result_dataclass_properties() -> None:
    result = EvaluationResult(
        decision="ALLOW", reason="test", policy_id="p1", requires_approval=False, latency_ms=0.5
    )
    assert result.decision == "ALLOW"
    assert result.policy_id == "p1"
    assert result.latency_ms == 0.5
