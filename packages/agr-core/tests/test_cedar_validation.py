import subprocess

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


def test_validate_cedar_rule_falls_back_when_cli_requires_schema(monkeypatch) -> None:
    monkeypatch.setattr("policy_engine._find_cedar_cli", lambda: "/usr/bin/cedar")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=2,
            stdout="",
            stderr=(
                "error: the following required arguments were not provided:\n"
                "  --schema <FILE>\n\n"
                "Usage: cedar validate --schema <FILE> --policies <FILE>\n"
            ),
        )

    monkeypatch.setattr("policy_engine.subprocess.run", fake_run)

    result = validate_cedar_rule('permit(principal, action == Action::"read", resource);')

    assert result.valid is True
    assert result.error is None


def test_validate_cedar_rule_schema_fallback_still_rejects_bad_rule(monkeypatch) -> None:
    monkeypatch.setattr("policy_engine._find_cedar_cli", lambda: "/usr/bin/cedar")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=2,
            stdout="",
            stderr=(
                "error: the following required arguments were not provided:\n"
                "  --schema <FILE>\n\n"
                "Usage: cedar validate --schema <FILE> --policies <FILE>\n"
            ),
        )

    monkeypatch.setattr("policy_engine.subprocess.run", fake_run)

    result = validate_cedar_rule("permit(resource);")

    assert result.valid is False
    assert result.error is not None
