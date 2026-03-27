"""AGR Python SDK — evaluate(), wait_for_approval(), register_agent()."""

import asyncio
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
    risk_score: int | None = None
    risk_level: str | None = None
    risk_factors: dict[str, int] | None = None
    compliance_findings: list[dict[str, object]] | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"

    @property
    def denied(self) -> bool:
        return self.decision == "DENY"

    @property
    def requires_approval(self) -> bool:
        return self.decision == "APPROVAL_REQUIRED"


def _get_required_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if isinstance(value, str):
        return value
    raise AGRError(f"AGR API error: invalid evaluation response missing '{key}'.", status_code=500)


def _get_optional_str(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _get_required_float(data: dict[str, object], key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise AGRError(
            f"AGR API error: invalid evaluation response missing '{key}'.", status_code=500
        )
    return float(value)


def _get_optional_int(data: dict[str, object], key: str) -> int | None:
    value = data.get(key)
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _get_optional_risk_factors(data: dict[str, object]) -> dict[str, int] | None:
    value = data.get("risk_factors")
    if not isinstance(value, dict):
        return None

    normalized: dict[str, int] = {}
    for factor_key, factor_value in value.items():
        if not isinstance(factor_key, str) or isinstance(factor_value, bool):
            return None
        if not isinstance(factor_value, int):
            return None
        normalized[factor_key] = factor_value
    return normalized


def _get_optional_compliance_findings(
    data: dict[str, object],
) -> list[dict[str, object]] | None:
    value = data.get("compliance_findings")
    if not isinstance(value, list):
        return None

    findings: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        findings.append(item)
    return findings


def _parse_evaluation_result(data: dict[str, object]) -> EvaluationResult:
    return EvaluationResult(
        decision=_get_required_str(data, "decision"),
        reason=_get_required_str(data, "reason"),
        policy_id=_get_optional_str(data, "policy_id"),
        approval_id=_get_optional_str(data, "approval_id"),
        latency_ms=_get_required_float(data, "latency_ms"),
        eval_id=_get_required_str(data, "eval_id"),
        risk_score=_get_optional_int(data, "risk_score"),
        risk_level=_get_optional_str(data, "risk_level"),
        risk_factors=_get_optional_risk_factors(data),
        compliance_findings=_get_optional_compliance_findings(data),
    )


def _raise_evaluate_error(response: httpx.Response) -> None:
    if response.status_code == 401:
        data = response.json()
        if isinstance(data, dict):
            message = data.get(
                "message",
                "Unauthorized. Check your API key at https://dashboard.agr.dev/settings",
            )
            raise AGRAuthError(str(message), status_code=401)
        raise AGRAuthError(
            "Unauthorized. Check your API key at https://dashboard.agr.dev/settings",
            status_code=401,
        )

    if response.status_code == 429:
        data = response.json()
        if isinstance(data, dict):
            upgrade_url = data.get("upgrade_url")
            raise AGRRateLimitError(
                message=str(data.get("message", "Rate limit exceeded.")),
                upgrade_url=str(upgrade_url) if isinstance(upgrade_url, str) else None,
            )
        raise AGRRateLimitError(message="Rate limit exceeded.")

    raise AGRError(
        f"AGR API error ({response.status_code}): {response.text}",
        status_code=response.status_code,
    )


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
        if response.status_code >= 400:
            _raise_evaluate_error(response)

        data = response.json()
        if not isinstance(data, dict):
            raise AGRError("AGR API error: invalid evaluation response.", status_code=500)
        return _parse_evaluation_result(data)

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

    def import_policies(
        self,
        *,
        policies: list[dict[str, object]] | None = None,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> dict[str, object]:
        """Bulk-import policies from a list of PolicyImportItem dicts.

        Each item must have: name (str), level (str), cedar_rule (str).
        Optional: active (bool), agent_id (str), project_id (str).

        Returns a PolicyImportResponse dict with keys: dry_run, total,
        created, updated, skipped, errors, results.
        """
        if not policies:
            raise AGRError("policies list is required and must not be empty.")
        body: dict[str, object] = {
            "policies": policies,
            "overwrite": overwrite,
            "dry_run": dry_run,
        }
        response = self._client.post("/v1/policies/import", json=body)
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to import policies ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    def export_policies(self, *, active_only: bool = True) -> list[dict[str, object]]:
        """Export all org policies as a list of PolicyImportItem dicts.

        Suitable for backup or re-import via import_policies().
        """
        response = self._client.get(
            "/v1/policies/export",
            params={"active_only": str(active_only).lower()},
        )
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to export policies ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    # ── Audit ──────────────────────────────────────────────────────────────────

    def get_audit_events(
        self,
        *,
        event_type: str | None = None,
        agent_id: str | None = None,
        action: str | None = None,
        resource: str | None = None,
        decision: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        """Fetch audit events with optional filters."""
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        for k, v in {
            "event_type": event_type,
            "agent_id": agent_id,
            "action": action,
            "resource": resource,
            "decision": decision,
            "start_date": start_date,
            "end_date": end_date,
        }.items():
            if v is not None:
                params[k] = v
        response = self._client.get("/v1/audit", params=params)
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to fetch audit events ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    def search_audit(self, filters: dict[str, object]) -> list[dict[str, object]]:
        """POST /v1/audit/search — structured filter query."""
        response = self._client.post("/v1/audit/search", json=filters)
        if response.status_code >= 400:
            raise AGRError(
                f"Audit search failed ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    # ── Risk config ────────────────────────────────────────────────────────────

    def get_risk_config(self) -> dict[str, object]:
        """Return current per-org risk scoring configuration."""
        response = self._client.get("/v1/org/risk-config")
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to get risk config ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    def update_risk_config(self, updates: dict[str, object]) -> dict[str, object]:
        """Update per-org risk scoring weights and thresholds."""
        response = self._client.put("/v1/org/risk-config", json=updates)
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to update risk config ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    # ── Compliance ─────────────────────────────────────────────────────────────

    def get_compliance_summary(self, period_days: int = 7) -> dict[str, object]:
        """Return aggregated compliance posture for the last N days."""
        response = self._client.get("/v1/compliance/summary", params={"period_days": period_days})
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to get compliance summary ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AGRClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncAGRClient:
    """Async version of AGRClient for use in async frameworks (LangGraph, CrewAI, etc.).

    Usage:
        async with AsyncAGRClient(api_key="agr_sk_...") as client:
            result = await client.evaluate("agent", "deploy", "prod")
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.agr.dev",
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("AGR_API_KEY", "")
        if not self.api_key:
            raise AGRError(
                "API key is required. Pass api_key or set AGR_API_KEY environment variable."
            )
        self.base_url = base_url.rstrip("/")
        kwargs: dict[str, object] = {
            "base_url": self.base_url,
            "headers": {"Authorization": f"Bearer {self.api_key}"},
            "timeout": timeout,
        }
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.AsyncClient(**kwargs)  # type: ignore[arg-type]

    async def evaluate(
        self,
        agent: str,
        action: str,
        resource: str,
        context: dict[str, object] | None = None,
    ) -> EvaluationResult:
        """Evaluate an agent action against Cedar policies (async).

        Raises AGRAuthError on 401, AGRRateLimitError on 429, AGRError on other failures.
        """
        payload = {
            "agent_id": agent,
            "action": action,
            "resource": resource,
            "context": context or {},
        }
        response = await self._client.post("/v1/evaluate", json=payload)
        if response.status_code >= 400:
            _raise_evaluate_error(response)

        data = response.json()
        if not isinstance(data, dict):
            raise AGRError("AGR API error: invalid evaluation response.", status_code=500)
        return _parse_evaluation_result(data)

    async def wait_for_approval(
        self,
        approval_id: str,
        poll_interval: float = 2.0,
        timeout: float = 3600.0,
    ) -> bool:
        """Wait for an approval decision (async). Returns True if approved, False if rejected."""
        start = time.monotonic()
        while True:
            if time.monotonic() - start >= timeout:
                raise TimeoutError(f"Approval {approval_id} not resolved within {timeout}s.")

            response = await self._client.get(f"/v1/approvals/{approval_id}")
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

            await asyncio.sleep(poll_interval)

    async def register_agent(
        self, agent_id: str, metadata: dict[str, object] | None = None
    ) -> dict[str, object]:
        """Register an agent with AGR (async)."""
        payload = {"agent_id": agent_id, "metadata": metadata or {}}
        response = await self._client.post("/v1/agents/register", json=payload)
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to register agent ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    async def import_policies(
        self,
        *,
        policies: list[dict[str, object]] | None = None,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> dict[str, object]:
        """Bulk-import policies from a list of PolicyImportItem dicts (async)."""
        if not policies:
            raise AGRError("policies list is required and must not be empty.")
        body: dict[str, object] = {
            "policies": policies,
            "overwrite": overwrite,
            "dry_run": dry_run,
        }
        response = await self._client.post("/v1/policies/import", json=body)
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to import policies ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    async def export_policies(self, *, active_only: bool = True) -> list[dict[str, object]]:
        """Export all org policies as a list of PolicyImportItem dicts (async)."""
        response = await self._client.get(
            "/v1/policies/export",
            params={"active_only": str(active_only).lower()},
        )
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to export policies ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    async def get_audit_events(
        self,
        *,
        event_type: str | None = None,
        agent_id: str | None = None,
        action: str | None = None,
        resource: str | None = None,
        decision: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        """Fetch audit events with optional filters (async)."""
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        for k, v in {
            "event_type": event_type,
            "agent_id": agent_id,
            "action": action,
            "resource": resource,
            "decision": decision,
            "start_date": start_date,
            "end_date": end_date,
        }.items():
            if v is not None:
                params[k] = v
        response = await self._client.get("/v1/audit", params=params)
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to fetch audit events ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    async def search_audit(self, filters: dict[str, object]) -> list[dict[str, object]]:
        """POST /v1/audit/search — structured filter query (async)."""
        response = await self._client.post("/v1/audit/search", json=filters)
        if response.status_code >= 400:
            raise AGRError(
                f"Audit search failed ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    async def get_risk_config(self) -> dict[str, object]:
        """Return current per-org risk scoring configuration (async)."""
        response = await self._client.get("/v1/org/risk-config")
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to get risk config ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    async def update_risk_config(self, updates: dict[str, object]) -> dict[str, object]:
        """Update per-org risk scoring weights and thresholds (async)."""
        response = await self._client.put("/v1/org/risk-config", json=updates)
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to update risk config ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    async def get_compliance_summary(self, period_days: int = 7) -> dict[str, object]:
        """Return aggregated compliance posture for the last N days (async)."""
        response = await self._client.get(
            "/v1/compliance/summary",
            params={"period_days": period_days},
        )
        if response.status_code >= 400:
            raise AGRError(
                f"Failed to get compliance summary ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.json()  # type: ignore[no-any-return]

    async def close(self) -> None:
        await self._client.aclose()

    async def aclose(self) -> None:
        await self.close()

    async def __aenter__(self) -> "AsyncAGRClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
