"""Integration tests for enterprise SSO mapping via GET /v1/clerk/api-key."""

import base64
import json
import uuid

import pytest
from app.config import settings
from app.models import Organization, OrgMember
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _make_fake_jwt(payload: dict[str, object]) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.signature"


def _make_fake_org_api_key(label: str) -> str:
    return f"agr_sk_test_{label}"


class _FakeClerkResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


def _patch_clerk_api(monkeypatch: pytest.MonkeyPatch, *, email: str, user_id: str) -> None:
    class _FakeClerkClient:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        async def __aenter__(self) -> "_FakeClerkClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            return None

        async def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeClerkResponse:
            if f"/sessions/sess_{user_id}" in url:
                return _FakeClerkResponse(200, {"status": "active", "user_id": user_id})
            if f"/users/{user_id}" in url:
                return _FakeClerkResponse(
                    200,
                    {
                        "id": user_id,
                        "first_name": "Enterprise",
                        "last_name": "User",
                        "email_addresses": [{"email_address": email}],
                    },
                )
            raise AssertionError(f"Unexpected Clerk URL: {url}")

    monkeypatch.setattr("app.routes.clerk.httpx.AsyncClient", _FakeClerkClient)
    monkeypatch.setattr(settings, "clerk_secret_key", "clerk_test_secret", raising=False)


@pytest.mark.asyncio
async def test_clerk_api_key_returns_user_scoped_sso_session(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enterprise_org = Organization(
        id=uuid.uuid4(),
        name="Enterprise Org",
        slug="enterprise-org",
        plan="enterprise",
        api_key=_make_fake_org_api_key("enterprise_fixture"),
        eval_count=0,
        eval_limit=1000,
        sso_enabled=True,
        sso_provider="clerk_saml",
        sso_entity_id="enterprise-org",
        sso_domains="example.com",
        sso_auto_join=True,
        sso_default_role="viewer",
    )
    db_session.add(enterprise_org)
    await db_session.commit()

    _patch_clerk_api(monkeypatch, email="erin@example.com", user_id="user_enterprise")
    token = _make_fake_jwt(
        {
            "sub": "user_enterprise",
            "sid": "sess_user_enterprise",
            "organization_slug": "enterprise-org",
            "groups": ["operator"],
        }
    )

    response = await client.get(
        "/v1/clerk/api-key",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["api_key"].startswith("agr_usr_")
    assert payload["role"] == "operator"
    assert payload["auth_mode"] == "sso_session"

    org_response = await client.get(
        "/v1/org/me",
        headers={"Authorization": f"Bearer {payload['api_key']}"},
    )
    assert org_response.status_code == 200
    org_payload = org_response.json()
    assert org_payload["id"] == str(enterprise_org.id)
    assert org_payload["role"] == "operator"
    assert org_payload["auth_mode"] == "sso_session"

    member = (
        await db_session.execute(
            select(OrgMember).where(
                OrgMember.org_id == enterprise_org.id,
                OrgMember.email == "erin@example.com",
            )
        )
    ).scalar_one()
    assert member.status == "active"
    assert member.role == "operator"


@pytest.mark.asyncio
async def test_clerk_api_key_enforces_existing_membership_when_auto_join_disabled(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enterprise_org = Organization(
        id=uuid.uuid4(),
        name="Enterprise Locked Org",
        slug="locked-enterprise",
        plan="enterprise",
        api_key=_make_fake_org_api_key("locked_fixture"),
        eval_count=0,
        eval_limit=1000,
        sso_enabled=True,
        sso_provider="clerk_saml",
        sso_entity_id="locked-enterprise",
        sso_domains="example.com",
        sso_auto_join=False,
        sso_default_role="viewer",
    )
    db_session.add(enterprise_org)
    await db_session.commit()

    _patch_clerk_api(monkeypatch, email="locked@example.com", user_id="user_locked")
    token = _make_fake_jwt(
        {
            "sub": "user_locked",
            "sid": "sess_user_locked",
            "organization_slug": "locked-enterprise",
        }
    )

    response = await client.get(
        "/v1/clerk/api-key",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
