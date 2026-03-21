"""Clerk webhook handler — POST /v1/clerk/webhook.

Receives Svix-signed events from Clerk. On user.created, creates an
Organization row and seeds the 5 default Cedar policies.

This endpoint is in UNPROTECTED_PATHS — Svix signature is the auth mechanism.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Organization
from app.schemas import ClerkApiKeyResponse
from app.services.org_service import seed_default_policies
from app.services.redis_service import _get_redis  # noqa: PLC2701

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


_CLERK_API_KEY_RATE_WINDOW = 60  # 1-minute window
_CLERK_API_KEY_RATE_MAX = 10  # max 10 lookups per IP per minute


async def _clerk_api_key_rate_limit(ip: str) -> bool:
    """Return True (blocked) if the IP has exceeded the rate limit.

    S5: /v1/clerk/api-key is unauthenticated — without rate limiting an
    attacker can enumerate Clerk user IDs to harvest AGR API keys.
    Fails open if Redis is unavailable.
    """
    r = _get_redis()
    if r is None:
        return False
    try:
        key = f"clerk_apikey_limit:{ip}"
        count: int = await r.incr(key)
        if count == 1:
            await r.expire(key, _CLERK_API_KEY_RATE_WINDOW)
        if count > _CLERK_API_KEY_RATE_MAX:
            logger.warning("Clerk API key rate limit exceeded for IP %s (count=%d)", ip, count)
            return True
        return False
    except Exception as exc:
        logger.debug("Clerk API key rate limit check failed (allowing through): %s", exc)
        return False


@router.get("/clerk/api-key", response_model=ClerkApiKeyResponse)
async def get_api_key_from_clerk_session(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ClerkApiKeyResponse | Response:
    """Exchange a Clerk session JWT for the org's AGR API key.

    The dashboard calls this after login to auto-populate the API key,
    eliminating the need to manually paste it in Settings.

    Requires CLERK_SECRET_KEY to be configured. Returns 401 if the
    Clerk session is invalid or the org does not exist yet.
    """
    # S5: rate-limit by client IP to prevent API key enumeration
    client_ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    if await _clerk_api_key_rate_limit(client_ip):
        return Response(
            content='{"error":"rate_limited","message":"Too many requests. Try again later."}',
            status_code=429,
            media_type="application/json",
        )

    if not settings.clerk_secret_key:
        return Response(
            content='{"error":"clerk_not_configured","message":"CLERK_SECRET_KEY is not set."}',
            status_code=503,
            media_type="application/json",
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return Response(
            content='{"error":"unauthorized","message":"Missing Clerk session token."}',
            status_code=401,
            media_type="application/json",
        )

    token = auth_header.removeprefix("Bearer ").strip()

    # L7: JWT signature is intentionally NOT verified locally. We extract
    # session_id from the payload and then verify it with the Clerk Backend API
    # (GET /v1/sessions/{session_id}). The API call is the auth mechanism —
    # Clerk rejects invalid/expired sessions server-side. Local signature
    # verification would require caching Clerk's JWKS and handling key rotation,
    # adding complexity with no security benefit since we call Clerk anyway.
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("not a JWT")
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        user_id: str = payload["sub"]
        session_id: str = payload["sid"]
    except Exception:
        return Response(
            content='{"error":"unauthorized","message":"Invalid Clerk session token."}',
            status_code=401,
            media_type="application/json",
        )

    # Verify the session is active via Clerk Backend API
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"https://api.clerk.com/v1/sessions/{session_id}",
                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            )
        if r.status_code != 200:
            return Response(
                content='{"error":"unauthorized","message":"Clerk session not found."}',
                status_code=401,
                media_type="application/json",
            )
        clerk_session = r.json()
        if clerk_session.get("status") != "active":
            return Response(
                content='{"error":"unauthorized","message":"Clerk session is not active."}',
                status_code=401,
                media_type="application/json",
            )
        if clerk_session.get("user_id") != user_id:
            return Response(
                content='{"error":"unauthorized","message":"Session user mismatch."}',
                status_code=401,
                media_type="application/json",
            )
    except httpx.RequestError as exc:
        logger.warning("Could not reach Clerk API: %s", exc)
        return Response(
            content='{"error":"clerk_unavailable","message":"Could not verify session."}',
            status_code=503,
            media_type="application/json",
        )

    # Look up org by Clerk user_id (stored as slug)
    result = await session.execute(select(Organization).where(Organization.slug == user_id))
    org = result.scalar_one_or_none()

    if org is None:
        # Org not found — webhook may not have fired yet (common in local dev where
        # localhost is unreachable from Clerk's servers). Auto-provision the org now
        # using the verified Clerk user data so the user can proceed immediately.
        logger.info("Auto-provisioning org for verified Clerk user %s", user_id)
        try:
            # Fetch user profile from Clerk to get name/email for the org
            async with httpx.AsyncClient(timeout=5.0) as client:
                user_resp = await client.get(
                    f"https://api.clerk.com/v1/users/{user_id}",
                    headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
                )
            if user_resp.status_code == 200:
                user_data = user_resp.json()
                email_addresses = user_data.get("email_addresses", [])
                email = email_addresses[0]["email_address"] if email_addresses else ""
                first_name = user_data.get("first_name") or ""
                last_name = user_data.get("last_name") or ""
                name = f"{first_name} {last_name}".strip() or email or user_id
            else:
                name = user_id
        except httpx.RequestError:
            name = user_id

        try:
            org = Organization(
                id=uuid.uuid4(),
                name=name,
                slug=user_id,
                plan="developer",
                api_key="agr_sk_" + secrets.token_hex(24),
                eval_count=0,
                eval_limit=100,
                eval_week_start=datetime.now(UTC),
            )
            session.add(org)
            await session.flush()
            await seed_default_policies(session, org.id)
            logger.info("Auto-provisioned org %s for Clerk user %s", org.id, user_id)
        except IntegrityError:
            await session.rollback()
            # Another request raced us — re-fetch the row that was just created
            result = await session.execute(
                select(Organization).where(Organization.slug == user_id)
            )
            org = result.scalar_one_or_none()
            if org is None:
                return Response(
                    content='{"error":"org_error","message":"Failed to provision organisation."}',
                    status_code=500,
                    media_type="application/json",
                )

    return ClerkApiKeyResponse(
        api_key=org.api_key,
        org_id=str(org.id),
        org_name=org.name,
    )


@router.post("/clerk/webhook", status_code=200)
async def clerk_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Handle Clerk webhook events.

    Verifies the Svix signature (skipped in dev when clerk_webhook_secret is empty).
    Creates org + seeds default policies on user.created.
    Idempotent: duplicate user_id returns 200 without creating a second row.
    """
    raw_body = await request.body()

    # --- Svix signature verification ---
    if settings.clerk_webhook_secret:
        try:
            from svix.webhooks import Webhook

            wh = Webhook(settings.clerk_webhook_secret)
            headers = {
                "svix-id": request.headers.get("svix-id", ""),
                "svix-timestamp": request.headers.get("svix-timestamp", ""),
                "svix-signature": request.headers.get("svix-signature", ""),
            }
            wh.verify(raw_body, headers)
        except Exception as exc:
            # Catch both WebhookVerificationError and import errors gracefully
            logger.warning("Svix webhook verification failed: %s", exc)
            return Response(
                content=(
                    '{"error":"invalid_signature",'
                    '"message":"Webhook signature verification failed."}'
                ),
                status_code=400,
                media_type="application/json",
            )
    else:
        logger.debug("CLERK_WEBHOOK_SECRET not set — skipping Svix signature verification.")

    # --- Parse payload ---
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return Response(
            status_code=400, content='{"error":"invalid_json"}', media_type="application/json"
        )

    event_type = payload.get("type")
    if event_type != "user.created":
        logger.debug("Ignoring Clerk event type: %s", event_type)
        return Response(status_code=200)

    data = payload.get("data", {})
    clerk_user_id: str = data.get("id", "")
    if not clerk_user_id:
        logger.warning("user.created payload missing data.id — ignoring.")
        return Response(status_code=200)

    email_addresses = data.get("email_addresses", [])
    email = email_addresses[0]["email_address"] if email_addresses else ""
    first_name = data.get("first_name") or ""
    last_name = data.get("last_name") or ""
    name = f"{first_name} {last_name}".strip() or email or clerk_user_id

    api_key = "agr_sk_" + secrets.token_hex(24)

    # --- Create org + seed policies ---
    try:
        org = Organization(
            id=uuid.uuid4(),
            name=name,
            slug=clerk_user_id,  # stable, unique, safe for retries
            plan="developer",
            api_key=api_key,
            eval_count=0,
            eval_limit=100,
            eval_week_start=datetime.now(UTC),  # L3: always UTC-aware on creation
        )
        session.add(org)
        await session.flush()  # get org.id before seeding

        await seed_default_policies(session, org.id)

        logger.info("Created org for Clerk user %s (org_id=%s)", clerk_user_id, org.id)
    except IntegrityError as exc:
        await session.rollback()
        # H8: only silently ignore a unique-constraint violation on the slug
        # column. Any other integrity error (e.g. api_key collision, which
        # would signal a secrets.token_hex PRNG failure) must be re-raised.
        #
        # Detection strategy works for both PostgreSQL (pgcode=23505) and
        # SQLite (error message contains "UNIQUE constraint failed" + "slug").
        orig = getattr(exc, "orig", None)
        pgcode = getattr(orig, "pgcode", None)
        orig_str = str(orig or exc).lower()
        is_unique_violation = pgcode == "23505" or (
            "unique constraint" in orig_str or "unique" in orig_str
        )
        is_slug_column = "slug" in orig_str
        if is_unique_violation and is_slug_column:
            logger.info("Duplicate Clerk user %s — org already exists, ignoring.", clerk_user_id)
            return Response(status_code=200)
        # Unexpected integrity error — log and re-raise
        logger.error(
            "Unexpected IntegrityError creating org for Clerk user %s: %s",
            clerk_user_id,
            exc,
        )
        raise

    return Response(status_code=200)
