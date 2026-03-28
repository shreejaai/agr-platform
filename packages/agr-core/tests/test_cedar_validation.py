from policy_engine import validate_cedar_rule


def test_validate_cedar_rule_accepts_well_formed_permit(monkeypatch) -> None:
    monkeypatch.setattr("policy_engine._find_cedar_cli", lambda: None)

    result = validate_cedar_rule('permit(principal, action == Action::"read", resource);')

    assert result.valid is True
    assert result.error is None


def test_validate_cedar_rule_rejects_malformed_input(monkeypatch) -> None:
    monkeypatch.setattr("policy_engine._find_cedar_cli", lambda: None)

    result = validate_cedar_rule("permit(resource);")

    assert result.valid is False
    assert result.error is not None
