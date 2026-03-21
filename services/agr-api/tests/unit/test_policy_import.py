"""Unit tests for policy import/export service utilities."""

import pytest
from app.schemas import PolicyImportItem, PolicyImportRequest
from app.services.policy_import_service import (
    parse_cedar_raw_import,
    parse_yaml_import,
)


def _valid_item(name: str = "Test policy") -> dict:
    return {
        "name": name,
        "level": "org",
        "cedar_rule": 'permit(principal, action == Action::"read", resource);',
    }


def test_parse_yaml_import_valid() -> None:
    yaml_str = """\
policies:
  - name: Allow reads
    level: org
    cedar_rule: 'permit(principal, action == Action::"read", resource);'
"""
    req = parse_yaml_import(yaml_str)
    assert len(req.policies) == 1
    assert req.policies[0].name == "Allow reads"
    assert req.policies[0].level == "org"


def test_parse_yaml_import_multiple() -> None:
    yaml_str = """\
policies:
  - name: Policy A
    level: org
    cedar_rule: 'permit(principal, action == Action::"read", resource);'
  - name: Policy B
    level: org
    cedar_rule: 'forbid(principal, action == Action::"drop", resource);'
dry_run: true
"""
    req = parse_yaml_import(yaml_str)
    assert len(req.policies) == 2
    assert req.dry_run is True


def test_parse_yaml_import_invalid_yaml() -> None:
    with pytest.raises(ValueError, match="Invalid YAML"):
        parse_yaml_import("policies: [unclosed")


def test_parse_yaml_import_not_mapping() -> None:
    with pytest.raises(ValueError, match="mapping"):
        parse_yaml_import("- just a list item")


def test_parse_cedar_raw_single_policy() -> None:
    raw = 'permit(principal, action == Action::"read", resource);'
    req = parse_cedar_raw_import(raw)
    assert len(req.policies) == 1
    assert req.policies[0].name == "Imported policy 1"
    assert req.policies[0].level == "org"


def test_parse_cedar_raw_multiple_blocks() -> None:
    raw = """\
permit(principal, action == Action::"read", resource);

forbid(principal, action == Action::"drop", resource);
"""
    req = parse_cedar_raw_import(raw)
    assert len(req.policies) == 2
    assert req.policies[0].name == "Imported policy 1"
    assert req.policies[1].name == "Imported policy 2"


def test_parse_cedar_raw_dry_run() -> None:
    raw = 'permit(principal, action == Action::"read", resource);'
    req = parse_cedar_raw_import(raw, dry_run=True)
    assert req.dry_run is True


def test_policy_import_item_cedar_validation() -> None:
    """PolicyImportItem validates Cedar rule structure."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        PolicyImportItem(
            name="Bad policy",
            level="org",
            cedar_rule="not a cedar rule",
        )


def test_policy_import_request_requires_at_least_one_policy() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        PolicyImportRequest(policies=[])
