"""Tests for AsyncAGRClient.

Uses httpx.MockTransport to avoid real HTTP calls.
"""

import asyncio
import json

import httpx
import pytest
from agr.client import AGRAuthError, AGRError, AGRRateLimitError, AsyncAGRClient

ALLOW_RESPONSE = {
    "decision": "ALLOW",
    "reason": "Permitted by policy.",
    "policy_id": "p1",
    "approval_id": None,
    "latency_ms": 12.5,
    "eval_id": "eval-abc123",
    "risk_score": 10,
    "risk_level": "low",
    "risk_factors": {"action_severity": 10},
    "compliance_findings": [],
}

DENY_RESPONSE = {**ALLOW_RESPONSE, "decision": "DENY", "reason": "Denied by policy."}

APPROVAL_RESPONSE = {
    **ALLOW_RESPONSE,
    "decision": "APPROVAL_REQUIRED",
    "approval_id": "appr-xyz",
    "reason": "Requires human approval.",
}

COMPLIANCE_RESPONSE = {
    **ALLOW_RESPONSE,
    "compliance_findings": [
        {
            "plugin": "audit_trail_check",
            "standard": "SOC2",
            "rule_id": "CC6.1",
            "severity": "warning",
            "message": "Action is wildcard.",
            "passed": False,
            "remediation_steps": [
                "Replace wildcard or empty actions with the exact operation name being requested."
            ],
            "severity_level": "medium",
            "compliance_score": 61,
        }
    ],
}

SIMULATE_RESPONSE = {
    "decision": "APPROVAL_REQUIRED",
    "reason": "Simulation requires review.",
    "policy_id": "policy-123",
    "risk_score": 82,
    "risk_level": "high",
    "risk_factors": {"action_severity": 60, "context_signals": 22},
    "compliance_findings": [],
    "decision_trace": {
        "policy_source": "python_fallback",
        "matched_policy_id": "policy-123",
        "cedar_decision": "ALLOW",
        "risk_score": 82,
        "risk_level": "high",
        "risk_override": True,
        "fallback_used": True,
        "fallback_reason": "cedar_cli_not_found",
    },
}


def _make_transport(responses: list[tuple[int, dict]]):
    """Build a MockTransport that returns responses in order."""
    resp_iter = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        status, body = next(resp_iter)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


class TestAsyncAGRClientEvaluate:
    @pytest.mark.asyncio
    async def test_evaluate_allow(self):
        transport = _make_transport([(200, ALLOW_RESPONSE)])
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            result = await client.evaluate("agent1", "read", "db")
        assert result.decision == "ALLOW"
        assert result.allowed is True
        assert result.denied is False
        assert result.requires_approval is False
        assert result.risk_score == 10
        assert result.eval_id == "eval-abc123"

    @pytest.mark.asyncio
    async def test_evaluate_deny(self):
        transport = _make_transport([(200, DENY_RESPONSE)])
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            result = await client.evaluate("agent1", "deploy", "prod")
        assert result.denied is True

    @pytest.mark.asyncio
    async def test_evaluate_approval_required(self):
        transport = _make_transport([(200, APPROVAL_RESPONSE)])
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            result = await client.evaluate("agent1", "deploy", "prod")
        assert result.requires_approval is True
        assert result.approval_id == "appr-xyz"

    @pytest.mark.asyncio
    async def test_evaluate_preserves_enriched_compliance_findings(self):
        transport = _make_transport([(200, COMPLIANCE_RESPONSE)])
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            result = await client.evaluate("agent1", "deploy", "prod")
        assert result.compliance_findings is not None
        assert result.compliance_findings[0]["severity_level"] == "medium"
        assert result.compliance_findings[0]["compliance_score"] == 61

    @pytest.mark.asyncio
    async def test_evaluate_raises_auth_error_on_401(self):
        transport = _make_transport([(401, {"message": "Invalid API key."})])
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            with pytest.raises(AGRAuthError) as exc_info:
                await client.evaluate("a", "b", "c")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_evaluate_raises_rate_limit_on_429(self):
        transport = _make_transport(
            [(429, {"message": "Rate limit exceeded.", "upgrade_url": "https://agr.dev/pricing"})]
        )
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            with pytest.raises(AGRRateLimitError) as exc_info:
                await client.evaluate("a", "b", "c")
        assert exc_info.value.upgrade_url == "https://agr.dev/pricing"

    @pytest.mark.asyncio
    async def test_evaluate_raises_agr_error_on_500(self):
        transport = _make_transport([(500, {"detail": "Internal server error"})])
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            with pytest.raises(AGRError) as exc_info:
                await client.evaluate("a", "b", "c")
        assert exc_info.value.status_code == 500


class TestAsyncAGRClientWaitForApproval:
    @pytest.mark.asyncio
    async def test_approved(self):
        transport = _make_transport([(200, {"status": "approved"})])
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            result = await client.wait_for_approval("appr-1", poll_interval=0.01)
        assert result is True

    @pytest.mark.asyncio
    async def test_rejected(self):
        transport = _make_transport([(200, {"status": "rejected"})])
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            result = await client.wait_for_approval("appr-1", poll_interval=0.01)
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        def handler(request):
            return httpx.Response(200, json={"status": "pending"})

        transport = httpx.MockTransport(handler)
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            with pytest.raises(TimeoutError):
                await client.wait_for_approval("appr-1", poll_interval=0.01, timeout=0.05)


class TestAsyncAGRClientSimulate:
    @pytest.mark.asyncio
    async def test_simulate_returns_typed_result(self):
        transport = _make_transport([(200, SIMULATE_RESPONSE)])
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            result = await client.simulate(
                "agent1",
                "deploy",
                "prod-cluster",
                {"environment": "production"},
            )

        assert result.requires_approval is True
        assert result.risk_score == 82
        assert result.decision_trace is not None
        assert result.decision_trace.risk_override is True
        assert result.decision_trace.fallback_reason == "cedar_cli_not_found"


class TestAsyncAGRClientMisconfiguration:
    def test_raises_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("AGR_API_KEY", raising=False)
        with pytest.raises(AGRError, match="API key is required"):
            AsyncAGRClient(api_key="")


class TestAsyncAGRClientParity:
    @pytest.mark.asyncio
    async def test_policy_management_methods(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/v1/agents/register":
                payload = json.loads(request.content.decode())
                assert payload == {"agent_id": "agent-1", "metadata": {"team": "ops"}}
                return httpx.Response(200, json={"id": "agent-1", "status": "registered"})

            if request.method == "POST" and request.url.path == "/v1/policies/import":
                payload = json.loads(request.content.decode())
                assert payload["overwrite"] is True
                assert payload["dry_run"] is False
                assert len(payload["policies"]) == 1
                return httpx.Response(
                    200,
                    json={
                        "dry_run": False,
                        "total": 1,
                        "created": 1,
                        "updated": 0,
                        "skipped": 0,
                        "errors": [],
                        "results": [{"name": "allow-read", "status": "created"}],
                    },
                )

            if request.method == "GET" and request.url.path == "/v1/policies/export":
                assert request.url.params["active_only"] == "false"
                return httpx.Response(
                    200,
                    json=[
                        {
                            "name": "allow-read",
                            "level": "org",
                            "cedar_rule": "permit(principal, action, resource);",
                        }
                    ],
                )

            raise AssertionError(f"Unexpected request: {request.method} {request.url}")

        transport = httpx.MockTransport(handler)
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            agent = await client.register_agent("agent-1", metadata={"team": "ops"})
            imported = await client.import_policies(
                policies=[
                    {
                        "name": "allow-read",
                        "level": "org",
                        "cedar_rule": "permit(principal, action, resource);",
                    }
                ],
                overwrite=True,
            )
            exported = await client.export_policies(active_only=False)

        assert agent["status"] == "registered"
        assert imported["created"] == 1
        assert exported[0]["name"] == "allow-read"

    @pytest.mark.asyncio
    async def test_audit_risk_and_compliance_methods(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/v1/audit":
                assert request.url.params["event_type"] == "evaluation"
                assert request.url.params["agent_id"] == "agent-1"
                assert request.url.params["limit"] == "25"
                assert request.url.params["offset"] == "5"
                return httpx.Response(200, json=[{"id": "audit-1"}])

            if request.method == "POST" and request.url.path == "/v1/audit/search":
                payload = json.loads(request.content.decode())
                assert payload == {"decision": "DENY"}
                return httpx.Response(200, json=[{"id": "audit-2"}])

            if request.method == "GET" and request.url.path == "/v1/org/risk-config":
                return httpx.Response(
                    200,
                    json={"weights": {"sensitive_data": 30}, "thresholds": {"high": 80}},
                )

            if request.method == "PUT" and request.url.path == "/v1/org/risk-config":
                payload = json.loads(request.content.decode())
                assert payload == {"weights": {"sensitive_data": 40}}
                return httpx.Response(
                    200,
                    json={"weights": {"sensitive_data": 40}, "thresholds": {"high": 80}},
                )

            if request.method == "GET" and request.url.path == "/v1/compliance/summary":
                assert request.url.params["period_days"] == "30"
                return httpx.Response(200, json={"period_days": 30, "violations": 0})

            raise AssertionError(f"Unexpected request: {request.method} {request.url}")

        transport = httpx.MockTransport(handler)
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            audits = await client.get_audit_events(
                event_type="evaluation",
                agent_id="agent-1",
                limit=25,
                offset=5,
            )
            searched = await client.search_audit({"decision": "DENY"})
            risk_config = await client.get_risk_config()
            updated_risk_config = await client.update_risk_config(
                {"weights": {"sensitive_data": 40}}
            )
            compliance = await client.get_compliance_summary(period_days=30)

        assert audits[0]["id"] == "audit-1"
        assert searched[0]["id"] == "audit-2"
        assert risk_config["weights"] == {"sensitive_data": 30}
        assert updated_risk_config["weights"] == {"sensitive_data": 40}
        assert compliance["period_days"] == 30

    @pytest.mark.asyncio
    async def test_concurrent_evaluate_reuses_single_client(self):
        seen_agents: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode())
            agent_id = payload["agent_id"]
            seen_agents.append(agent_id)
            return httpx.Response(
                200,
                json={
                    **ALLOW_RESPONSE,
                    "eval_id": f"eval-{agent_id}",
                    "reason": f"Permitted for {agent_id}",
                },
            )

        transport = httpx.MockTransport(handler)
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            results = await asyncio.gather(
                client.evaluate("agent-a", "deploy", "prod"),
                client.evaluate("agent-b", "deploy", "prod"),
                client.evaluate("agent-c", "deploy", "prod"),
            )

        assert sorted(seen_agents) == ["agent-a", "agent-b", "agent-c"]
        assert sorted(result.eval_id for result in results) == [
            "eval-agent-a",
            "eval-agent-b",
            "eval-agent-c",
        ]
