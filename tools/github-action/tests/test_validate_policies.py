"""Tests for the AGR GitHub Action validator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_validator_module():
    module_path = Path(__file__).resolve().parents[1] / "validate_policies.py"
    spec = importlib.util.spec_from_file_location("validate_policies_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load validate_policies.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator_module()


def test_load_config_merges_yaml(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "agr-policy-check.yml"
    config_file.write_text(
        """
policy_dir: fixtures/policies
changed_only: true
fail_on_conflict: false
fail_on_violation: true
evaluation_tests:
  - name: deploy review
    action: deploy
    resource: production-cluster
    expect: APPROVAL_REQUIRED
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGR_API_KEY", "agr_sk_test")
    monkeypatch.setenv("AGR_BASE_URL", "https://example.agr.dev")
    monkeypatch.setenv("CONFIG_FILE", str(config_file))
    monkeypatch.setenv("DRY_RUN_AGENT", "deploy-bot")

    config = validator.load_config()

    assert config.api_key == "agr_sk_test"
    assert config.api_base_url == "https://example.agr.dev"
    assert config.changed_only is True
    assert config.fail_on_conflict is False
    assert config.evaluation_tests[0].agent == "deploy-bot"
    assert config.evaluation_tests[0].expect == "APPROVAL_REQUIRED"


def test_load_policy_entries_supports_cedar_and_yaml(tmp_path: Path) -> None:
    cedar_file = tmp_path / "deploy.cedar"
    cedar_file.write_text(
        'forbid(principal, action == Action::"deploy", resource);',
        encoding="utf-8",
    )

    yaml_file = tmp_path / "pack.yaml"
    yaml_file.write_text(
        """
policies:
  - name: allow-read
    level: org
    cedar_rule: 'permit(principal, action == Action::"read", resource);'
""".strip(),
        encoding="utf-8",
    )

    cedar_entries = validator.load_policy_entries(cedar_file)
    yaml_entries = validator.load_policy_entries(yaml_file)

    assert cedar_entries[0].name == "deploy"
    assert cedar_entries[0].cedar_rule.startswith("forbid(")
    assert yaml_entries[0].name == "allow-read"
    assert yaml_entries[0].level == "org"


def test_run_evaluation_tests_uses_local_policy_engine() -> None:
    policies = [
        validator.PolicyFileEntry(
            file=validator.REPO_ROOT / "policies" / "deploy.cedar",
            name="require-approval",
            cedar_rule=(
                'forbid(principal, action == Action::"deploy", resource) '
                'unless { context.approval_status == "approved" };'
            ),
        )
    ]
    cases = [
        validator.EvaluationCase(
            name="deploy approval",
            agent="deploy-bot",
            action="deploy",
            resource="production-cluster",
            expect="APPROVAL_REQUIRED",
            context={"environment": "production"},
        )
    ]

    results = validator.run_evaluation_tests(policies, cases)

    assert results[0]["passed"] is True
    assert results[0]["actual"] == "APPROVAL_REQUIRED"


def test_main_returns_nonzero_when_evaluation_violation_detected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    (policy_dir / "deny.cedar").write_text(
        'forbid(principal, action == Action::"deploy", resource);',
        encoding="utf-8",
    )

    config_file = tmp_path / "agr-policy-check.yml"
    config_file.write_text(
        """
evaluation_tests:
  - name: deploy should stay allowed
    agent: deploy-bot
    action: deploy
    resource: production-cluster
    expect: ALLOW
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("AGR_API_KEY", "agr_sk_test")
    monkeypatch.setenv("POLICY_DIR", str(policy_dir))
    monkeypatch.setenv("CONFIG_FILE", str(config_file))
    monkeypatch.setenv("FAIL_ON_VIOLATION", "true")
    monkeypatch.setenv("FAIL_ON_CONFLICT", "true")
    monkeypatch.delenv("CHANGED_ONLY", raising=False)
    monkeypatch.setattr(
        validator,
        "api_validate",
        lambda client, config, policy: {"valid": True, "conflicts": []},
    )

    exit_code = validator.main()

    assert exit_code == 1
