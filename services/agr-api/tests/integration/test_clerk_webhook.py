"""Integration tests for POST /v1/clerk/webhook.

Svix signature verification is bypassed in tests because CLERK_WEBHOOK_SECRET
defaults to "" — the handler skips verification gracefully in that case.
"""

import pytest
from app.models import Organization, Policy
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WEBHOOK_URL = "/v1/clerk/webhook"


def _user_created_payload(
    user_id: str = "user_abc123",
    email: str = "alice@example.com",
    first_name: str = "Alice",
    last_name: str = "Smith",
) -> dict[str, object]:
    return {
        "type": "user.created",
        "data": {
            "id": user_id,
            "email_addresses": [{"email_address": email}],
            "first_name": first_name,
            "last_name": last_name,
        },
    }


# ---------------------------------------------------------------------------
# Core creation flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_created_returns_200(client: AsyncClient, db_session: AsyncSession) -> None:
    resp = await client.post(_WEBHOOK_URL, json=_user_created_payload())
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_user_created_creates_org_in_db(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(_WEBHOOK_URL, json=_user_created_payload(user_id="user_neworg1"))

    result = await db_session.execute(
        select(Organization).where(Organization.slug == "user_neworg1")
    )
    org = result.scalar_one_or_none()
    assert org is not None
    assert org.name == "Alice Smith"
    assert org.plan == "developer"
    assert org.api_key.startswith("agr_sk_")
    assert len(org.api_key) == 55  # "agr_sk_" (7) + 48 hex chars


@pytest.mark.asyncio
async def test_user_created_seeds_5_default_policies(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(_WEBHOOK_URL, json=_user_created_payload(user_id="user_policies1"))

    result = await db_session.execute(
        select(Organization).where(Organization.slug == "user_policies1")
    )
    org = result.scalar_one_or_none()
    assert org is not None

    pol_result = await db_session.execute(select(Policy).where(Policy.org_id == org.id))
    policies = pol_result.scalars().all()
    names = {p.name for p in policies}
    assert "Block production DB drops" in names
    assert "Require approval for production deploys" in names
    assert "Block writes to secrets/env files" in names
    assert "Allow staging auto-deploy" in names
    assert "Allow source code writes" in names
    assert len(policies) == 5


@pytest.mark.asyncio
async def test_user_created_name_derived_from_first_last(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(
        _WEBHOOK_URL,
        json=_user_created_payload(user_id="user_name1", first_name="Bob", last_name="Jones"),
    )
    result = await db_session.execute(select(Organization).where(Organization.slug == "user_name1"))
    org = result.scalar_one_or_none()
    assert org is not None
    assert org.name == "Bob Jones"


@pytest.mark.asyncio
async def test_user_created_name_falls_back_to_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    payload = {
        "type": "user.created",
        "data": {
            "id": "user_nofullname",
            "email_addresses": [{"email_address": "noname@example.com"}],
            "first_name": "",
            "last_name": "",
        },
    }
    await client.post(_WEBHOOK_URL, json=payload)
    result = await db_session.execute(
        select(Organization).where(Organization.slug == "user_nofullname")
    )
    org = result.scalar_one_or_none()
    assert org is not None
    assert org.name == "noname@example.com"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_user_id_is_idempotent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Sending the same user.created twice must return 200 both times."""
    payload = _user_created_payload(user_id="user_dup1")
    resp1 = await client.post(_WEBHOOK_URL, json=payload)
    resp2 = await client.post(_WEBHOOK_URL, json=payload)
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    result = await db_session.execute(select(Organization).where(Organization.slug == "user_dup1"))
    orgs = result.scalars().all()
    assert len(orgs) == 1  # only one org row despite two webhook calls


# ---------------------------------------------------------------------------
# Auth bypass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_requires_no_auth_header(client: AsyncClient) -> None:
    """Webhook must succeed with no Authorization header."""
    resp = await client.post(
        _WEBHOOK_URL,
        json=_user_created_payload(user_id="user_noauth"),
        # no headers= argument → no Authorization header
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Non-user.created events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_user_created_event_returns_200_no_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await client.post(
        _WEBHOOK_URL,
        json={"type": "user.deleted", "data": {"id": "user_deleted1"}},
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(Organization).where(Organization.slug == "user_deleted1")
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_session_created_event_ignored(client: AsyncClient) -> None:
    resp = await client.post(
        _WEBHOOK_URL,
        json={"type": "session.created", "data": {}},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_email_addresses_does_not_crash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    payload = {
        "type": "user.created",
        "data": {
            "id": "user_noemail",
            "email_addresses": [],
            "first_name": "Ghost",
            "last_name": "",
        },
    }
    resp = await client.post(_WEBHOOK_URL, json=payload)
    assert resp.status_code == 200
    result = await db_session.execute(
        select(Organization).where(Organization.slug == "user_noemail")
    )
    org = result.scalar_one_or_none()
    assert org is not None
    assert org.name == "Ghost"


@pytest.mark.asyncio
async def test_invalid_json_returns_400(client: AsyncClient) -> None:
    resp = await client.post(
        _WEBHOOK_URL,
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_missing_data_id_returns_200_no_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await client.post(
        _WEBHOOK_URL,
        json={"type": "user.created", "data": {"email_addresses": []}},
    )
    assert resp.status_code == 200
