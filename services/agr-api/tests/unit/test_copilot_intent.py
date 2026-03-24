"""Unit tests for CopilotService._classify_intent."""

import uuid
from unittest.mock import MagicMock

from app.services.copilot_service import CopilotService


def _make_service() -> CopilotService:
    """Create a CopilotService with mock session and org (no DB needed for intent tests)."""
    mock_org = MagicMock()
    mock_org.plan = "startup"
    return CopilotService(
        session=MagicMock(),  # type: ignore[arg-type]
        org_id=uuid.uuid4(),
        org=mock_org,
    )


# ── list intents ──────────────────────────────────────────────────────────────


def test_classify_list_policies() -> None:
    svc = _make_service()
    assert svc._classify_intent("list my policies") == "list_policies"


def test_classify_show_policies() -> None:
    svc = _make_service()
    assert svc._classify_intent("show all policies") == "list_policies"


def test_classify_list_agents() -> None:
    svc = _make_service()
    assert svc._classify_intent("list agents") == "list_agents"


def test_classify_show_agents() -> None:
    svc = _make_service()
    assert svc._classify_intent("show me all agents") == "list_agents"


def test_classify_list_webhooks() -> None:
    svc = _make_service()
    assert svc._classify_intent("list webhooks") == "list_webhooks"


def test_classify_get_webhooks() -> None:
    svc = _make_service()
    assert svc._classify_intent("get my webhooks") == "list_webhooks"


# ── sample intent ─────────────────────────────────────────────────────────────


def test_classify_sample() -> None:
    svc = _make_service()
    assert svc._classify_intent("show me sample policies") == "sample"


def test_classify_example() -> None:
    svc = _make_service()
    assert svc._classify_intent("give me an example policy") == "sample"


def test_classify_template() -> None:
    svc = _make_service()
    assert svc._classify_intent("show me a policy template") == "sample"


# ── explain intent ────────────────────────────────────────────────────────────


def test_classify_explain_cedar() -> None:
    svc = _make_service()
    assert svc._classify_intent("explain what Cedar is") == "explain"


def test_classify_what_is_agr() -> None:
    svc = _make_service()
    assert svc._classify_intent("what is AGR?") == "explain"


def test_classify_how_does_approval_work() -> None:
    svc = _make_service()
    assert svc._classify_intent("how does approval work?") == "explain"


# ── create_policy intent ──────────────────────────────────────────────────────


def test_classify_create_policy() -> None:
    svc = _make_service()
    assert svc._classify_intent("create a policy that blocks production deploys") == "create_policy"


def test_classify_block_production() -> None:
    svc = _make_service()
    assert svc._classify_intent("block all writes to production") == "create_policy"


def test_classify_forbid_action() -> None:
    svc = _make_service()
    assert svc._classify_intent("forbid db.drop in production") == "create_policy"


def test_classify_allow_action() -> None:
    svc = _make_service()
    assert svc._classify_intent("allow staging deploys") == "create_policy"


def test_classify_require_approval() -> None:
    svc = _make_service()
    assert svc._classify_intent("require approval for fund transfers over $10k") == "create_policy"


def test_classify_generate_cedar_rule() -> None:
    svc = _make_service()
    assert svc._classify_intent("generate a cedar rule for file writes") == "create_policy"


# ── register_agent intent ─────────────────────────────────────────────────────


def test_classify_register_agent() -> None:
    svc = _make_service()
    assert svc._classify_intent("register an agent called my-finance-agent") == "register_agent"


def test_classify_add_agent() -> None:
    svc = _make_service()
    assert svc._classify_intent("add an agent using LangGraph") == "register_agent"


def test_classify_register_keyword() -> None:
    svc = _make_service()
    assert svc._classify_intent("register my-crewai-agent") == "register_agent"


# ── create_webhook intent ─────────────────────────────────────────────────────


def test_classify_create_webhook() -> None:
    svc = _make_service()
    assert (
        svc._classify_intent("create a webhook for https://example.com/events")
        == "create_webhook"
    )


def test_classify_webhook_url_only() -> None:
    svc = _make_service()
    assert svc._classify_intent("webhook https://hooks.example.com/agr") == "create_webhook"


def test_classify_add_webhook() -> None:
    svc = _make_service()
    assert svc._classify_intent("add webhook https://my.service.com/hook") == "create_webhook"


# ── general fallback ──────────────────────────────────────────────────────────


def test_classify_general_fallback() -> None:
    svc = _make_service()
    assert svc._classify_intent("hello there") == "general"


def test_classify_general_question() -> None:
    svc = _make_service()
    assert svc._classify_intent("what can you help me with?") == "general"
