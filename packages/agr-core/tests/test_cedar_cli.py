"""Tests for the Cedar CLI evaluation path in policy_engine.py.

These tests are skipped automatically when the `cedar` binary is not on PATH.
CI job `test-cedar-cli` installs Cedar before running this file.
"""

import os
import shutil
import stat
import tempfile

import pytest
from policy_engine import (
    _cedar_cli_authorize,
    _cedar_cli_evaluator,
    _cedar_policy_text,
    _find_cedar_cli,
    evaluate_policies,
)

cedar_required = pytest.mark.skipif(
    shutil.which("cedar") is None,
    reason="cedar CLI not installed — skipped in dev/CI without cedar job",
)


def _make_fake_cedar_validator() -> str:
    """Create a fake cedar executable that validates request-json file contents."""
    tmpdir = tempfile.mkdtemp()
    fake_cedar = os.path.join(tmpdir, "cedar")
    script = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

args = sys.argv[1:]
request_path = Path(args[args.index("--request-json") + 1])
payload = json.loads(request_path.read_text(encoding="utf-8"))

assert isinstance(payload["principal"], str)
assert isinstance(payload["action"], str)
assert isinstance(payload["resource"], str)
assert payload["principal"].startswith('Agent::"')
assert payload["action"].startswith('Action::"')
assert payload["resource"].startswith('Resource::"')
assert isinstance(payload["context"], dict)

print("Decision: ALLOW")
"""
    with open(fake_cedar, "w", encoding="utf-8") as fh:
        fh.write(script)
    os.chmod(fake_cedar, os.stat(fake_cedar).st_mode | stat.S_IXUSR)
    return fake_cedar


class TestCedarCliRequestFormat:
    def test_request_json_uses_string_entity_uids(self):
        fake_cedar = _make_fake_cedar_validator()
        result = _cedar_cli_authorize(
            fake_cedar,
            [PERMIT_ALL_POLICY],
            "agent1",
            "read",
            "db",
            {"env": "staging"},
        )
        assert result == "ALLOW"

    def test_approval_rules_emit_companion_permit_for_cli(self):
        policy_text = _cedar_policy_text([APPROVAL_REQUIRED_POLICY])

        assert APPROVAL_REQUIRED_POLICY["cedar_rule"] in policy_text
        assert (
            'permit(principal, action == Action::"deploy", resource) '
            'when { context.approval_status == "approved" };'
        ) in policy_text


PERMIT_ALL_POLICY = {
    "id": "p1",
    "cedar_rule": "permit(principal, action, resource);",
}

DENY_DEPLOY_POLICY = {
    "id": "p2",
    "cedar_rule": 'forbid(principal, action == Action::"deploy", resource);',
}

APPROVAL_REQUIRED_POLICY = {
    "id": "p3",
    "cedar_rule": (
        'forbid(principal, action == Action::"deploy", resource) '
        'unless { context.approval_status == "approved" };'
    ),
}


@cedar_required
class TestFindCedarCli:
    def test_returns_path_when_installed(self):
        path = _find_cedar_cli()
        assert path is not None
        assert "cedar" in path


@cedar_required
class TestCedarCliAuthorize:
    def test_permit_all_allows(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_authorize(cedar, [PERMIT_ALL_POLICY], "agent1", "read", "db", {})
        assert result == "ALLOW"

    def test_deny_deploy_blocks(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_authorize(cedar, [DENY_DEPLOY_POLICY], "agent1", "deploy", "prod", {})
        assert result == "DENY"

    def test_no_matching_policy_denies(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_authorize(cedar, [DENY_DEPLOY_POLICY], "agent1", "read", "db", {})
        assert result == "DENY"

    def test_permit_with_context(self):
        cedar = _find_cedar_cli()
        policy = {
            "id": "p4",
            "cedar_rule": (
                'permit(principal, action, resource) when { context.env == "staging" };'
            ),
        }
        result = _cedar_cli_authorize(cedar, [policy], "a1", "read", "db", {"env": "staging"})
        assert result == "ALLOW"

    def test_permit_with_wrong_context_denies(self):
        cedar = _find_cedar_cli()
        policy = {
            "id": "p4",
            "cedar_rule": (
                'permit(principal, action, resource) when { context.env == "staging" };'
            ),
        }
        result = _cedar_cli_authorize(cedar, [policy], "a1", "read", "db", {"env": "prod"})
        assert result == "DENY"


@cedar_required
class TestCedarCliEvaluator:
    def test_allow_decision(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_evaluator(cedar, [PERMIT_ALL_POLICY], "a1", "read", "db", {})
        assert result.decision == "ALLOW"
        assert result.policy_source == "cedar_cli"
        assert result.requires_approval is False

    def test_deny_decision(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_evaluator(cedar, [DENY_DEPLOY_POLICY], "a1", "deploy", "prod", {})
        assert result.decision == "DENY"
        assert result.policy_source == "cedar_cli"
        assert result.requires_approval is False

    def test_approval_required_detected(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_evaluator(cedar, [APPROVAL_REQUIRED_POLICY], "a1", "deploy", "prod", {})
        assert result.decision == "APPROVAL_REQUIRED"
        assert result.policy_source == "cedar_cli"
        assert result.requires_approval is True

    def test_approval_required_with_status_approved_allows(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_evaluator(
            cedar,
            [APPROVAL_REQUIRED_POLICY],
            "a1",
            "deploy",
            "prod",
            {"approval_status": "approved"},
        )
        assert result.decision == "ALLOW"
        assert result.policy_source == "cedar_cli"


@cedar_required
class TestEvaluatePoliciesIntegration:
    def test_uses_cedar_cli_when_available(self):
        result = evaluate_policies([PERMIT_ALL_POLICY], "agent1", "read", "db", {})
        assert result.decision == "ALLOW"
        assert result.policy_source == "cedar_cli"
