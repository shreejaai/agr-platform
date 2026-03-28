"""Parity tests: Cedar CLI vs Python fallback evaluator.

These tests run the same request through BOTH engines and assert that they
produce the same decision.  Mismatches indicate either a Python regex bug or
a Cedar policy that uses syntax the fallback cannot parse.

Skipped automatically when the `cedar` CLI binary is not on PATH.

Run in CI via the `test-cedar-cli` job, which installs the Cedar CLI first.
"""

import shutil

import pytest
from policy_engine import (
    _cedar_cli_evaluator,
    _find_cedar_cli,
    _python_evaluator,
)

cedar_required = pytest.mark.skipif(
    shutil.which("cedar") is None,
    reason="cedar CLI not installed — skipped without cedar binary",
)

# ---------------------------------------------------------------------------
# Test cases: (description, policies, agent_id, action, resource, context, expected_decision)
# ---------------------------------------------------------------------------

PERMIT_ALL = {"id": "permit-all", "cedar_rule": "permit(principal, action, resource);"}

DENY_DEPLOY = {
    "id": "deny-deploy",
    "cedar_rule": 'forbid(principal, action == Action::"deploy", resource);',
}

APPROVAL_REQUIRED_POLICY = {
    "id": "approval-deploy",
    "cedar_rule": (
        'forbid(principal, action == Action::"deploy", resource) '
        'unless { context.approval_status == "approved" };'
    ),
}

CONTEXT_PERMIT = {
    "id": "ctx-permit",
    "cedar_rule": ('permit(principal, action, resource) when { context.env == "staging" };'),
}

WIRE_APPROVAL_POLICY = {
    "id": "wire-approval",
    "cedar_rule": (
        'forbid(principal, action == Action::"wire.transfer", resource) '
        "when { context has amount && context.amount > 50000 } "
        'unless { context has approval_status && context.approval_status == "approved" };'
    ),
}

OFAC_DENY_POLICY = {
    "id": "wire-ofac",
    "cedar_rule": (
        'forbid(principal, action == Action::"wire.transfer", resource) '
        "when { context has destination_country && "
        '(context.destination_country == "IR" || '
        'context.destination_country == "KP" || '
        'context.destination_country == "SY" || '
        'context.destination_country == "CU") };'
    ),
}

PAYROLL_APPROVAL_POLICY = {
    "id": "payroll-approval",
    "cedar_rule": (
        'forbid(principal, action == Action::"ach.batch_submit", resource) '
        "when { context has is_after_hours && context.is_after_hours == true && "
        "context has total_amount && context.total_amount > 100000 } "
        'unless { context has approval_status && context.approval_status == "approved" };'
    ),
}

PAYROLL_PERMIT_POLICY = {
    "id": "payroll-permit",
    "cedar_rule": (
        'permit(principal, action == Action::"ach.batch_submit", resource) '
        'when { context has batch_type && context.batch_type == "payroll" && '
        "context has total_amount && context.total_amount <= 500000 };"
    ),
}

SMALL_CLAIM_PERMIT_POLICY = {
    "id": "claim-permit",
    "cedar_rule": (
        'permit(principal, action == Action::"claim.approve", resource) '
        "when { context has claim_amount && context.claim_amount <= 2500 && "
        "context has fraud_score && context.fraud_score < 0.3 };"
    ),
}

HIGH_FRAUD_APPROVAL_POLICY = {
    "id": "claim-fraud-review",
    "cedar_rule": (
        'forbid(principal, action == Action::"claim.approve", resource) '
        "when { context has fraud_score && context.fraud_score >= 0.75 } "
        'unless { context has approval_status && context.approval_status == "approved" };'
    ),
}

PARITY_CASES = [
    # id, description, policies, agent, action, resource, context, expected
    (
        "permit_all_allows",
        "permit(all) → ALLOW",
        [PERMIT_ALL],
        "agent1",
        "read",
        "db",
        {},
        "ALLOW",
    ),
    (
        "deny_deploy_blocks",
        "forbid(deploy) → DENY",
        [DENY_DEPLOY],
        "agent1",
        "deploy",
        "prod",
        {},
        "DENY",
    ),
    (
        "deny_deploy_allows_other_actions",
        "forbid(deploy) does not block read",
        [PERMIT_ALL, DENY_DEPLOY],
        "agent1",
        "read",
        "db",
        {},
        "ALLOW",
    ),
    (
        "approval_required_without_status",
        "approval policy → APPROVAL_REQUIRED without approval_status",
        [APPROVAL_REQUIRED_POLICY],
        "agent1",
        "deploy",
        "prod",
        {},
        "APPROVAL_REQUIRED",
    ),
    (
        "approval_required_with_approved_status",
        "approval policy + approval_status=approved → ALLOW",
        [APPROVAL_REQUIRED_POLICY],
        "agent1",
        "deploy",
        "prod",
        {"approval_status": "approved"},
        "ALLOW",
    ),
    (
        "context_permit_matching",
        "context permit with matching env → ALLOW",
        [CONTEXT_PERMIT],
        "agent1",
        "read",
        "db",
        {"env": "staging"},
        "ALLOW",
    ),
    (
        "context_permit_non_matching",
        "context permit with non-matching env → DENY",
        [CONTEXT_PERMIT],
        "agent1",
        "read",
        "db",
        {"env": "prod"},
        "DENY",
    ),
    (
        "no_matching_policy",
        "no matching policy → DENY by default",
        [DENY_DEPLOY],
        "agent1",
        "read",
        "db",
        {},
        "DENY",
    ),
    (
        "permit_and_forbid_forbid_wins",
        "permit + forbid on same action → DENY (deny-overrides)",
        [PERMIT_ALL, DENY_DEPLOY],
        "agent1",
        "deploy",
        "prod",
        {},
        "DENY",
    ),
    (
        "ofac_deny_not_shadowed_by_wire_approval",
        "specific OFAC deny beats unrelated approval-gated wire rule",
        [WIRE_APPROVAL_POLICY, OFAC_DENY_POLICY],
        "finance-agent",
        "wire.transfer",
        "recipient",
        {"amount": 5000, "destination_country": "IR"},
        "DENY",
    ),
    (
        "wire_approval_without_status",
        "wire approval rule → APPROVAL_REQUIRED without approval_status",
        [WIRE_APPROVAL_POLICY],
        "finance-agent",
        "wire.transfer",
        "recipient",
        {"amount": 75000},
        "APPROVAL_REQUIRED",
    ),
    (
        "wire_approval_with_approved_status",
        "wire approval rule + approval_status=approved → ALLOW",
        [WIRE_APPROVAL_POLICY],
        "finance-agent",
        "wire.transfer",
        "recipient",
        {"amount": 75000, "approval_status": "approved"},
        "ALLOW",
    ),
    (
        "payroll_allow_not_shadowed_by_after_hours_rule",
        "routine payroll stays ALLOW when after-hours approval rule does not match",
        [PAYROLL_APPROVAL_POLICY, PAYROLL_PERMIT_POLICY],
        "finance-agent",
        "ach.batch_submit",
        "payroll",
        {"batch_type": "payroll", "is_after_hours": False, "total_amount": 380000},
        "ALLOW",
    ),
    (
        "small_claim_allow_not_shadowed_by_high_fraud_rule",
        "small low-fraud claim stays ALLOW when fraud review rule does not match",
        [SMALL_CLAIM_PERMIT_POLICY, HIGH_FRAUD_APPROVAL_POLICY],
        "claims-agent",
        "claim.approve",
        "claim",
        {"claim_amount": 1800, "fraud_score": 0.12},
        "ALLOW",
    ),
]


@cedar_required
@pytest.mark.parametrize(
    "case_id,description,policies,agent,action,resource,context,expected",
    PARITY_CASES,
    ids=[c[0] for c in PARITY_CASES],
)
def test_cedar_vs_python_parity(
    case_id: str,
    description: str,
    policies: list[dict[str, str]],
    agent: str,
    action: str,
    resource: str,
    context: dict[str, object],
    expected: str,
) -> None:
    """Both Cedar CLI and Python fallback must produce the same decision."""
    cedar = _find_cedar_cli()
    assert cedar is not None, "cedar binary must be on PATH for parity tests"

    cedar_result = _cedar_cli_evaluator(cedar, policies, agent, action, resource, context)
    python_result = _python_evaluator(policies, agent, action, resource, context)

    assert cedar_result.decision == expected, (
        f"Cedar CLI gave unexpected decision for '{description}': "
        f"got {cedar_result.decision!r}, expected {expected!r}"
    )
    assert python_result.decision == expected, (
        f"Python fallback gave unexpected decision for '{description}': "
        f"got {python_result.decision!r}, expected {expected!r}"
    )
    assert cedar_result.decision == python_result.decision, (
        f"PARITY MISMATCH for '{description}': "
        f"Cedar={cedar_result.decision!r} Python={python_result.decision!r}. "
        "The Python fallback diverges from Cedar CLI for this policy. Fix the fallback."
    )


@cedar_required
def test_fallback_tracking_cedar_path() -> None:
    """When Cedar CLI is available, fallback_used must be False."""
    from policy_engine import evaluate_policies

    result = evaluate_policies([PERMIT_ALL], "agent1", "read", "db", {})
    assert result.policy_source == "cedar_cli"
    assert result.fallback_used is False
    assert result.fallback_reason is None


def test_fallback_tracking_python_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """When Cedar CLI is absent, fallback_used must be True and reason set."""
    monkeypatch.setattr("policy_engine._find_cedar_cli", lambda: None)

    from policy_engine import evaluate_policies

    result = evaluate_policies([PERMIT_ALL], "agent1", "read", "db", {})
    assert result.policy_source == "python_fallback"
    assert result.fallback_used is True
    assert result.fallback_reason == "cedar_cli_not_found"


def test_fallback_tracking_no_policies() -> None:
    """Empty policy list returns no_policies source; fallback_used is False."""
    from policy_engine import evaluate_policies

    result = evaluate_policies([], "agent1", "read", "db", {})
    assert result.policy_source == "no_policies"
    assert result.decision == "DENY"
    assert result.fallback_used is False
