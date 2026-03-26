"""Unit tests for the risk scoring engine."""

from app.services.risk_service import RiskResult, compute_risk_score


def test_low_risk_read_action() -> None:
    result = compute_risk_score(
        agent_id="trusted-reader",
        action="read",
        resource="docs/readme.txt",
        context={},
    )
    assert result.score <= 30
    assert result.level == "low"


def test_high_risk_destructive_action() -> None:
    result = compute_risk_score(
        agent_id="agent-001",
        action="db.drop",
        resource="production-db",
        context={"environment": "production"},
    )
    assert result.score > 30
    assert result.level in ("medium", "high")


def test_high_risk_delete_production() -> None:
    result = compute_risk_score(
        agent_id="agent-999",
        action="delete",
        resource="user-data",
        context={"environment": "production", "count": 1_000_000},
    )
    assert result.score >= 50


def test_trusted_agent_lowers_score() -> None:
    trusted = compute_risk_score(
        agent_id="trusted-agent",
        action="deploy",
        resource="staging",
        context={},
    )
    untrusted = compute_risk_score(
        agent_id="agent-4567",
        action="deploy",
        resource="staging",
        context={},
    )
    # Trusted agent should score lower on agent_trust factor
    assert trusted.factors["agent_trust"] <= untrusted.factors["agent_trust"]


def test_risk_result_fields() -> None:
    result = compute_risk_score(
        agent_id="bot-1",
        action="write",
        resource="file.txt",
        context={"amount": 5000},
    )
    assert isinstance(result, RiskResult)
    assert 0 <= result.score <= 100
    assert result.level in ("low", "medium", "high")
    assert set(result.factors.keys()) == {
        "action_severity",
        "context_signals",
        "rate_pattern",
        "agent_trust",
        "amount_scale",
        "resource_sensitivity",
    }


def test_rate_pressure_near_limit() -> None:
    result_high_usage = compute_risk_score(
        agent_id="agent-1",
        action="list",
        resource="items",
        context={},
        eval_count=950,
        eval_limit=1000,
    )
    result_low_usage = compute_risk_score(
        agent_id="agent-1",
        action="list",
        resource="items",
        context={},
        eval_count=10,
        eval_limit=1000,
    )
    assert result_high_usage.factors["rate_pattern"] > result_low_usage.factors["rate_pattern"]


def test_unlimited_plan_no_rate_pressure() -> None:
    result = compute_risk_score(
        agent_id="agent-1",
        action="list",
        resource="items",
        context={},
        eval_count=9999,
        eval_limit=0,
    )
    assert result.factors["rate_pattern"] == 0


def test_large_amount_raises_score() -> None:
    result = compute_risk_score(
        agent_id="agent-1",
        action="transfer",
        resource="bank",
        context={"amount": 2_000_000},
    )
    assert result.factors["amount_scale"] > 0


def test_score_bounded_0_100() -> None:
    """Score never exceeds 100 or goes below 0."""
    result = compute_risk_score(
        agent_id="agent-drop-prod-9999",
        action="drop",
        resource="production-database",
        context={
            "environment": "production",
            "force": "true",
            "recursive": "yes",
            "amount": 999_999_999,
        },
    )
    assert 0 <= result.score <= 100
