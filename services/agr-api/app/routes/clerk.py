"""Clerk webhook handler — POST /v1/clerk/webhook.

Receives Svix-signed events from Clerk. On user.created, creates an
Organization row and seeds the 5 default Cedar policies.

This endpoint is in UNPROTECTED_PATHS — Svix signature is the auth mechanism.
"""

import json
import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Organization
from app.services.org_service import seed_default_policies

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


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
            from svix.webhooks import Webhook, WebhookVerificationError  # type: ignore[import]

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
                content='{"error":"invalid_signature","message":"Webhook signature verification failed."}',
                status_code=400,
                media_type="application/json",
            )
    else:
        logger.debug("CLERK_WEBHOOK_SECRET not set — skipping Svix signature verification.")

    # --- Parse payload ---
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return Response(status_code=400, content='{"error":"invalid_json"}', media_type="application/json")

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
            slug=clerk_user_id,   # stable, unique, safe for retries
            plan="developer",
            api_key=api_key,
            eval_count=0,
            eval_limit=10000,
        )
        session.add(org)
        await session.flush()   # get org.id before seeding

        await seed_default_policies(session, org.id)

        logger.info(
            "Created org for Clerk user %s (org_id=%s)", clerk_user_id, org.id
        )
    except IntegrityError:
        # Duplicate slug = same Clerk user already registered. Return 200 so
        # Clerk stops retrying.
        logger.info("Duplicate Clerk user %s — org already exists, ignoring.", clerk_user_id)
        return Response(status_code=200)

    return Response(status_code=200)
