"""Unit tests for the AGR Python SDK client."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "agr-sdk-python"))
from agr.client import AGRAuthError, AGRClient, AGRError, AGRRateLimitError, EvaluationResult


class TestEvaluationResult:
    def test_allowed_property(self) -> None:
        r = EvaluationResult("ALLOW", "ok", None, None, 0.5, "e1")
        assert r.allowed is True
        assert r.denied is False
        assert r.requires_approval is False

    def test_denied_property(self) -> None:
        r = EvaluationResult("DENY", "blocked", "p1", None, 0.5, "e1")
        assert r.denied is True
        assert r.allowed is False

    def test_requires_approval_property(self) -> None:
        r = EvaluationResult("APPROVAL_REQUIRED", "needs review", "p1", "a1", 0.5, "e1")
        assert r.requires_approval is True
        assert r.allowed is False
        assert r.denied is False


class TestAGRClient:
    def test_init_requires_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(AGRError, match="API key is required"):
                AGRClient(api_key="")

    def test_init_with_api_key(self) -> None:
        client = AGRClient(api_key="agr_sk_test123", base_url="http://localhost:8000")
        assert client.api_key == "agr_sk_test123"
        client.close()

    def test_init_from_env_var(self) -> None:
        with patch.dict("os.environ", {"AGR_API_KEY": "agr_sk_env123"}):
            client = AGRClient(base_url="http://localhost:8000")
            assert client.api_key == "agr_sk_env123"
            client.close()

    def test_evaluate_success(self) -> None:
        client = AGRClient(api_key="agr_sk_test", base_url="http://localhost:8000")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "decision": "ALLOW",
            "reason": "Allowed by policy",
            "policy_id": "p1",
            "approval_id": None,
            "latency_ms": 0.5,
            "eval_id": "e1",
        }
        client._client.post = MagicMock(return_value=mock_response)

        result = client.evaluate("agent-1", "deploy", "staging-server")
        assert result.decision == "ALLOW"
        assert result.allowed is True
        client.close()

    def test_evaluate_401_raises_auth_error(self) -> None:
        client = AGRClient(api_key="agr_sk_test", base_url="http://localhost:8000")
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"message": "Invalid key"}
        client._client.post = MagicMock(return_value=mock_response)

        with pytest.raises(AGRAuthError):
            client.evaluate("agent-1", "deploy", "server")
        client.close()

    def test_evaluate_429_raises_rate_limit_error(self) -> None:
        client = AGRClient(api_key="agr_sk_test", base_url="http://localhost:8000")
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.json.return_value = {
            "message": "Limit exceeded",
            "upgrade_url": "https://agr.dev/pricing",
        }
        client._client.post = MagicMock(return_value=mock_response)

        with pytest.raises(AGRRateLimitError) as exc_info:
            client.evaluate("agent-1", "deploy", "server")
        assert exc_info.value.upgrade_url == "https://agr.dev/pricing"
        client.close()

    def test_evaluate_500_raises_agr_error(self) -> None:
        client = AGRClient(api_key="agr_sk_test", base_url="http://localhost:8000")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        client._client.post = MagicMock(return_value=mock_response)

        with pytest.raises(AGRError):
            client.evaluate("agent-1", "deploy", "server")
        client.close()

    def test_context_manager(self) -> None:
        with AGRClient(api_key="agr_sk_test", base_url="http://localhost:8000") as client:
            assert client.api_key == "agr_sk_test"
