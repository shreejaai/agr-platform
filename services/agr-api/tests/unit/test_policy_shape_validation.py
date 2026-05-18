"""W1.2 — policy shape validation (validate_policy_shape).

Table-driven tests cover:

- syntax errors propagate from validate_cedar_rule
- approval-pattern policies that reference approval_status WITHOUT comparing
  it to "approved" are rejected with hint + doc_url
- warnings (non-blocking) emitted for `has`, set ops, entity-set `in`
- every shipped example policy pack validates clean
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.cedar_service import validate_policy_shape


VALID_RULES = [
    'permit(principal, action == Action::"deploy", resource);',
    (
        'forbid(principal, action == Action::"transfer_funds", resource) '
        'unless { context.approval_status == "approved" };'
    ),
    'forbid(principal, action == Action::"drop_table", resource);',
]


INVALID_APPROVAL_PATTERN = (
    'forbid(principal, action == Action::"transfer_funds", resource) '
    'unless { context.approval_status == "ok" };'
)


@pytest.mark.parametrize("rule", VALID_RULES)
def test_valid_rules_pass(rule: str) -> None:
    result = validate_policy_shape(rule)
    assert result.valid is True
    assert result.error is None


def test_approval_pattern_without_approved_is_rejected() -> None:
    result = validate_policy_shape(INVALID_APPROVAL_PATTERN)
    assert result.valid is False
    assert result.error is not None
    assert "approval_status" in result.error
    assert result.hint is not None
    assert "approved" in result.hint
    assert result.doc_url is not None


def test_syntax_error_passed_through() -> None:
    result = validate_policy_shape("not a real cedar rule")
    assert result.valid is False
    assert result.hint is not None
    assert result.doc_url is not None


def test_has_construct_emits_warning_but_passes() -> None:
    rule = (
        'permit(principal, action == Action::"read", resource) '
        "when { context has region };"
    )
    result = validate_policy_shape(rule)
    assert result.valid is True
    assert any("has" in w for w in result.warnings)


def test_entity_set_in_emits_warning_but_passes() -> None:
    rule = (
        'permit(principal in [Agent::"a", Agent::"b"], '
        'action == Action::"read", resource);'
    )
    result = validate_policy_shape(rule)
    assert result.valid is True
    assert any("in [...]" in w or "entity-set" in w for w in result.warnings)


def test_all_shipped_policy_packs_validate_clean() -> None:
    """Every Cedar rule in examples/policy_packs/*.yaml must shape-validate."""
    import yaml

    repo_root = Path(__file__).resolve().parents[4]
    pack_dir = repo_root / "examples" / "policy_packs"
    assert pack_dir.exists(), pack_dir

    failures: list[str] = []
    for pack_file in sorted(pack_dir.glob("*.yaml")):
        with pack_file.open() as fh:
            data = yaml.safe_load(fh) or {}
        for policy in data.get("policies", []) or []:
            rule = policy.get("cedar_rule")
            if not rule:
                continue
            result = validate_policy_shape(rule)
            if not result.valid:
                failures.append(
                    f"{pack_file.name} :: {policy.get('name', '?')} :: {result.error}"
                )

    assert not failures, "Shipped policy packs failed shape validation:\n" + "\n".join(
        failures
    )
