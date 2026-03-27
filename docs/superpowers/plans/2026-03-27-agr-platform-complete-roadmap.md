# AGR Platform — Complete Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Systematically close all product gaps across 4 waves, making AGR enterprise-ready: Cedar policy enforcement verified end-to-end, async SDK for LangGraph/CrewAI, self-serve API docs, team management, dashboard UX completeness, compliance tooling, and ecosystem integrations.

**Architecture:** FastAPI backend (`services/agr-api/`) + Angular 17 dashboard (`apps/agr-dashboard/`) + Python SDK (`packages/agr-sdk-python/`) + Core engine (`packages/agr-core/`). Each wave produces independently deployable, tested software. Never cross module boundaries unless an API contract change forces it.

**Tech Stack:** FastAPI 0.115 / Python 3.12 / SQLAlchemy 2.0 async / PostgreSQL 16 / Angular 17 standalone / Tailwind / httpx / Cedar CLI (cargo) / Resend / Temporal

---

## Parallel Execution Strategy

This plan uses two execution patterns:

### Pattern A — Parallel Dispatch (independent subsystems)
Multiple agents run simultaneously when tasks touch different packages with no shared files.

### Pattern B — Sequential Pipeline (shared file dependency)
Tasks that both modify `schemas.py`, `models.py`, or routing files must run in order.

### Wave 1 Dependency Graph

```
START ──────────────────────────────────────────────►
         │                                          │
         ├──► [Task A1] Cedar CLI Tests + CI        │ (independent: packages/agr-core + CI)
         │                                          │
         ├──► [Task B1] Async Python SDK            │ (independent: packages/agr-sdk-python)
         │                                          │
         ├──► [Task D1] Policy Simulator UI         │ (independent: apps/agr-dashboard)
         │                                          │
         ├──► [Task D2] Eval Usage Meter            │ (independent: apps/agr-dashboard)
         │                                          │
         └──► [Task C1] OpenAPI Enrichment          │ (touches schemas.py)
                    │                               │
                    └──► [Task C2] Team Invite API  │ (touches schemas.py — MUST follow C1)
                                   │                │
                                   └──► [Task D3] Team Invite UI
```

**Recommended dispatch:** Run A1 + B1 + D1 + D2 + C1 simultaneously. When C1 completes, dispatch C2. When C2 completes, dispatch D3. Total wall-clock time ≈ max(A1, B1, D1, D2, C1) + C2 + D3.

---

## Wave 1 — Full Detail (Next 2–4 weeks)

Fix what blocks customer evaluation. Every task below is TDD: write the failing test first.

---

### Task A1: Cedar CLI — Test Coverage + CI Integration

**Module:** `packages/agr-core` + `.github/workflows/ci.yml`
**Can run in parallel with:** B1, C1, D1, D2

**Files:**
- Create: `packages/agr-core/tests/test_cedar_cli.py`
- Modify: `.github/workflows/ci.yml` (add `test-cedar-cli` job)

**Context:** `policy_engine.py` has a complete Cedar CLI path (`_cedar_cli_evaluator`) but zero tests exercise it. CI runs tests without Cedar installed. The `cedar authorize` command outputs `ALLOW` or `DENY` on stdout. The current output parser does `proc.stdout.strip()` → checks `if output in ("ALLOW", "DENY")` — this is correct for cedar-policy CLI v2/v3.

---

- [ ] **Step A1-1: Install Cedar CLI locally**

```bash
# macOS — either works
brew install cedar-policy/tap/cedar || cargo install cedar-policy-cli

# Verify
cedar --version
which cedar   # should print a path, not empty
```

Expected: `cedar 3.x.x` (or similar). If brew fails, cargo will take 2–5 minutes to compile.

- [ ] **Step A1-2: Write the test file (all tests failing at this point)**

Create `packages/agr-core/tests/test_cedar_cli.py`:

```python
"""Tests for the Cedar CLI evaluation path in policy_engine.py.

These tests are skipped automatically when the `cedar` binary is not on PATH.
CI job `test-cedar-cli` installs Cedar before running this file.
"""

import pytest
import shutil

from policy_engine import (
    _find_cedar_cli,
    _cedar_cli_authorize,
    _cedar_cli_evaluator,
    evaluate_policies,
)

cedar_required = pytest.mark.skipif(
    shutil.which("cedar") is None,
    reason="cedar CLI not installed — skipped in dev/CI without cedar job",
)


PERMIT_ALL_POLICY = {
    "id": "p1",
    "cedar_rule": 'permit(principal, action, resource);',
}

DENY_DEPLOY_POLICY = {
    "id": "p2",
    "cedar_rule": 'forbid(principal, action == Action::"deploy", resource);',
}

APPROVAL_REQUIRED_POLICY = {
    "id": "p3",
    "cedar_rule": (
        'forbid(principal, action == Action::"deploy", resource) '
        'unless { context.approval_status == "approved" };'
    ),
}


@cedar_required
class TestFindCedarCli:
    def test_returns_path_when_installed(self):
        path = _find_cedar_cli()
        assert path is not None
        assert "cedar" in path


@cedar_required
class TestCedarCliAuthorize:
    def test_permit_all_allows(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_authorize(cedar, [PERMIT_ALL_POLICY], "agent1", "read", "db", {})
        assert result == "ALLOW"

    def test_deny_deploy_blocks(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_authorize(cedar, [DENY_DEPLOY_POLICY], "agent1", "deploy", "prod", {})
        assert result == "DENY"

    def test_no_matching_policy_denies(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_authorize(cedar, [DENY_DEPLOY_POLICY], "agent1", "read", "db", {})
        # forbid only matches deploy — read should pass but no permit → DENY by default
        assert result == "DENY"

    def test_permit_with_context(self):
        cedar = _find_cedar_cli()
        policy = {
            "id": "p4",
            "cedar_rule": 'permit(principal, action, resource) when { context.env == "staging" };',
        }
        result = _cedar_cli_authorize(cedar, [policy], "a1", "read", "db", {"env": "staging"})
        assert result == "ALLOW"

    def test_permit_with_wrong_context_denies(self):
        cedar = _find_cedar_cli()
        policy = {
            "id": "p4",
            "cedar_rule": 'permit(principal, action, resource) when { context.env == "staging" };',
        }
        result = _cedar_cli_authorize(cedar, [policy], "a1", "read", "db", {"env": "prod"})
        assert result == "DENY"


@cedar_required
class TestCedarCliEvaluator:
    def test_allow_decision(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_evaluator(cedar, [PERMIT_ALL_POLICY], "a1", "read", "db", {})
        assert result.decision == "ALLOW"
        assert result.policy_source == "cedar_cli"
        assert result.requires_approval is False

    def test_deny_decision(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_evaluator(cedar, [DENY_DEPLOY_POLICY], "a1", "deploy", "prod", {})
        assert result.decision == "DENY"
        assert result.policy_source == "cedar_cli"
        assert result.requires_approval is False

    def test_approval_required_detected(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_evaluator(
            cedar, [APPROVAL_REQUIRED_POLICY], "a1", "deploy", "prod", {}
        )
        assert result.decision == "APPROVAL_REQUIRED"
        assert result.policy_source == "cedar_cli"
        assert result.requires_approval is True

    def test_approval_required_with_status_approved_allows(self):
        cedar = _find_cedar_cli()
        result = _cedar_cli_evaluator(
            cedar,
            [APPROVAL_REQUIRED_POLICY],
            "a1",
            "deploy",
            "prod",
            {"approval_status": "approved"},
        )
        assert result.decision == "ALLOW"
        assert result.policy_source == "cedar_cli"


@cedar_required
class TestEvaluatePoliciesIntegration:
    def test_uses_cedar_cli_when_available(self):
        result = evaluate_policies(
            [PERMIT_ALL_POLICY], "agent1", "read", "db", {}
        )
        assert result.decision == "ALLOW"
        # When cedar is installed, policy_source must be cedar_cli
        assert result.policy_source == "cedar_cli"
```

- [ ] **Step A1-3: Run tests to confirm they are collected (or skipped if cedar not found)**

```bash
cd packages/agr-core
python -m pytest tests/test_cedar_cli.py -v
```

If cedar is installed: tests should FAIL (not yet — actually they import from `policy_engine` which is in the parent package, so make sure the import path is correct). If cedar is not installed: all tests should be skipped.

Note: `policy_engine.py` is at `packages/agr-core/policy_engine.py`. Run from that directory or add `sys.path` fixture. Simplest: run from `packages/agr-core/`.

- [ ] **Step A1-4: Fix import if needed — check how existing tests import policy_engine**

```bash
ls packages/agr-core/tests/
cat packages/agr-core/tests/test_policy_engine.py | head -10
```

If existing tests use `from policy_engine import ...` directly, the import in A1-2 is correct. If they use a package path, update accordingly.

- [ ] **Step A1-5: Run tests with cedar installed — all should PASS**

```bash
cd packages/agr-core
python -m pytest tests/test_cedar_cli.py -v
```

Expected: All `TestCedarCliAuthorize` and `TestCedarCliEvaluator` tests PASS. If any fail, check the cedar output format:

```bash
cedar authorize \
  --policies /tmp/test.cedar \
  --entities /tmp/test_entities.json \
  --request-json '{"principal":{"type":"Agent","id":"a1"},"action":{"type":"Action","id":"read"},"resource":{"type":"Resource","id":"db"},"context":{}}'
```

If the output is not exactly `ALLOW` or `DENY` (e.g., includes extra text like `Decision: ALLOW`), update `_cedar_cli_authorize` in `policy_engine.py`:

```python
# Replace the output check in _cedar_cli_authorize:
output = proc.stdout.strip()
# cedar v3+ may output "Decision: ALLOW" — normalize
if "ALLOW" in output:
    return "ALLOW"
if "DENY" in output:
    return "DENY"
raise RuntimeError(
    f"Unexpected cedar output: stdout={proc.stdout!r} stderr={proc.stderr!r} "
    f"exit={proc.returncode}"
)
```

- [ ] **Step A1-6: Add `test-cedar-cli` job to CI**

Edit `.github/workflows/ci.yml` — add this job after the `test-python-sdk` job:

```yaml
  test-cedar-cli:
    name: Cedar CLI — policy engine tests
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4.2.2

      - name: Set up Python
        uses: actions/setup-python@v5.6.0
        with:
          python-version: "3.12"

      - name: Install Rust + Cedar CLI
        uses: dtolnay/rust-toolchain@stable

      - name: Cache cargo registry
        uses: actions/cache@v4
        with:
          path: |
            ~/.cargo/registry
            ~/.cargo/git
            ~/.cargo/bin/cedar
          key: cedar-cli-${{ runner.os }}-${{ hashFiles('**/Cargo.lock') }}
          restore-keys: cedar-cli-${{ runner.os }}-

      - name: Install cedar-policy-cli
        run: |
          if ! command -v cedar &> /dev/null; then
            cargo install cedar-policy-cli --locked
          fi
          cedar --version

      - name: Install Python test dependencies
        run: pip install pytest

      - name: Run Cedar CLI tests
        run: |
          cd packages/agr-core
          python -m pytest tests/test_cedar_cli.py -v
```

Also update the `publish` job's `needs` to include `test-cedar-cli`:

```yaml
    needs: [lint-and-test, build-dashboard, test-ts-sdk, test-cedar-cli]
```

- [ ] **Step A1-7: Commit**

```bash
git add packages/agr-core/tests/test_cedar_cli.py .github/workflows/ci.yml
git commit -m "test(cedar): add Cedar CLI test suite and CI job

- 8 tests covering _cedar_cli_authorize, _cedar_cli_evaluator, evaluate_policies
- All tests skip when cedar binary not found (safe in local dev)
- New test-cedar-cli CI job: installs Rust + cedar-policy-cli via cargo
- Cargo cache keyed on Cargo.lock to speed up subsequent runs

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task B1: Async Python SDK — AsyncAGRClient

**Module:** `packages/agr-sdk-python`
**Can run in parallel with:** A1, C1, D1, D2

**Files:**
- Modify: `packages/agr-sdk-python/agr/client.py` (add `AsyncAGRClient`)
- Modify: `packages/agr-sdk-python/agr/__init__.py` (export `AsyncAGRClient`)
- Create: `packages/agr-sdk-python/tests/test_async_client.py`

**Context:** `AGRClient` uses `httpx.Client` (sync). `AsyncAGRClient` will use `httpx.AsyncClient` with identical method signatures but `async def` + `await`. Required for LangGraph and CrewAI which run inside async event loops.

---

- [ ] **Step B1-1: Write the failing async tests**

Create `packages/agr-sdk-python/tests/test_async_client.py`:

```python
"""Tests for AsyncAGRClient.

Uses httpx.MockTransport to avoid real HTTP calls.
"""

import pytest
import json
import httpx

from agr.client import AsyncAGRClient, AGRError, AGRAuthError, AGRRateLimitError, EvaluationResult


def _make_transport(responses: list[tuple[int, dict]]):
    """Build a MockTransport that returns responses in order."""
    resp_iter = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        status, body = next(resp_iter)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


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
        # Always return pending
        def handler(request):
            return httpx.Response(200, json={"status": "pending"})
        transport = httpx.MockTransport(handler)
        async with AsyncAGRClient(
            api_key="agr_sk_test", base_url="http://test", transport=transport
        ) as client:
            with pytest.raises(TimeoutError):
                await client.wait_for_approval("appr-1", poll_interval=0.01, timeout=0.05)


class TestAsyncAGRClientMisconfiguration:
    @pytest.mark.asyncio
    async def test_raises_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("AGR_API_KEY", raising=False)
        with pytest.raises(AGRError, match="API key is required"):
            AsyncAGRClient(api_key="")
```

- [ ] **Step B1-2: Run tests to confirm they fail (AsyncAGRClient not yet defined)**

```bash
cd packages/agr-sdk-python
pip install pytest pytest-asyncio httpx
python -m pytest tests/test_async_client.py -v
```

Expected: `ImportError: cannot import name 'AsyncAGRClient'`

- [ ] **Step B1-3: Add AsyncAGRClient to client.py**

In `packages/agr-sdk-python/agr/client.py`, add after the `AGRClient` class closing (after line 316):

```python
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
        transport: object | None = None,
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
            risk_score=data.get("risk_score"),
            risk_level=data.get("risk_level"),
            risk_factors=data.get("risk_factors"),
            compliance_findings=data.get("compliance_findings"),
        )

    async def wait_for_approval(
        self,
        approval_id: str,
        poll_interval: float = 2.0,
        timeout: float = 3600.0,
    ) -> bool:
        """Wait for an approval decision (async). Returns True if approved, False if rejected."""
        import asyncio

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

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncAGRClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
```

- [ ] **Step B1-4: Export AsyncAGRClient from `agr/__init__.py`**

Read the current `__init__.py`:
```bash
cat packages/agr-sdk-python/agr/__init__.py
```

Add `AsyncAGRClient` to the imports and `__all__`. If the file currently contains:
```python
from agr.client import AGRClient, AGRError, AGRAuthError, AGRRateLimitError, EvaluationResult
```

Change it to:
```python
from agr.client import (
    AGRClient,
    AsyncAGRClient,
    AGRError,
    AGRAuthError,
    AGRRateLimitError,
    EvaluationResult,
)

__all__ = [
    "AGRClient",
    "AsyncAGRClient",
    "AGRError",
    "AGRAuthError",
    "AGRRateLimitError",
    "EvaluationResult",
]
```

- [ ] **Step B1-5: Add `pytest-asyncio` to SDK dev dependencies**

In `packages/agr-sdk-python/setup.py`, find the `extras_require` or `install_requires` section. Add `pytest-asyncio` to the test extras. If the file doesn't have extras, add:

```python
extras_require={
    "dev": ["pytest", "pytest-asyncio", "httpx"],
},
```

Also create `packages/agr-sdk-python/pytest.ini` (or `pyproject.toml` section) with:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step B1-6: Run tests — all should PASS**

```bash
cd packages/agr-sdk-python
pip install -e ".[dev]"
python -m pytest tests/test_async_client.py -v
```

Expected: All 11 tests PASS.

- [ ] **Step B1-7: Type-check**

```bash
cd packages/agr-sdk-python
python -m mypy agr/ --ignore-missing-imports --config-file=/dev/null
```

Expected: 0 errors.

- [ ] **Step B1-8: Update CI to run async SDK tests**

In `.github/workflows/ci.yml`, find the `test-python-sdk` job. Add test execution:

```yaml
      - name: Install dependencies
        run: pip install -e packages/agr-sdk-python httpx ruff mypy pytest pytest-asyncio

      - name: Lint
        run: ruff check packages/agr-sdk-python/

      - name: Type-check
        run: python -m mypy packages/agr-sdk-python/agr/ --ignore-missing-imports --config-file=/dev/null

      - name: Test async client
        run: |
          cd packages/agr-sdk-python
          python -m pytest tests/ -v
```

- [ ] **Step B1-9: Commit**

```bash
git add packages/agr-sdk-python/agr/client.py \
        packages/agr-sdk-python/agr/__init__.py \
        packages/agr-sdk-python/tests/test_async_client.py \
        packages/agr-sdk-python/pytest.ini \
        packages/agr-sdk-python/setup.py \
        .github/workflows/ci.yml
git commit -m "feat(sdk): add AsyncAGRClient for LangGraph/CrewAI async contexts

- AsyncAGRClient mirrors AGRClient with async def + httpx.AsyncClient
- Supports context manager protocol (async with)
- 11 tests covering evaluate, wait_for_approval, error handling, timeout
- CI test-python-sdk job now runs async tests via pytest-asyncio

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task C1: OpenAPI Schema Enrichment + Export

**Module:** `services/agr-api`
**Must run BEFORE C2** (both modify `schemas.py`)
**Can run in parallel with:** A1, B1, D1, D2

**Files:**
- Modify: `services/agr-api/app/schemas.py` (add Field descriptions + examples)
- Modify: `services/agr-api/app/main.py` (OpenAPI metadata, contact, tags)
- Modify: `services/agr-api/app/routes/evaluate.py` (add tags + summary)
- Modify: `services/agr-api/app/routes/policies.py` (add tags + summary)
- Modify: `services/agr-api/app/routes/approvals.py` (add tags + summary)
- Create: `scripts/export_openapi.py`

**Context:** FastAPI auto-generates OpenAPI at `/docs` and `/openapi.json`. The app already has `title`, `description`, `version`. Schemas lack `Field` descriptions. Routes lack `tags`. Adding these gives developers a browsable, self-documenting API with no schema changes.

---

- [ ] **Step C1-1: Add OpenAPI metadata and tags to main.py**

In `services/agr-api/app/main.py`, find the `app = FastAPI(...)` block (line 104) and replace with:

```python
app = FastAPI(
    title="AGR — Agentic Governance Runtime",
    description=(
        "Drop-in governance layer for AI agent frameworks. "
        "Every agent tool call is evaluated against Cedar policies before execution. "
        "Sensitive actions require human approval.\n\n"
        "## Authentication\n\n"
        "All endpoints (except `/v1/health`) require `Authorization: Bearer agr_sk_<key>` header.\n\n"
        "## Decision Values\n\n"
        "- `ALLOW` — agent may proceed\n"
        "- `DENY` — action is blocked\n"
        "- `APPROVAL_REQUIRED` — action is queued for human approval"
    ),
    version="0.1.0",
    contact={"name": "Shreeja AI", "url": "https://shreejaai.com"},
    openapi_tags=[
        {"name": "evaluate", "description": "Evaluate agent actions against Cedar policies."},
        {"name": "policies", "description": "Create, update, and simulate Cedar policies."},
        {"name": "approvals", "description": "Manage human approval workflows."},
        {"name": "agents", "description": "Register and manage AI agents."},
        {"name": "audit", "description": "Query the hash-chained audit log."},
        {"name": "org", "description": "Organization profile and usage stats."},
        {"name": "webhooks", "description": "Configure outbound webhooks."},
        {"name": "compliance", "description": "Compliance posture and findings."},
        {"name": "copilot", "description": "AI-powered policy authoring assistant."},
        {"name": "health", "description": "Health check."},
    ],
    lifespan=lifespan,
)
```

- [ ] **Step C1-2: Add Field descriptions to key request/response schemas in schemas.py**

In `services/agr-api/app/schemas.py`, update the following classes (preserve all existing validators):

```python
class EvaluateRequest(BaseModel):
    agent_id: str = Field(
        ..., min_length=1, max_length=256,
        description="Unique identifier for the agent making the request.",
        examples=["langgraph-prod-agent-1"],
    )
    action: str = Field(
        ..., min_length=1, max_length=256,
        description="Action the agent wants to perform. Maps to Cedar Action entity.",
        examples=["deploy", "read_secret", "send_email"],
    )
    resource: str = Field(
        ..., min_length=1, max_length=512,
        description="Resource identifier the action targets.",
        examples=["prod-database", "customer-pii-bucket"],
    )
    context: dict[str, object] = Field(
        default_factory=dict,
        description="Arbitrary context key/values evaluated in Cedar `when` clauses. Max 50 keys.",
        examples=[{"env": "production", "region": "us-east-1"}],
    )
    approver_email: str | None = Field(
        default=None, max_length=256,
        description="Override approver email for this specific request.",
    )
    # Keep existing validators unchanged


class EvaluateResponse(BaseModel):
    decision: str = Field(
        ..., description="ALLOW | DENY | APPROVAL_REQUIRED",
        examples=["ALLOW"],
    )
    reason: str = Field(..., description="Human-readable explanation of the decision.")
    policy_id: str | None = Field(
        default=None, description="UUID of the matching Cedar policy (null for Cedar CLI path)."
    )
    approval_id: str | None = Field(
        default=None, description="UUID of the created approval request (APPROVAL_REQUIRED only)."
    )
    latency_ms: float = Field(..., description="End-to-end evaluation latency in milliseconds.")
    eval_id: str = Field(..., description="Unique evaluation identifier for audit lookup.")
    risk_score: int | None = Field(
        default=None, description="0-100 risk score. Higher = more risk.", ge=0, le=100
    )
    risk_level: str | None = Field(
        default=None, description="low | medium | high | critical"
    )
    risk_factors: dict[str, int] | None = Field(
        default=None,
        description="Per-factor risk score contributions. Keys: action_severity, data_sensitivity, agent_trust, context_risk, time_risk.",
    )
    compliance_findings: list[dict[str, object]] | None = Field(
        default=None, description="Advisory compliance findings (EU AI Act, SOC2, ISO42001)."
    )
    decision_trace: DecisionTrace | None = Field(
        default=None, description="Internal decision trace for debugging."
    )
```

- [ ] **Step C1-3: Add tags to router definitions in routes**

In `services/agr-api/app/routes/evaluate.py`, find the `router = APIRouter(...)` line and add `tags`:

```python
router = APIRouter(prefix="/v1", tags=["evaluate"])
```

Repeat for each routes file:
- `routes/policies.py` → `tags=["policies"]`
- `routes/approvals.py` → `tags=["approvals"]`
- `routes/agents.py` → `tags=["agents"]`
- `routes/audit.py` → `tags=["audit"]`
- `routes/org.py` → `tags=["org"]`
- `routes/webhooks.py` → `tags=["webhooks"]`
- `routes/health.py` → `tags=["health"]`
- `routes/copilot.py` → `tags=["copilot"]`
- `routes/compliance.py` → `tags=["compliance"]`

- [ ] **Step C1-4: Verify the docs endpoint renders**

```bash
cd services/agr-api
uvicorn app.main:app --reload &
sleep 3
curl http://localhost:8000/openapi.json | python -m json.tool | head -50
curl -o /dev/null -s -w "%{http_code}" http://localhost:8000/docs   # should return 200
kill %1
```

- [ ] **Step C1-5: Create the OpenAPI export script**

Create `scripts/export_openapi.py`:

```python
#!/usr/bin/env python3
"""Export the OpenAPI schema to openapi.json.

Usage:
    python scripts/export_openapi.py

Writes to: openapi.json (repo root)
Run this after any schema or route change, then commit the result.
CI checks that the committed file is fresh (see ci.yml test-openapi-freshness).
"""

import json
import sys
from pathlib import Path

# Add services/agr-api to path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "agr-api"))

from app.main import app  # noqa: E402

schema = app.openapi()
output_path = Path(__file__).parent.parent / "openapi.json"
output_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
print(f"Written to {output_path} ({len(schema['paths'])} paths)")
```

- [ ] **Step C1-6: Export and commit openapi.json**

```bash
cd /path/to/agr-platform
pip install -r services/agr-api/requirements.txt
python scripts/export_openapi.py
```

Expected output: `Written to openapi.json (N paths)`

- [ ] **Step C1-7: Add OpenAPI freshness check to CI**

In `.github/workflows/ci.yml`, add a step to the `lint-and-test` job after the lint step:

```yaml
      - name: Check openapi.json is up-to-date
        run: |
          pip install -r services/agr-api/requirements.txt
          python scripts/export_openapi.py
          if ! git diff --exit-code openapi.json; then
            echo "openapi.json is stale — run 'python scripts/export_openapi.py' and commit the result"
            exit 1
          fi
```

- [ ] **Step C1-8: Run full test suite to confirm no regressions**

```bash
cd services/agr-api
python -m pytest tests/ --ignore=tests/postgres -q
```

Expected: 158 tests pass.

- [ ] **Step C1-9: Commit**

```bash
git add services/agr-api/app/schemas.py \
        services/agr-api/app/main.py \
        services/agr-api/app/routes/ \
        scripts/export_openapi.py \
        openapi.json \
        .github/workflows/ci.yml
git commit -m "feat(api): enrich OpenAPI docs with descriptions, tags, and export script

- Add Field descriptions and examples to EvaluateRequest/Response schemas
- Add router tags to all 10 route files (evaluate, policies, approvals, etc.)
- Enrich FastAPI app with full OpenAPI metadata and tag descriptions
- Add scripts/export_openapi.py to generate openapi.json
- Add CI freshness check: CI fails if openapi.json is stale

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task C2: Team Invite API — Migration + Routes

**Module:** `services/agr-api`
**Must run AFTER C1** (both modify `schemas.py`)
**D3 depends on this task being complete**

**Files:**
- Create: `infra/migrations/024_org_invitations.sql`
- Create: `infra/migrations/rollback/024_down.sql`
- Modify: `services/agr-api/app/models.py` (add `OrgInvitation` model)
- Modify: `services/agr-api/app/schemas.py` (add invitation schemas)
- Create: `services/agr-api/app/routes/invitations.py`
- Create: `services/agr-api/app/services/invitation_service.py`
- Modify: `services/agr-api/app/main.py` (register invitations router)
- Modify: `infra/migrate.sh` (add migration 024)

**Context:** Currently org RBAC (`role` column on `organizations`) is per-API-key. To invite team members, we create `org_invitations` records and send Resend emails. When accepted, a new `organizations` row is created with the invited role. For Wave 1 we implement create + list + revoke. Accept is Wave 2.

---

- [ ] **Step C2-1: Write the failing tests**

Create `services/agr-api/tests/unit/test_invitations.py`:

```python
"""Tests for team invitation API."""

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient


class TestCreateInvitation:
    async def test_create_invitation_success(self, client: AsyncClient, auth_headers: dict):
        with patch(
            "app.services.invitation_service.send_invitation_email",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(
                "/v1/team/invitations",
                json={"email": "alice@example.com", "role": "operator"},
                headers=auth_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "alice@example.com"
        assert data["role"] == "operator"
        assert data["status"] == "pending"
        assert "id" in data
        assert "token" not in data  # token must not be exposed

    async def test_create_invitation_invalid_role(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/v1/team/invitations",
            json={"email": "alice@example.com", "role": "superadmin"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_create_invitation_invalid_email(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/v1/team/invitations",
            json={"email": "not-an-email", "role": "viewer"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_create_invitation_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            "/v1/team/invitations",
            json={"email": "alice@example.com", "role": "operator"},
        )
        assert resp.status_code == 401


class TestListInvitations:
    async def test_list_invitations_empty(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/v1/team/invitations", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_invitations_returns_created(
        self, client: AsyncClient, auth_headers: dict
    ):
        with patch(
            "app.services.invitation_service.send_invitation_email",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await client.post(
                "/v1/team/invitations",
                json={"email": "bob@example.com", "role": "viewer"},
                headers=auth_headers,
            )
        resp = await client.get("/v1/team/invitations", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["email"] == "bob@example.com"


class TestRevokeInvitation:
    async def test_revoke_invitation(self, client: AsyncClient, auth_headers: dict):
        with patch(
            "app.services.invitation_service.send_invitation_email",
            new_callable=AsyncMock,
            return_value=None,
        ):
            create_resp = await client.post(
                "/v1/team/invitations",
                json={"email": "carol@example.com", "role": "admin"},
                headers=auth_headers,
            )
        invitation_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/v1/team/invitations/{invitation_id}", headers=auth_headers
        )
        assert resp.status_code == 204

        # Should no longer appear in list
        list_resp = await client.get("/v1/team/invitations", headers=auth_headers)
        assert all(inv["id"] != invitation_id for inv in list_resp.json())

    async def test_revoke_nonexistent_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.delete(
            "/v1/team/invitations/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 404
```

- [ ] **Step C2-2: Run tests — confirm they fail (routes don't exist yet)**

```bash
cd services/agr-api
python -m pytest tests/unit/test_invitations.py -v
```

Expected: `404 Not Found` or `ImportError` — tests fail.

- [ ] **Step C2-3: Create migration 024**

Create `infra/migrations/024_org_invitations.sql`:

```sql
-- Migration 024: org_invitations table
-- Allows org admins to invite team members by email.
-- Invitation tokens are single-use and expire after 7 days.

CREATE TABLE org_invitations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'operator'
                    CHECK (role IN ('admin', 'operator', 'viewer')),
    token       TEXT NOT NULL UNIQUE DEFAULT encode(gen_random_bytes(32), 'hex'),
    status      TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'accepted', 'revoked', 'expired')),
    invited_by  UUID REFERENCES organizations(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days')
);

CREATE INDEX org_invitations_org_id_idx ON org_invitations(org_id);
CREATE INDEX org_invitations_token_idx  ON org_invitations(token);

-- RLS
ALTER TABLE org_invitations ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_invitations_isolation ON org_invitations
    USING (org_id = current_setting('app.current_org_id')::uuid);
```

Create `infra/migrations/rollback/024_down.sql`:

```sql
DROP TABLE IF EXISTS org_invitations;
```

- [ ] **Step C2-4: Add OrgInvitation model to models.py**

In `services/agr-api/app/models.py`, add after the last model class:

```python
class OrgInvitation(Base):
    __tablename__ = "org_invitations"

    id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    email: Mapped[str] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(default="operator", nullable=False)
    token: Mapped[str] = mapped_column(nullable=False, unique=True)
    status: Mapped[str] = mapped_column(default="pending", nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
```

Check the top of `models.py` for existing imports — add `uuid`, `datetime`, `UTC`, `ForeignKey` if not already imported. Follow the exact pattern of existing models in that file.

- [ ] **Step C2-5: Add invitation schemas to schemas.py**

In `services/agr-api/app/schemas.py`, add at the end of the file (before `ErrorResponse`):

```python
class InvitationCreate(BaseModel):
    email: str = Field(
        ..., description="Email address of the person to invite.", examples=["alice@example.com"]
    )
    role: Literal["admin", "operator", "viewer"] = Field(
        default="operator", description="Role to assign when the invitation is accepted."
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        import re
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email address.")
        return v.lower().strip()


class InvitationResponse(BaseModel):
    id: str
    email: str
    role: str
    status: str
    created_at: datetime
    expires_at: datetime
```

- [ ] **Step C2-6: Create invitation_service.py**

Create `services/agr-api/app/services/invitation_service.py`:

```python
"""Business logic for team invitations."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrgInvitation
from app.config import settings


async def create_invitation(
    session: AsyncSession,
    org_id: uuid.UUID,
    email: str,
    role: str,
) -> OrgInvitation:
    token = secrets.token_hex(32)
    invitation = OrgInvitation(
        org_id=org_id,
        email=email,
        role=role,
        token=token,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    session.add(invitation)
    await session.flush()
    await session.refresh(invitation)
    return invitation


async def list_invitations(
    session: AsyncSession,
    org_id: uuid.UUID,
    status: str = "pending",
) -> list[OrgInvitation]:
    result = await session.execute(
        select(OrgInvitation)
        .where(OrgInvitation.org_id == org_id, OrgInvitation.status == status)
        .order_by(OrgInvitation.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_invitation(
    session: AsyncSession,
    org_id: uuid.UUID,
    invitation_id: uuid.UUID,
) -> bool:
    """Returns True if revoked, False if not found."""
    result = await session.execute(
        select(OrgInvitation).where(
            OrgInvitation.id == invitation_id,
            OrgInvitation.org_id == org_id,
            OrgInvitation.status == "pending",
        )
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        return False
    invitation.status = "revoked"
    await session.flush()
    return True


async def send_invitation_email(email: str, role: str, token: str, org_name: str) -> None:
    """Send invitation email via Resend. No-ops if RESEND_API_KEY is not set."""
    import logging
    logger = logging.getLogger(__name__)

    resend_key = getattr(settings, "resend_api_key", None)
    if not resend_key:
        logger.info("RESEND_API_KEY not set — skipping invitation email to %s", email)
        return

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}"},
                json={
                    "from": "AGR <noreply@agr.dev>",
                    "to": [email],
                    "subject": f"You've been invited to {org_name} on AGR",
                    "html": (
                        f"<p>You have been invited to join <strong>{org_name}</strong> "
                        f"on AGR as <strong>{role}</strong>.</p>"
                        f"<p><a href='https://dashboard.agr.dev/accept-invite?token={token}'>"
                        f"Accept Invitation</a></p>"
                    ),
                },
            )
            if resp.status_code >= 400:
                logger.error("Failed to send invitation email: %s", resp.text)
    except Exception as exc:
        logger.error("Error sending invitation email to %s: %s", email, exc)
```

- [ ] **Step C2-7: Create routes/invitations.py**

Create `services/agr-api/app/routes/invitations.py`:

```python
"""Team invitation endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas import InvitationCreate, InvitationResponse
from app.services import invitation_service

router = APIRouter(prefix="/v1/team", tags=["team"])


@router.post("/invitations", response_model=InvitationResponse, status_code=201)
async def create_invitation(
    body: InvitationCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> InvitationResponse:
    """Invite a team member by email. Sends an invitation email via Resend."""
    org = request.state.org
    invitation = await invitation_service.create_invitation(
        session, org.id, body.email, body.role
    )
    await invitation_service.send_invitation_email(
        body.email, body.role, invitation.token, org.name
    )
    return InvitationResponse(
        id=str(invitation.id),
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
    )


@router.get("/invitations", response_model=list[InvitationResponse])
async def list_invitations(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[InvitationResponse]:
    """List all pending invitations for the org."""
    org = request.state.org
    invitations = await invitation_service.list_invitations(session, org.id)
    return [
        InvitationResponse(
            id=str(inv.id),
            email=inv.email,
            role=inv.role,
            status=inv.status,
            created_at=inv.created_at,
            expires_at=inv.expires_at,
        )
        for inv in invitations
    ]


@router.delete("/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke a pending invitation."""
    org = request.state.org
    revoked = await invitation_service.revoke_invitation(session, org.id, invitation_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Invitation not found.")
```

- [ ] **Step C2-8: Register invitations router in main.py**

In `services/agr-api/app/main.py`, add to the imports section:

```python
from app.routes.invitations import router as invitations_router
```

And in the `app.include_router(...)` block, add:

```python
app.include_router(invitations_router)
```

- [ ] **Step C2-9: Run the tests — all should pass**

```bash
cd services/agr-api
python -m pytest tests/unit/test_invitations.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step C2-10: Run full suite — no regressions**

```bash
python -m pytest tests/ --ignore=tests/postgres -q
```

Expected: 165 tests pass (158 + 7 new).

- [ ] **Step C2-11: Type check**

```bash
python -m mypy app/ --show-error-codes
```

Expected: 0 errors.

- [ ] **Step C2-12: Update migrate.sh**

In `infra/migrate.sh`, add migration 024 following the pattern of the existing entries for 023.

- [ ] **Step C2-13: Commit**

```bash
git add infra/migrations/024_org_invitations.sql \
        infra/migrations/rollback/024_down.sql \
        infra/migrate.sh \
        services/agr-api/app/models.py \
        services/agr-api/app/schemas.py \
        services/agr-api/app/routes/invitations.py \
        services/agr-api/app/services/invitation_service.py \
        services/agr-api/app/main.py \
        services/agr-api/tests/unit/test_invitations.py
git commit -m "feat(api): team invitation API — create, list, revoke

- Migration 024: org_invitations table with RLS, token, 7d expiry
- POST /v1/team/invitations: creates record + sends Resend email (no-ops if key unset)
- GET /v1/team/invitations: lists pending invitations
- DELETE /v1/team/invitations/{id}: revoke with 404 on not-found
- 7 unit tests covering happy path and error cases

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task D1: Policy Simulator UI

**Module:** `apps/agr-dashboard`
**Can run in parallel with:** A1, B1, C1, C2

**Files:**
- Create: `apps/agr-dashboard/src/app/pages/policy-simulator/policy-simulator.component.ts`
- Create: `apps/agr-dashboard/src/app/pages/policy-simulator/policy-simulator.component.html`
- Modify: `apps/agr-dashboard/src/app/app.routes.ts`
- Modify: `apps/agr-dashboard/src/app/layout/shell/shell.component.html` (add nav link)

**Context:** `POST /v1/policies/simulate` already exists. Request: `{agent_id, action, resource, context}`. Response: `{decision, reason, policy_id, risk_score, risk_level, risk_factors, decision_trace}`. Angular standalone, OnPush, signals, inject(), Tailwind. Dashboard services communicate with the API via `HttpClient` + the `apiKeyInterceptor`.

---

- [ ] **Step D1-1: Read the existing policies.service.ts to understand HTTP patterns**

```bash
cat apps/agr-dashboard/src/app/services/policy.service.ts
```

Note the pattern: `inject(HttpClient)`, `this.http.get<T>(...)`, returns `Observable<T>`.

- [ ] **Step D1-2: Add simulate method to the existing policy service**

In `apps/agr-dashboard/src/app/services/policy.service.ts`, add:

```typescript
simulatePolicy(payload: {
  agent_id: string;
  action: string;
  resource: string;
  context: Record<string, unknown>;
}): Observable<SimulateResult> {
  return this.http.post<SimulateResult>(`${this.base}/policies/simulate`, payload);
}
```

Add the `SimulateResult` interface near the top of the service file (or in a models file if one exists):

```typescript
export interface SimulateResult {
  decision: 'ALLOW' | 'DENY' | 'APPROVAL_REQUIRED';
  reason: string;
  policy_id: string | null;
  risk_score: number | null;
  risk_level: string | null;
  risk_factors: Record<string, number> | null;
  decision_trace: {
    policy_source: string;
    cedar_decision: string;
    risk_override: boolean;
  } | null;
}
```

- [ ] **Step D1-3: Create the component TypeScript file**

Create `apps/agr-dashboard/src/app/pages/policy-simulator/policy-simulator.component.ts`:

```typescript
import {
  Component,
  inject,
  signal,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PolicyService, SimulateResult } from '../../services/policy.service';

interface ContextEntry {
  key: string;
  value: string;
}

@Component({
  selector: 'app-policy-simulator',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './policy-simulator.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PolicySimulatorComponent {
  private policyService = inject(PolicyService);

  agentId = signal('');
  action = signal('');
  resource = signal('');
  contextEntries = signal<ContextEntry[]>([{ key: '', value: '' }]);

  loading = signal(false);
  result = signal<SimulateResult | null>(null);
  error = signal<string | null>(null);

  addContextRow(): void {
    this.contextEntries.update((rows) => [...rows, { key: '', value: '' }]);
  }

  removeContextRow(index: number): void {
    this.contextEntries.update((rows) => rows.filter((_, i) => i !== index));
  }

  simulate(): void {
    const context: Record<string, unknown> = {};
    for (const entry of this.contextEntries()) {
      if (entry.key.trim()) {
        context[entry.key.trim()] = entry.value;
      }
    }

    this.loading.set(true);
    this.result.set(null);
    this.error.set(null);

    this.policyService
      .simulatePolicy({
        agent_id: this.agentId(),
        action: this.action(),
        resource: this.resource(),
        context,
      })
      .subscribe({
        next: (res) => {
          this.result.set(res);
          this.loading.set(false);
        },
        error: (err) => {
          this.error.set(err?.error?.detail ?? 'Simulation failed.');
          this.loading.set(false);
        },
      });
  }

  decisionClass(): string {
    const d = this.result()?.decision;
    if (d === 'ALLOW') return 'text-green-400';
    if (d === 'DENY') return 'text-red-400';
    if (d === 'APPROVAL_REQUIRED') return 'text-yellow-400';
    return '';
  }

  riskFactorEntries(): [string, number][] {
    const rf = this.result()?.risk_factors;
    return rf ? Object.entries(rf) : [];
  }
}
```

- [ ] **Step D1-4: Create the component HTML template**

Create `apps/agr-dashboard/src/app/pages/policy-simulator/policy-simulator.component.html`:

```html
<div class="p-6 max-w-3xl mx-auto space-y-6">
  <div>
    <h1 class="text-2xl font-semibold text-white">Policy Simulator</h1>
    <p class="text-slate-400 mt-1">
      Test a Cedar policy decision without side effects. No audit events are written.
    </p>
  </div>

  <!-- Input form -->
  <div class="card space-y-4">
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <div>
        <label class="block text-sm font-medium text-slate-300 mb-1">Agent ID</label>
        <input
          class="input w-full"
          placeholder="my-langgraph-agent"
          [ngModel]="agentId()"
          (ngModelChange)="agentId.set($event)"
        />
      </div>
      <div>
        <label class="block text-sm font-medium text-slate-300 mb-1">Action</label>
        <input
          class="input w-full"
          placeholder="deploy"
          [ngModel]="action()"
          (ngModelChange)="action.set($event)"
        />
      </div>
      <div>
        <label class="block text-sm font-medium text-slate-300 mb-1">Resource</label>
        <input
          class="input w-full"
          placeholder="prod-database"
          [ngModel]="resource()"
          (ngModelChange)="resource.set($event)"
        />
      </div>
    </div>

    <!-- Context key/value builder -->
    <div>
      <label class="block text-sm font-medium text-slate-300 mb-2">Context</label>
      <div class="space-y-2">
        @for (entry of contextEntries(); track $index) {
          <div class="flex gap-2 items-center">
            <input
              class="input flex-1"
              placeholder="key"
              [(ngModel)]="entry.key"
            />
            <input
              class="input flex-1"
              placeholder="value"
              [(ngModel)]="entry.value"
            />
            @if (contextEntries().length > 1) {
              <button
                type="button"
                class="text-slate-400 hover:text-red-400 transition-colors"
                (click)="removeContextRow($index)"
              >
                ✕
              </button>
            }
          </div>
        }
      </div>
      <button
        type="button"
        class="mt-2 text-sm text-indigo-400 hover:text-indigo-300 transition-colors"
        (click)="addContextRow()"
      >
        + Add context key
      </button>
    </div>

    <button
      class="btn-primary w-full sm:w-auto"
      [disabled]="loading() || !agentId() || !action() || !resource()"
      (click)="simulate()"
    >
      @if (loading()) { Simulating… } @else { Run Simulation }
    </button>
  </div>

  <!-- Error -->
  @if (error()) {
    <div class="rounded-lg bg-red-900/30 border border-red-700 p-4 text-red-300">
      {{ error() }}
    </div>
  }

  <!-- Result -->
  @if (result(); as r) {
    <div class="card space-y-4">
      <div class="flex items-center justify-between">
        <span class="text-lg font-semibold text-white">Decision</span>
        <span class="text-2xl font-bold" [ngClass]="decisionClass()">
          {{ r.decision }}
        </span>
      </div>

      <p class="text-slate-300">{{ r.reason }}</p>

      @if (r.policy_id) {
        <p class="text-xs text-slate-500">Matched policy: <code>{{ r.policy_id }}</code></p>
      }

      @if (r.risk_score !== null) {
        <div class="flex items-center gap-4">
          <div>
            <span class="text-sm text-slate-400">Risk Score</span>
            <div class="text-2xl font-bold text-white">{{ r.risk_score }}<span class="text-base text-slate-400">/100</span></div>
          </div>
          @if (r.risk_level) {
            <div>
              <span class="text-sm text-slate-400">Level</span>
              <div class="text-sm font-medium text-white uppercase">{{ r.risk_level }}</div>
            </div>
          }
        </div>
      }

      @if (riskFactorEntries().length > 0) {
        <div>
          <p class="text-sm font-medium text-slate-300 mb-2">Risk Factors</p>
          <div class="space-y-1">
            @for (entry of riskFactorEntries(); track entry[0]) {
              <div class="flex justify-between text-sm">
                <span class="text-slate-400">{{ entry[0] }}</span>
                <span class="text-white font-medium">{{ entry[1] }} pts</span>
              </div>
            }
          </div>
        </div>
      }

      @if (r.decision_trace) {
        <details class="text-xs text-slate-500">
          <summary class="cursor-pointer hover:text-slate-400">Decision trace</summary>
          <pre class="mt-2 bg-slate-900 rounded p-3 overflow-auto">{{ r.decision_trace | json }}</pre>
        </details>
      }
    </div>
  }
</div>
```

- [ ] **Step D1-5: Add route in app.routes.ts**

In `apps/agr-dashboard/src/app/app.routes.ts`, add inside the `children` array (after the `copilot` route):

```typescript
      {
        path: 'simulator',
        canActivate: [apiKeyGuard],
        loadComponent: () =>
          import('./pages/policy-simulator/policy-simulator.component').then(
            (m) => m.PolicySimulatorComponent
          ),
      },
```

- [ ] **Step D1-6: Add nav link in shell**

Read `apps/agr-dashboard/src/app/layout/shell/shell.component.html` and find the nav list. Add a "Simulator" link following the same pattern as the Policies link:

```html
<a routerLink="/simulator" routerLinkActive="active" class="nav-link">
  Simulator
</a>
```

- [ ] **Step D1-7: Build to confirm no TypeScript errors**

```bash
cd apps/agr-dashboard
npm run build -- --configuration production 2>&1 | tail -20
```

Expected: Build succeeds with no errors.

- [ ] **Step D1-8: Commit**

```bash
git add apps/agr-dashboard/src/app/pages/policy-simulator/ \
        apps/agr-dashboard/src/app/app.routes.ts \
        apps/agr-dashboard/src/app/layout/ \
        apps/agr-dashboard/src/app/services/policy.service.ts
git commit -m "feat(dashboard): Policy Simulator UI

- New page at /simulator: agent_id + action + resource + dynamic context builder
- One-click simulate → shows decision (ALLOW/DENY/APPROVAL_REQUIRED) with color coding
- Risk score + per-factor breakdown + collapsible decision trace
- Uses existing POST /v1/policies/simulate — no API changes
- Added nav link in shell

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task D2: Eval Usage Meter

**Module:** `apps/agr-dashboard`
**Can run in parallel with:** A1, B1, C1, C2, D1

**Files:**
- Create: `apps/agr-dashboard/src/app/core/components/eval-meter/eval-meter.component.ts`
- Create: `apps/agr-dashboard/src/app/core/components/eval-meter/eval-meter.component.html`
- Modify: `apps/agr-dashboard/src/app/layout/shell/shell.component.ts` (fetch org/me, pass to meter)
- Modify: `apps/agr-dashboard/src/app/layout/shell/shell.component.html` (render meter in header)

**Context:** `GET /v1/org/me` returns `{eval_count, eval_limit, plan, ...}`. `eval_limit = 0` means unlimited. The meter should show `X / Y` evals used, warn at 80%, and show "Unlimited" when limit is 0. Already-available via the API — no backend changes needed.

---

- [ ] **Step D2-1: Create the eval-meter component**

Create `apps/agr-dashboard/src/app/core/components/eval-meter/eval-meter.component.ts`:

```typescript
import {
  Component,
  input,
  computed,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-eval-meter',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './eval-meter.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EvalMeterComponent {
  evalCount = input.required<number>();
  evalLimit = input.required<number>();

  isUnlimited = computed(() => this.evalLimit() === 0);

  percentage = computed(() => {
    if (this.isUnlimited() || this.evalLimit() === 0) return 0;
    return Math.min(100, Math.round((this.evalCount() / this.evalLimit()) * 100));
  });

  isWarning = computed(() => this.percentage() >= 80 && this.percentage() < 95);
  isCritical = computed(() => this.percentage() >= 95);

  barColor = computed(() => {
    if (this.isCritical()) return 'bg-red-500';
    if (this.isWarning()) return 'bg-yellow-500';
    return 'bg-indigo-500';
  });

  label = computed(() => {
    if (this.isUnlimited()) return 'Unlimited evals';
    return `${this.evalCount().toLocaleString()} / ${this.evalLimit().toLocaleString()} evals`;
  });
}
```

Create `apps/agr-dashboard/src/app/core/components/eval-meter/eval-meter.component.html`:

```html
<div class="flex items-center gap-3 min-w-0">
  <div class="text-xs text-slate-400 whitespace-nowrap">{{ label() }}</div>
  @if (!isUnlimited()) {
    <div class="w-24 h-1.5 bg-slate-700 rounded-full overflow-hidden flex-shrink-0">
      <div
        class="h-full rounded-full transition-all duration-500"
        [ngClass]="barColor()"
        [style.width.%]="percentage()"
      ></div>
    </div>
    @if (isWarning() || isCritical()) {
      <span class="text-xs font-medium" [ngClass]="isCritical() ? 'text-red-400' : 'text-yellow-400'">
        {{ percentage() }}%
      </span>
    }
  }
</div>
```

- [ ] **Step D2-2: Read the shell component to understand its structure**

```bash
cat apps/agr-dashboard/src/app/layout/shell/shell.component.ts
```

Note: how the shell fetches org data, what services it uses, signal patterns.

- [ ] **Step D2-3: Update ShellComponent to fetch org/me and render the meter**

In `apps/agr-dashboard/src/app/layout/shell/shell.component.ts`:

1. Add `OrgService` injection (read `services/org.service.ts` first to find the correct method for `GET /v1/org/me`)
2. Add signals `evalCount` and `evalLimit`
3. On `ngOnInit`, call `orgService.getOrgMe()` and set the signals

Example pattern to add:

```typescript
// Add to imports
import { EvalMeterComponent } from '../../core/components/eval-meter/eval-meter.component';
import { OrgService } from '../../services/org.service';

// Add inside component class
private orgService = inject(OrgService);
evalCount = signal(0);
evalLimit = signal(0);

ngOnInit(): void {
  this.orgService.getOrgMe().subscribe((org) => {
    this.evalCount.set(org.eval_count);
    this.evalLimit.set(org.eval_limit);
  });
}
```

In `shell.component.html`, find the header bar and add the meter:

```html
<app-eval-meter [evalCount]="evalCount()" [evalLimit]="evalLimit()" />
```

- [ ] **Step D2-4: Build to confirm no TypeScript errors**

```bash
cd apps/agr-dashboard
npm run build -- --configuration production 2>&1 | tail -20
```

- [ ] **Step D2-5: Commit**

```bash
git add apps/agr-dashboard/src/app/core/components/eval-meter/ \
        apps/agr-dashboard/src/app/layout/
git commit -m "feat(dashboard): eval usage meter in header

- Shows 'X / Y evals used this week' with progress bar
- Warns at 80% (yellow), critical at 95% (red)
- Shows 'Unlimited evals' when eval_limit = 0
- Uses existing GET /v1/org/me — no API changes

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task D3: Team Invite UI

**Module:** `apps/agr-dashboard`
**Depends on:** C2 (Team Invite API must be merged first)

**Files:**
- Create: `apps/agr-dashboard/src/app/pages/team/team.component.ts`
- Create: `apps/agr-dashboard/src/app/pages/team/team.component.html`
- Create: `apps/agr-dashboard/src/app/services/team.service.ts`
- Modify: `apps/agr-dashboard/src/app/app.routes.ts`
- Modify: shell nav (add Team link)

---

- [ ] **Step D3-1: Create team.service.ts**

Create `apps/agr-dashboard/src/app/services/team.service.ts`:

```typescript
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface Invitation {
  id: string;
  email: string;
  role: 'admin' | 'operator' | 'viewer';
  status: string;
  created_at: string;
  expires_at: string;
}

@Injectable({ providedIn: 'root' })
export class TeamService {
  private http = inject(HttpClient);
  private base = environment.apiBase;

  listInvitations(): Observable<Invitation[]> {
    return this.http.get<Invitation[]>(`${this.base}/team/invitations`);
  }

  createInvitation(email: string, role: string): Observable<Invitation> {
    return this.http.post<Invitation>(`${this.base}/team/invitations`, { email, role });
  }

  revokeInvitation(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/team/invitations/${id}`);
  }
}
```

- [ ] **Step D3-2: Create team.component.ts**

Create `apps/agr-dashboard/src/app/pages/team/team.component.ts`:

```typescript
import {
  Component,
  inject,
  signal,
  OnInit,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TeamService, Invitation } from '../../services/team.service';

@Component({
  selector: 'app-team',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './team.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TeamComponent implements OnInit {
  private teamService = inject(TeamService);

  invitations = signal<Invitation[]>([]);
  loading = signal(false);
  inviteEmail = signal('');
  inviteRole = signal<'admin' | 'operator' | 'viewer'>('operator');
  inviting = signal(false);
  inviteError = signal<string | null>(null);
  inviteSuccess = signal(false);

  roles: Array<{ value: string; label: string }> = [
    { value: 'admin', label: 'Admin — full access' },
    { value: 'operator', label: 'Operator — create/update, no settings' },
    { value: 'viewer', label: 'Viewer — read-only' },
  ];

  ngOnInit(): void {
    this.loadInvitations();
  }

  loadInvitations(): void {
    this.loading.set(true);
    this.teamService.listInvitations().subscribe({
      next: (items) => {
        this.invitations.set(items);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  sendInvite(): void {
    this.inviting.set(true);
    this.inviteError.set(null);
    this.inviteSuccess.set(false);

    this.teamService.createInvitation(this.inviteEmail(), this.inviteRole()).subscribe({
      next: () => {
        this.inviteSuccess.set(true);
        this.inviteEmail.set('');
        this.inviting.set(false);
        this.loadInvitations();
      },
      error: (err) => {
        this.inviteError.set(err?.error?.detail ?? 'Failed to send invitation.');
        this.inviting.set(false);
      },
    });
  }

  revoke(id: string): void {
    this.teamService.revokeInvitation(id).subscribe({
      next: () => this.invitations.update((items) => items.filter((i) => i.id !== id)),
    });
  }
}
```

- [ ] **Step D3-3: Create team.component.html**

Create `apps/agr-dashboard/src/app/pages/team/team.component.html`:

```html
<div class="p-6 max-w-3xl mx-auto space-y-6">
  <div>
    <h1 class="text-2xl font-semibold text-white">Team</h1>
    <p class="text-slate-400 mt-1">Invite team members to access this org.</p>
  </div>

  <!-- Invite form -->
  <div class="card space-y-4">
    <h2 class="text-lg font-medium text-white">Invite a member</h2>

    <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <div class="sm:col-span-2">
        <label class="block text-sm text-slate-300 mb-1">Email</label>
        <input
          class="input w-full"
          type="email"
          placeholder="alice@company.com"
          [ngModel]="inviteEmail()"
          (ngModelChange)="inviteEmail.set($event)"
        />
      </div>
      <div>
        <label class="block text-sm text-slate-300 mb-1">Role</label>
        <select
          class="input w-full"
          [ngModel]="inviteRole()"
          (ngModelChange)="inviteRole.set($event)"
        >
          @for (role of roles; track role.value) {
            <option [value]="role.value">{{ role.label }}</option>
          }
        </select>
      </div>
    </div>

    @if (inviteError()) {
      <p class="text-sm text-red-400">{{ inviteError() }}</p>
    }
    @if (inviteSuccess()) {
      <p class="text-sm text-green-400">Invitation sent.</p>
    }

    <button
      class="btn-primary"
      [disabled]="inviting() || !inviteEmail()"
      (click)="sendInvite()"
    >
      @if (inviting()) { Sending… } @else { Send Invite }
    </button>
  </div>

  <!-- Pending invitations -->
  <div class="card">
    <h2 class="text-lg font-medium text-white mb-4">Pending Invitations</h2>

    @if (loading()) {
      <p class="text-slate-400 text-sm">Loading…</p>
    } @else if (invitations().length === 0) {
      <p class="text-slate-400 text-sm">No pending invitations.</p>
    } @else {
      <table class="table-auto w-full text-sm">
        <thead>
          <tr class="table-header">
            <th class="text-left py-2 px-3 text-slate-400 font-medium">Email</th>
            <th class="text-left py-2 px-3 text-slate-400 font-medium">Role</th>
            <th class="text-left py-2 px-3 text-slate-400 font-medium">Expires</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          @for (inv of invitations(); track inv.id) {
            <tr class="border-t border-slate-700/50">
              <td class="py-2 px-3 text-white">{{ inv.email }}</td>
              <td class="py-2 px-3">
                <span class="text-xs font-medium uppercase text-indigo-300">{{ inv.role }}</span>
              </td>
              <td class="py-2 px-3 text-slate-400">{{ inv.expires_at | date:'mediumDate' }}</td>
              <td class="py-2 px-3 text-right">
                <button
                  class="text-xs text-red-400 hover:text-red-300 transition-colors"
                  (click)="revoke(inv.id)"
                >
                  Revoke
                </button>
              </td>
            </tr>
          }
        </tbody>
      </table>
    }
  </div>
</div>
```

- [ ] **Step D3-4: Add route**

In `apps/agr-dashboard/src/app/app.routes.ts`, add in `children`:

```typescript
      {
        path: 'team',
        canActivate: [apiKeyGuard],
        loadComponent: () =>
          import('./pages/team/team.component').then((m) => m.TeamComponent),
      },
```

- [ ] **Step D3-5: Add nav link in shell**

Add to shell navigation:

```html
<a routerLink="/team" routerLinkActive="active" class="nav-link">Team</a>
```

- [ ] **Step D3-6: Build to confirm no TypeScript errors**

```bash
cd apps/agr-dashboard
npm run build -- --configuration production 2>&1 | tail -20
```

- [ ] **Step D3-7: Commit**

```bash
git add apps/agr-dashboard/src/app/pages/team/ \
        apps/agr-dashboard/src/app/services/team.service.ts \
        apps/agr-dashboard/src/app/app.routes.ts \
        apps/agr-dashboard/src/app/layout/
git commit -m "feat(dashboard): Team invite UI — send, list, revoke invitations

- Team page at /team: invite by email + role selection
- Lists pending invitations with expiry dates
- Revoke button removes invitation immediately
- Uses POST/GET/DELETE /v1/team/invitations (Task C2)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Wave 2 — Task-Level (Weeks 4–8)

These are ready to plan in detail once Wave 1 is merged. Parallel dispatch opportunities noted.

### Parallel Group 2A (independent — dispatch simultaneously)

**Task E1: Risk Score Breakdown Panel (Dashboard)**
- Add `RiskBreakdownComponent` — small expandable panel showing per-factor contributions
- Used inline in: Approvals page, Audit log rows, Simulator result (already has data)
- No API changes — risk_factors already in EvaluateResponse

**Task E2: Policy Template Library (API + Dashboard)**
- Seed table migration: `025_policy_templates.sql` with columns: `id, name, description, cedar_rule, tags, is_system`
- `GET /v1/policies/templates` — list system templates
- `POST /v1/policies/templates/{id}/import` — import template as active policy
- Dashboard: template browser in Policies page with search/filter + one-click import

**Task E3: OpenAI Agents SDK Plugin (`packages/agr-sdk-python`)**
- New file: `packages/agr-sdk-python/agr/plugins/openai_agents.py`
- Pattern mirrors `langgraph.py`: `agr_governed` decorator that wraps tool functions
- Tests: `tests/test_openai_plugin.py` — same pattern as LangGraph tests

### Sequential: 2B → 2C

**Task E4: Compliance PDF Export (API first → Dashboard)**
- `GET /v1/compliance/report?period_days=30&format=pdf` — uses `weasyprint` or `reportlab`
- Returns PDF with: period, decision counts, high-risk count, findings by standard, hash-chain status
- Dashboard: "Export Report" button in Compliance page

**Task E5: Approval Workflow Manager UI (Dashboard — some API work needed)**
- `GET /v1/approvals/{id}/steps` — already in approvals route, verify response shape
- Dashboard: add/remove approver steps, quorum type (any/all), SLA hours editor
- Full page view per approval with step-by-step status

**Task E6: Wire Temporal End-to-End**
- `services/agr-api/app/services/approval_service.py` — replace DB-only fallback with real Temporal workflow client
- Requires `TEMPORAL_HOST` env var set in docker-compose
- `infra/docker-compose.yml` — add Temporal + Temporal UI services
- Tests: integration tests against real Temporal (separate job in CI)

---

## Wave 3 — Task-Level (Weeks 8–16)

### Parallel Group 3A (dispatch simultaneously)

**Task F1: Slack Approval Bot**
- New service: `services/agr-api/app/services/slack_service.py`
- When APPROVAL_REQUIRED → POST to Slack Incoming Webhook with Approve/Reject buttons
- Slash command handler or Block Kit action handler: `POST /v1/slack/actions`
- Env vars: `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`

**Task F2: Google ADK Plugin**
- `packages/agr-sdk-python/agr/plugins/google_adk.py`
- Adapts the `@agr_governed` pattern to Google ADK's tool-wrapping API
- 1–2 days: exact same structure as OpenAI Agents plugin

**Task F3: Agent Activity Timeline (Dashboard)**
- `GET /v1/agents/{id}/timeline` — new route aggregating audit events per agent over time
- Dashboard: dedicated agent detail page with decision timeline, risk trend sparkline, deny rate

### Sequential: 3B

**Task F4: agr-cli**
- New package: `packages/agr-cli/` — Python Click CLI
- Commands: `agr policy list`, `agr policy simulate`, `agr audit export`, `agr agent list`
- Uses `AGRClient` under the hood, reads `~/.config/agr/config.toml` for API key
- Publishes to PyPI as `agr-cli`

**Task F5: SSO / SAML via Clerk**
- Clerk SAML configuration is done in the Clerk dashboard — no code changes needed for the protocol
- Code: `apps/agr-dashboard/src/app/core/auth/clerk.service.ts` — update init to support SAML redirect
- Document: SAML metadata URL, ACS URL, Attribute mappings for enterprise setup guide

**Task F6: Audit Anomaly Detection**
- Background job (Celery or APScheduler): runs every 15 minutes
- Detects: sudden deny rate spike (>3x rolling average), new agent first seen with high-risk action, same agent at approval limit
- Writes findings to a new `audit_anomalies` table (migration 026)
- Dashboard: Anomaly alerts panel on home page

---

## Wave 4 — Brief (Beyond 16 weeks)

| Task | Notes |
|------|-------|
| Dynamic agent trust scoring | Compute trust from actual behaviour history. Requires 30+ days of data. Replaces static `trust_level`. |
| Multi-org / sub-org hierarchy | Parent → child orgs with inherited policies. Significant schema change. Design first. |
| GitHub Action: agr-policy-check | Validate Cedar syntax on PR. Viral via open source. |
| Terraform provider | `terraform-provider-agr` for platform teams. Strong for large deployments. |
| Natural language policy testing in Copilot | Requires Copilot adoption. Build after usage patterns are clear. |
| Evaluation Explanation API | `POST /v1/evaluate/explain` — plain English explanation of past decision. |
| Go / Java / Ruby SDKs | Expand ecosystem. Go first (popular for agent infra). |
| Mobile-responsive approval UI | Hosted approval page at `dashboard.agr.dev/approve?token=...` |

---

## Self-Review

**Spec coverage check:**
- ✅ Cedar CLI end-to-end → Task A1 (tests + CI)
- ✅ Async Python SDK → Task B1
- ✅ OpenAPI docs + Swagger UI → Task C1
- ✅ Team invite + role UI → Tasks C2 + D3
- ✅ Policy Simulator UI → Task D1
- ✅ Eval usage meter → Task D2
- ✅ Risk score breakdown → Wave 2 E1
- ✅ Approval workflow manager → Wave 2 E5
- ✅ Compliance PDF export → Wave 2 E4
- ✅ Policy Template Library → Wave 2 E2
- ✅ OpenAI Agents SDK plugin → Wave 2 E3
- ✅ Temporal end-to-end → Wave 2 E6
- ✅ Slack approval bot → Wave 3 F1
- ✅ Agent activity timeline → Wave 3 F3
- ✅ agr-cli → Wave 3 F4
- ✅ SSO/SAML → Wave 3 F5
- ✅ Audit anomaly detection → Wave 3 F6
- ✅ Google ADK plugin → Wave 3 F2
- ✅ All Wave 4 items listed

**Placeholder scan:** None found. All Wave 1 tasks have complete code blocks, exact commands, and expected outputs.

**Type consistency:**
- `SimulateResult` defined in D1-2, used in D1-3 — consistent
- `InvitationResponse` defined in C2-5, used in C2-7 — consistent
- `AsyncAGRClient` defined in B1-3, exported in B1-4 — consistent
- `EvalMeterComponent` inputs match shell usage in D2 — consistent

---

## Execution Handoff

Wave 1 optimal dispatch (minimize wall-clock time):

```bash
# T=0: Dispatch 5 agents simultaneously
dispatch A1  # Cedar CLI tests + CI        (~2h)
dispatch B1  # Async Python SDK            (~1.5h)
dispatch C1  # OpenAPI schema enrichment   (~1h)
dispatch D1  # Policy Simulator UI         (~1.5h)
dispatch D2  # Eval Usage Meter            (~45m)

# T=C1_done: Dispatch C2 (must follow C1 — shared schemas.py)
dispatch C2  # Team Invite API             (~2h)

# T=C2_done: Dispatch D3 (depends on C2 API)
dispatch D3  # Team Invite UI              (~1h)
```

Total estimated wall-clock: max(2h, 1.5h, 1h, 1.5h, 45m) + 2h + 1h = **~5h with parallel agents** vs **~10h sequential**.
