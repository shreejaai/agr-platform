"""Tests for the lightweight AGR CLI package."""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from importlib import import_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "packages" / "agr-sdk-python"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "agr-cli"))

agr = import_module("agr")
DecisionTrace = agr.DecisionTrace
EvaluationResult = agr.EvaluationResult
SimulationResult = agr.SimulationResult
run = import_module("agr_cli.main").run


class FakeClient:
    init_args: list[dict[str, object]] = []
    import_calls: list[dict[str, object]] = []

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.agr.dev") -> None:
        self.api_key = api_key
        self.base_url = base_url
        type(self).init_args.append({"api_key": api_key, "base_url": base_url})

    def evaluate(
        self,
        *,
        agent: str,
        action: str,
        resource: str,
        context: dict[str, object],
    ) -> EvaluationResult:
        return EvaluationResult(
            decision="ALLOW",
            reason=f"{agent}:{action}:{resource}",
            policy_id="policy-1",
            approval_id=None,
            latency_ms=12.0,
            eval_id="eval-1",
            risk_score=15,
            risk_level="low",
            risk_factors={"action_severity": 15},
            compliance_findings=[],
        )

    def simulate(
        self,
        *,
        agent: str,
        action: str,
        resource: str,
        context: dict[str, object],
    ) -> SimulationResult:
        return SimulationResult(
            decision="APPROVAL_REQUIRED",
            reason=f"{agent}:{action}:{resource}",
            policy_id="policy-sim",
            risk_score=78,
            risk_level="high",
            risk_factors={"action_severity": 55},
            compliance_findings=[],
            decision_trace=DecisionTrace(
                policy_source="python_fallback",
                matched_policy_id="policy-sim",
                cedar_decision="ALLOW",
                risk_score=78,
                risk_level="high",
                risk_override=True,
                fallback_used=True,
                fallback_reason="cedar_cli_not_found",
            ),
        )

    def import_policies(
        self,
        *,
        policies: list[dict[str, object]],
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> dict[str, object]:
        type(self).import_calls.append(
            {"policies": policies, "overwrite": overwrite, "dry_run": dry_run}
        )
        return {
            "dry_run": dry_run,
            "total": len(policies),
            "created": len(policies),
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "results": [{"name": item["name"], "status": "created"} for item in policies],
        }

    def close(self) -> None:
        return None


def _run_cli(monkeypatch, argv: list[str]) -> tuple[int, str, str]:
    monkeypatch.setattr("agr_cli.main.AGRClient", FakeClient)
    FakeClient.init_args.clear()
    FakeClient.import_calls.clear()
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = run(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_eval_outputs_readable_result(monkeypatch) -> None:
    code, stdout, stderr = _run_cli(
        monkeypatch,
        [
            "eval",
            "--api-key",
            "agr_sk_cli",
            "--base-url",
            "http://localhost:8000",
            "--agent",
            "deploy-bot",
            "--action",
            "deploy",
            "--resource",
            "prod-cluster",
            "--context",
            '{"environment":"production"}',
        ],
    )

    assert code == 0
    assert stderr == ""
    assert "Decision" in stdout
    assert "Eval Id" in stdout
    assert FakeClient.init_args[-1] == {
        "api_key": "agr_sk_cli",
        "base_url": "http://localhost:8000",
    }


def test_simulate_supports_json_output(monkeypatch) -> None:
    code, stdout, stderr = _run_cli(
        monkeypatch,
        [
            "simulate",
            "--agent",
            "finance-bot",
            "--action",
            "transfer_funds",
            "--resource",
            "treasury-system",
            "--context",
            '{"amount":50000}',
            "--json",
        ],
    )

    assert code == 0
    assert stderr == ""
    payload = json.loads(stdout)
    assert payload["decision"] == "APPROVAL_REQUIRED"
    assert payload["decision_trace"]["risk_override"] is True


def test_policy_apply_wraps_raw_cedar_file(monkeypatch, tmp_path: Path) -> None:
    policy_file = tmp_path / "prod-deploy.cedar"
    cedar_rule = (
        'forbid(principal, action == Action::"deploy", resource) '
        'unless { context.approval_status == "approved" };'
    )
    policy_file.write_text(
        cedar_rule,
        encoding="utf-8",
    )

    code, stdout, stderr = _run_cli(
        monkeypatch,
        [
            "policy",
            "apply",
            "--file",
            str(policy_file),
            "--level",
            "agent",
            "--state",
            "draft",
            "--overwrite",
            "--dry-run",
        ],
    )

    assert code == 0
    assert stderr == ""
    assert "Dry Run" in stdout
    assert FakeClient.import_calls[-1] == {
        "policies": [
            {
                "name": "prod-deploy",
                "level": "agent",
                "cedar_rule": cedar_rule,
                "state": "draft",
                "active": False,
            }
        ],
        "overwrite": True,
        "dry_run": True,
    }


def test_invalid_context_returns_nonzero(monkeypatch) -> None:
    code, stdout, stderr = _run_cli(
        monkeypatch,
        [
            "eval",
            "--agent",
            "deploy-bot",
            "--action",
            "deploy",
            "--resource",
            "prod-cluster",
            "--context",
            '["not","an","object"]',
        ],
    )

    assert code == 1
    assert stdout == ""
    assert "Context must be a JSON object" in stderr
