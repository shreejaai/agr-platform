"""Tests for AsyncAGRClient.

Uses httpx.MockTransport to avoid real HTTP calls.
"""

import pytest
import httpx

from agr.client import AsyncAGRClient, AGRError, AGRAuthError, AGRRateLimitError


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


class TestAsyncAGRClientMisconfiguration:
    def test_raises_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("AGR_API_KEY", raising=False)
        with pytest.raises(AGRError, match="API key is required"):
            AsyncAGRClient(api_key="")
