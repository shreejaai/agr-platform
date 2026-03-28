import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.database import (
    async_session_factory,
    reset_current_org_id,
    set_current_org_id,
    set_session_rls,
)
from app.models import ApiKey, AuthSession, Organization

logger = logging.getLogger(__name__)

UNPROTECTED_PATHS = {
    "/health",
    "/health/ready",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/v1/meta",
    "/v1/approvals/decide",
    "/v1/slack/interactivity",
    "/v1/clerk/webhook",
    "/v1/clerk/api-key",  # uses Clerk session JWT, not agr_sk_ key
    "/v1/stream/evaluations",
}

# Human-readable hints differ between SaaS and on-prem deployments
_HINT_MISSING = {
    "saas": "Get your API key at https://dashboard.agr.dev/settings",
    "onprem": "Copy the API key printed to Docker logs on first start, "
    "or contact your AGR administrator.",
}
_HINT_FORMAT = {
    "saas": "Tokens start with agr_sk_ or agr_usr_. Check https://dashboard.agr.dev/settings",
    "onprem": (
        "Tokens start with agr_sk_ or agr_usr_. " "Copy the key from Docker logs on first start."
    ),
}
_HINT_NOT_FOUND = {
    "saas": "API key not found. Verify your key at https://dashboard.agr.dev/settings",
    "onprem": "API key not found. Contact your AGR administrator.",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in UNPROTECTED_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        mode = settings.deployment_mode

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            hint = _HINT_MISSING.get(mode, _HINT_MISSING["saas"])
            # M1: use json.dumps so hint text never breaks the JSON structure
            return Response(
                content=json.dumps(
                    {
                        "error": "unauthorized",
                        "message": (
                            "Missing or invalid Authorization header. "
                            f"Provide a Bearer token. {hint}"
                        ),
                    }
                ),
                status_code=401,
                media_type="application/json",
            )

        api_key = auth_header.removeprefix("Bearer ").strip()
        if not (api_key.startswith("agr_sk_") or api_key.startswith("agr_usr_")):
            hint = _HINT_FORMAT.get(mode, _HINT_FORMAT["saas"])
            return Response(
                content=json.dumps(
                    {
                        "error": "unauthorized",
                        "message": f"Invalid API key format. {hint}",
                    }
                ),
                status_code=401,
                media_type="application/json",
            )

        auth_lookup = await self._lookup_org(api_key)
        if auth_lookup is None:
            hint = _HINT_NOT_FOUND.get(mode, _HINT_NOT_FOUND["saas"])
            return Response(
                content=json.dumps({"error": "unauthorized", "message": hint}),
                status_code=401,
                media_type="application/json",
            )

        org, role, auth_mode, auth_expires_at, scopes = auth_lookup
        request.state.org_id = org.id
        request.state.org = org
        request.state.role = role
        request.state.auth_mode = auth_mode
        request.state.auth_expires_at = auth_expires_at
        request.state.scopes = scopes
        org_token = set_current_org_id(org.id)
        try:
            return await call_next(request)
        finally:
            reset_current_org_id(org_token)

    @staticmethod
    async def _lookup_org(
        api_key: str,
    ) -> tuple[Organization, str, str, datetime | None, list[str]] | None:
        async with async_session_factory() as session:
            if api_key.startswith("agr_sk_"):
                now = datetime.now(UTC)
                key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
                scoped_result = await session.execute(
                    select(ApiKey, Organization)
                    .join(Organization, Organization.id == ApiKey.org_id)
                    .where(
                        ApiKey.key_hash == key_hash,
                        ApiKey.revoked.is_(False),
                        (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now),
                    )
                )
                scoped_row = scoped_result.one_or_none()
                if scoped_row is not None:
                    scoped_key, scoped_org = scoped_row
                    scoped_key.last_used_at = now
                    await session.commit()
                    return (
                        scoped_org,
                        scoped_org.role,
                        "scoped_api_key",
                        None,
                        list(scoped_key.scopes or ["*"]),
                    )

                result = await session.execute(
                    select(Organization).where(Organization.api_key == api_key)
                )
                org = result.scalar_one_or_none()
                if org is None:
                    return None
                return org, org.role, "api_key", None, ["*"]

            result = await session.execute(
                select(AuthSession, Organization)
                .join(Organization, Organization.id == AuthSession.org_id)
                .where(
                    AuthSession.token == api_key,
                    AuthSession.expires_at > datetime.now(UTC),
                )
            )
            row = result.one_or_none()
            if row is None:
                return None
            auth_session, org = row
            if org is None:
                return None
            return org, auth_session.role, "sso_session", auth_session.expires_at, ["*"]


async def set_rls_org(session: object, org_id: UUID) -> None:
    """Set the RLS context for the current session.

    Prefer the session factories in app.database for new code so the RLS
    context is applied before any queries run on the session.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    if isinstance(session, AsyncSession):
        await set_session_rls(session, org_id)


def require_scope(scope: str) -> Callable[[Request], Awaitable[None]]:
    async def _check(request: Request) -> None:
        scopes: list[str] = getattr(request.state, "scopes", ["*"])
        if "*" in scopes or scope in scopes:
            return
        raise HTTPException(status_code=403, detail=f"Missing required scope: {scope}")

    return _check


async def authenticate_token(
    api_key: str,
) -> tuple[Organization, str, str, datetime | None, list[str]] | None:
    return await AuthMiddleware._lookup_org(api_key)
