"""Tests for sync/async framework integration helpers."""

import json

import httpx
import pytest
from agr import AGRClient, AGRError, AsyncAGRClient
from agr.integrations import AGRPolicyEnforcer, AsyncAGRPolicyEnforcer

ALLOW_RESPONSE = {
    "decision": "ALLOW",
    "reason": "Permitted by policy.",
    "policy_id": "policy-allow",
    "approval_id": None,
    "latency_ms": 12.5,
    "eval_id": "eval-allow",
    "risk_score": 10,
    "risk_level": "low",
    "risk_factors": {"action_severity": 10},
    "compliance_findings": [],
}

DENY_RESPONSE = {
    **ALLOW_RESPONSE,
    "decision": "DENY",
    "reason": "Blocked by policy.",
}

APPROVAL_RESPONSE = {
    **ALLOW_RESPONSE,
    "decision": "APPROVAL_REQUIRED",
    "approval_id": "approval-123",
    "reason": "Review required.",
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


def test_sync_client_simulate_uses_simulation_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/policies/simulate"
        payload = json.loads(request.content.decode())
        assert payload == {
            "agent_id": "agent-1",
            "action": "deploy",
            "resource": "prod-cluster",
            "context": {"environment": "production"},
        }
        return httpx.Response(200, json=SIMULATE_RESPONSE)

    client = AGRClient(
        api_key="agr_sk_test",
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.simulate(
            "agent-1",
            "deploy",
            "prod-cluster",
            {"environment": "production"},
        )
    finally:
        client.close()

    assert result.requires_approval is True
    assert result.decision_trace is not None
    assert result.decision_trace.risk_override is True


def test_sync_enforcer_wraps_callable_and_merges_context() -> None:
    captured_context: dict[str, object] | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_context
        payload = json.loads(request.content.decode())
        captured_context = payload["context"]
        return httpx.Response(200, json=ALLOW_RESPONSE)

    client = AGRClient(
        api_key="agr_sk_test",
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    )
    enforcer = AGRPolicyEnforcer(client, "agent-1", default_context={"framework": "generic"})

    @enforcer.wrap(resource="internet", context=lambda query: {"query": query})
    def search(query: str) -> str:
        return f"search:{query}"

    try:
        result = search("billing export")
    finally:
        client.close()

    assert result == "search:billing export"
    assert captured_context == {"framework": "generic", "query": "billing export"}


def test_sync_enforcer_raises_on_deny() -> None:
    client = AGRClient(
        api_key="agr_sk_test",
        base_url="http://test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=DENY_RESPONSE)),
    )
    enforcer = AGRPolicyEnforcer(client, "agent-1")

    @enforcer.wrap()
    def delete_file(path: str) -> str:
        return path

    try:
        with pytest.raises(AGRError, match="denied by AGR policy"):
            delete_file("/tmp/secrets.txt")
    finally:
        client.close()


def test_sync_enforcer_waits_for_approval_before_execution() -> None:
    requests_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request.url.path)
        if request.url.path == "/v1/evaluate":
            return httpx.Response(200, json=APPROVAL_RESPONSE)
        if request.url.path == "/v1/approvals/approval-123":
            return httpx.Response(200, json={"status": "approved"})
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    client = AGRClient(
        api_key="agr_sk_test",
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    )
    enforcer = AGRPolicyEnforcer(client, "agent-1")

    @enforcer.wrap()
    def deploy(target: str) -> str:
        return f"deployed:{target}"

    try:
        result = deploy("prod")
    finally:
        client.close()

    assert result == "deployed:prod"
    assert requests_seen == ["/v1/evaluate", "/v1/approvals/approval-123"]


@pytest.mark.asyncio
async def test_async_enforcer_wraps_async_callable() -> None:
    captured_context: dict[str, object] | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_context
        payload = json.loads(request.content.decode())
        captured_context = payload["context"]
        return httpx.Response(200, json=ALLOW_RESPONSE)

    async with AsyncAGRClient(
        api_key="agr_sk_test",
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    ) as client:
        enforcer = AsyncAGRPolicyEnforcer(
            client,
            "agent-async",
            default_context={"framework": "async-generic"},
        )

        @enforcer.wrap(
            resource=lambda query: f"search:{query}",
            context=lambda query: {"query": query},
        )
        async def search(query: str) -> str:
            return query.upper()

        result = await search("slack approvals")

    assert result == "SLACK APPROVALS"
    assert captured_context == {"framework": "async-generic", "query": "slack approvals"}
