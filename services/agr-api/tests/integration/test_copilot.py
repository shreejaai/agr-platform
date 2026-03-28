"""Integration tests for POST /v1/copilot/chat."""

import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from app.config import settings as app_settings
from app.models import Organization, Policy
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Inject a stub `anthropic` module so tests run without the real package.
# The copilot service does `import anthropic` lazily inside _call_llm; we
# need the module available in sys.modules BEFORE patching starts.
# ---------------------------------------------------------------------------
if "anthropic" not in sys.modules:
    _stub = types.ModuleType("anthropic")
    _stub.AsyncAnthropic = MagicMock  # type: ignore[attr-defined]
    sys.modules["anthropic"] = _stub

# ── Plan-gating tests (no LLM needed) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_copilot_developer_plan_blocked(
    client: AsyncClient, auth_headers: dict[str, str], test_org: Organization
) -> None:
    """Developer plan orgs should receive an upgrade prompt."""
    assert test_org.plan == "developer"
    resp = await client.post(
        "/v1/copilot/chat",
        json={"message": "list my policies"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action_type"] == "error"
    assert "Startup" in data["message"] or "upgrade" in data["message"].lower()
    assert data["suggestions"] is not None


@pytest.mark.asyncio
async def test_copilot_startup_plan_allowed(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Startup plan org should pass plan gating and reach the service handler."""
    startup_org = Organization(
        id=uuid.uuid4(),
        name="Startup Org",
        slug="startup-org",
        plan="startup",
        api_key="agr_sk_startupkey1234567890abcdef123456789012",
        eval_count=0,
        eval_limit=10000,
    )
    db_session.add(startup_org)
    await db_session.commit()
    await db_session.refresh(startup_org)

    # Copilot is enabled but no API key — should return "not configured" error
    original_key = app_settings.anthropic_api_key
    app_settings.anthropic_api_key = ""
    try:
        resp = await client.post(
            "/v1/copilot/chat",
            json={"message": "list my policies"},
            headers={"Authorization": f"Bearer {startup_org.api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should reach the service (plan gate passed), but return error about missing API key
        assert data["action_type"] == "error"
        assert "not configured" in data["message"].lower() or "ANTHROPIC_API_KEY" in data["message"]
    finally:
        app_settings.anthropic_api_key = original_key


# ── List intents (no LLM needed) ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def startup_org_and_headers(
    db_session: AsyncSession,
) -> tuple[Organization, dict[str, str]]:
    """Create a startup-plan org and return it with auth headers."""
    org = Organization(
        id=uuid.uuid4(),
        name="Startup Test Org",
        slug="startup-test-org",
        plan="startup",
        api_key="agr_sk_startuptest1234567890abcdef12345678901",
        eval_count=0,
        eval_limit=10000,
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org, {"Authorization": f"Bearer {org.api_key}"}


@pytest.mark.asyncio
async def test_copilot_list_policies_empty(
    client: AsyncClient,
    startup_org_and_headers: tuple[Organization, dict[str, str]],
    db_session: AsyncSession,
) -> None:
    """list_policies with no policies returns a helpful empty message."""
    org, headers = startup_org_and_headers

    app_settings.anthropic_api_key = "sk-ant-fake-key-for-testing"
    app_settings.copilot_enabled = True
    try:
        resp = await client.post(
            "/v1/copilot/chat",
            json={"message": "list my policies"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_type"] == "list_policies"
        assert "no active policies" in data["message"].lower()
        assert data["suggestions"] is not None
    finally:
        app_settings.anthropic_api_key = ""


@pytest.mark.asyncio
async def test_copilot_list_policies_with_data(
    client: AsyncClient,
    startup_org_and_headers: tuple[Organization, dict[str, str]],
    db_session: AsyncSession,
) -> None:
    """list_policies with existing policies returns their names."""
    org, headers = startup_org_and_headers

    # Add 3 policies for this org
    for i in range(3):
        db_session.add(
            Policy(
                id=uuid.uuid4(),
                org_id=org.id,
                name=f"Policy {i + 1}",
                level="org",
                cedar_rule=f'permit(principal, action == Action::"action_{i}", resource);',
                active=True,
            )
        )
    await db_session.commit()

    app_settings.anthropic_api_key = "sk-ant-fake-key-for-testing"
    app_settings.copilot_enabled = True
    try:
        resp = await client.post(
            "/v1/copilot/chat",
            json={"message": "list my policies"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_type"] == "list_policies"
        assert "3" in data["message"]
        assert "Policy 1" in data["message"]
    finally:
        app_settings.anthropic_api_key = ""


@pytest.mark.asyncio
async def test_copilot_list_agents_empty(
    client: AsyncClient,
    startup_org_and_headers: tuple[Organization, dict[str, str]],
) -> None:
    """list_agents with no agents returns a helpful empty message."""
    org, headers = startup_org_and_headers

    app_settings.anthropic_api_key = "sk-ant-fake-key-for-testing"
    app_settings.copilot_enabled = True
    try:
        resp = await client.post(
            "/v1/copilot/chat",
            json={"message": "list agents"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_type"] == "list_agents"
        assert "no agents" in data["message"].lower()
    finally:
        app_settings.anthropic_api_key = ""


@pytest.mark.asyncio
async def test_copilot_list_webhooks_empty(
    client: AsyncClient,
    startup_org_and_headers: tuple[Organization, dict[str, str]],
) -> None:
    """list_webhooks with no webhooks returns a helpful empty message."""
    org, headers = startup_org_and_headers

    app_settings.anthropic_api_key = "sk-ant-fake-key-for-testing"
    app_settings.copilot_enabled = True
    try:
        resp = await client.post(
            "/v1/copilot/chat",
            json={"message": "list webhooks"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_type"] == "list_webhooks"
        assert "no webhooks" in data["message"].lower()
    finally:
        app_settings.anthropic_api_key = ""


# ── Sample intent (no LLM needed) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_copilot_sample_policies(
    client: AsyncClient,
    startup_org_and_headers: tuple[Organization, dict[str, str]],
) -> None:
    """Sample intent returns built-in sample policies without calling the LLM."""
    org, headers = startup_org_and_headers

    app_settings.anthropic_api_key = "sk-ant-fake-key-for-testing"
    app_settings.copilot_enabled = True
    try:
        resp = await client.post(
            "/v1/copilot/chat",
            json={"message": "show me sample policies"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_type"] == "sample"
        # Should contain at least one sample policy name
        assert "block_production_deploys" in data["message"]
        assert data["suggestions"] is not None
    finally:
        app_settings.anthropic_api_key = ""


# ── LLM-backed intents (mock Anthropic client) ────────────────────────────────


@pytest.mark.asyncio
async def test_copilot_create_policy_preview(
    client: AsyncClient,
    startup_org_and_headers: tuple[Organization, dict[str, str]],
) -> None:
    """create_policy returns a preview (not yet confirmed) when auto_confirm=False."""
    org, headers = startup_org_and_headers

    fake_llm_response = MagicMock()
    fake_llm_response.content = [
        MagicMock(
            text=(
                '{"name": "block_prod_deploy", "cedar_rule": '
                '"forbid(principal, action == Action::\\"deploy\\", resource)\\n'
                'when { context has \\"environment\\"'
                ' && context.environment == \\"production\\" };", '
                '"description": "Block all deploys to production", "level": "org"}'
            )
        )
    ]

    app_settings.anthropic_api_key = "sk-ant-fake-key-for-testing"
    app_settings.copilot_enabled = True
    try:
        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=fake_llm_response)
            mock_cls.return_value = mock_client

            resp = await client.post(
                "/v1/copilot/chat",
                json={
                    "message": "create a policy that blocks production deploys",
                    "auto_confirm": False,
                },
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["action_type"] == "create_policy"
            assert data["preview"] is not None
            assert data["preview"]["resource_type"] == "policy"
            assert data["preview"]["cedar_rule"] is not None
    finally:
        app_settings.anthropic_api_key = ""


@pytest.mark.asyncio
async def test_copilot_create_policy_auto_confirm(
    client: AsyncClient,
    startup_org_and_headers: tuple[Organization, dict[str, str]],
    db_session: AsyncSession,
) -> None:
    """create_policy with auto_confirm=True writes to DB and returns confirmed."""
    org, headers = startup_org_and_headers

    fake_llm_response = MagicMock()
    fake_llm_response.content = [
        MagicMock(
            text=(
                '{"name": "block_prod_deploy_auto", "cedar_rule": '
                '"forbid(principal, action == Action::\\"deploy\\", resource)\\n'
                'when { context has \\"environment\\"'
                ' && context.environment == \\"production\\" };", '
                '"description": "Block all deploys to production", "level": "org"}'
            )
        )
    ]

    app_settings.anthropic_api_key = "sk-ant-fake-key-for-testing"
    app_settings.copilot_enabled = True
    try:
        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=fake_llm_response)
            mock_cls.return_value = mock_client

            resp = await client.post(
                "/v1/copilot/chat",
                json={
                    "message": "create a policy that blocks production deploys",
                    "auto_confirm": True,
                },
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["action_type"] == "confirmed"
            assert data["created_resource"] is not None
            assert data["created_resource"]["name"] == "block_prod_deploy_auto"
            assert "id" in data["created_resource"]
    finally:
        app_settings.anthropic_api_key = ""


@pytest.mark.asyncio
async def test_copilot_returns_cedar_validation_error_for_bad_rule(
    client: AsyncClient,
    startup_org_and_headers: tuple[Organization, dict[str, str]],
) -> None:
    org, headers = startup_org_and_headers

    fake_llm_response = MagicMock()
    fake_llm_response.content = [
        MagicMock(
            text=(
                '{"name": "bad_rule", "cedar_rule": "permit(resource);", '
                '"description": "Broken policy", "level": "org"}'
            )
        )
    ]

    app_settings.anthropic_api_key = "sk-ant-fake-key-for-testing"
    app_settings.copilot_enabled = True
    try:
        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=fake_llm_response)
            mock_cls.return_value = mock_client

            resp = await client.post(
                "/v1/copilot/chat",
                json={
                    "message": "create a broken policy",
                    "auto_confirm": False,
                },
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["action_type"] == "error"
            assert data["cedar_valid"] is False
            assert data["cedar_validation_error"] is not None
    finally:
        app_settings.anthropic_api_key = ""


# ── _parse_json_response unit tests via service directly ─────────────────────


def test_parse_json_response_direct() -> None:
    """_parse_json_response handles clean JSON input."""
    from app.services.copilot_service import CopilotService

    svc = CopilotService(session=MagicMock(), org_id=uuid.uuid4(), org=MagicMock())  # type: ignore[arg-type]
    result = svc._parse_json_response('{"name": "test", "cedar_rule": "forbid(...);"}')
    assert result is not None
    assert result["name"] == "test"


def test_parse_json_response_with_markdown_block() -> None:
    """_parse_json_response strips markdown code fences."""
    from app.services.copilot_service import CopilotService

    svc = CopilotService(session=MagicMock(), org_id=uuid.uuid4(), org=MagicMock())  # type: ignore[arg-type]
    text = '```json\n{"name": "test", "level": "org"}\n```'
    result = svc._parse_json_response(text)
    assert result is not None
    assert result["name"] == "test"


def test_parse_json_response_embedded_json() -> None:
    """_parse_json_response finds JSON embedded in surrounding text."""
    from app.services.copilot_service import CopilotService

    svc = CopilotService(session=MagicMock(), org_id=uuid.uuid4(), org=MagicMock())  # type: ignore[arg-type]
    text = 'Here is the policy: {"name": "my_policy", "level": "org"} Hope that helps!'
    result = svc._parse_json_response(text)
    assert result is not None
    assert result["name"] == "my_policy"


def test_parse_json_response_invalid_returns_none() -> None:
    """_parse_json_response returns None for unparseable text."""
    from app.services.copilot_service import CopilotService

    svc = CopilotService(session=MagicMock(), org_id=uuid.uuid4(), org=MagicMock())  # type: ignore[arg-type]
    result = svc._parse_json_response("This is not JSON at all.")
    assert result is None


def test_parse_json_response_empty_string() -> None:
    """_parse_json_response returns None for empty input."""
    from app.services.copilot_service import CopilotService

    svc = CopilotService(session=MagicMock(), org_id=uuid.uuid4(), org=MagicMock())  # type: ignore[arg-type]
    result = svc._parse_json_response("")
    assert result is None
