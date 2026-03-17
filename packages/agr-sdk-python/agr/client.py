"""AGR Python SDK — evaluate(), wait_for_approval(), register_agent()."""

import logging
import os
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


class AGRError(Exception):
    """Base exception for AGR SDK errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AGRAuthError(AGRError):
    """Raised on 401 Unauthorized."""

    pass


class AGRRateLimitError(AGRError):
    """Raised on 429 Too Many Requests."""

    def __init__(self, message: str, upgrade_url: str | None = None) -> None:
        self.upgrade_url = upgrade_url
        super().__init__(message, status_code=429)


@dataclass
class EvaluationResult:
    decision: str
    reason: str
    policy_id: str | None
    approval_id: str | None
    latency_ms: float
    eval_id: str

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"

    @property
    def denied(self) -> bool:
        return self.decision == "DENY"

    @property
    def requires_approval(self) -> bool:
        return self.decision == "APPROVAL_REQUIRED"


class AGRClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.agr.dev",
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("AGR_API_KEY", "")
        if not self.api_key:
            raise AGRError(
                "API key is required. Pass api_key or set AGR_API_KEY environment variable."
            )
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=timeout,
        )

    def evaluate(
        self,
        agent: str,
        action: str,
        resource: str,
        context: dict[str, object] | None = None,
    ) -> EvaluationResult:
        """Evaluate an agent action against Cedar policies.

        Raises AGRAuthError on 401, AGRRateLimitError on 429, AGRError on other failures.
        """
        payload = {
            "agent_id": agent,
            "action": action,
            "resource": resource,
            "context": context or {},
        }
        response = self._client.post("/v1/evaluate", json=payload)

        if response.status_code == 401:
            data = response.json()
            raise AGRAuthError(
                data.get(
                    "message",
                    "Unauthorized. Check your API key at https://dashboard.agr.dev/settings",
                ),
                status_code=401,
            )

        if response.status_code == 429:
            data = response.json()
            raise AGRRateLimitError(
                message=data.get("message", "Rate limit exceeded."),
                upgrade_url=data.get("upgrade_url"),
            )

        if response.status_code >= 400:
            raise AGRError(
                f"AGR API error ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )

        data = response.json()
        return EvaluationResult(
            decision=data["decision"],
            reason=data["reason"],
            policy_id=data.get("policy_id"),
            approval_id=data.get("approval_id"),
            latency_ms=data["latency_ms"],
            eval_id=data["eval_id"],
        )

    def wait_for_approval(
        self,
        approval_id: str,
        poll_interval: float = 2.0,
        timeout: float = 3600.0,
    ) -> bool:
        """Wait for an approval decision. Returns True if approved, False if rejected.

        Raises TimeoutError if the approval is not resolved within the timeout.
        Raises AGRError on unexpected API failures.
        """
        start = time.monotonic()
        while True:
            if time.monotonic() - start >= timeout:
                raise TimeoutError(f"Approval {approval_id} not resolved within {timeout}s.")

            response = self._client.get(f"/v1/approvals/{approval_id}")
            if response.status_code == 200:
                status = response.json().get("status")
                if status == "approved":
                    return True
                if status == "rejected":
                    return False
            elif response.status_code >= 400:
                raise AGRError(
                    f"AGR API error ({response.status_code}): {response.text}",
                    status_code=response.status_code,
                )

            time.sleep(poll_interval)

    def register_agent(
        self, agent_id: str, metadata: dict[str, object] | None = None
    ) -> dict[str, object]:
        """Register an agent with AGR."""
        payload = {"agent_id": agent_id, "metadata": metadata or {}}
        response = self._client.post("/v1/agents/register", json=payload)
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to register agent ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AGRClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
