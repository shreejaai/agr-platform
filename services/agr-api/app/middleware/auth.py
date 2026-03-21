import json
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import select, text
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.database import async_session_factory
from app.models import Organization

logger = logging.getLogger(__name__)

UNPROTECTED_PATHS = {
    "/health",
    "/health/ready",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/v1/approvals/decide",
    "/v1/clerk/webhook",
    "/v1/clerk/api-key",  # uses Clerk session JWT, not agr_sk_ key
}

# Human-readable hints differ between SaaS and on-prem deployments
_HINT_MISSING = {
    "saas": "Get your API key at https://dashboard.agr.dev/settings",
    "onprem": "Copy the API key printed to Docker logs on first start, "
    "or contact your AGR administrator.",
}
_HINT_FORMAT = {
    "saas": "Keys start with agr_sk_. Check https://dashboard.agr.dev/settings",
    "onprem": "Keys start with agr_sk_. Copy the key from Docker logs on first start.",
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
        if not api_key.startswith("agr_sk_"):
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

        org = await self._lookup_org(api_key)
        if org is None:
            hint = _HINT_NOT_FOUND.get(mode, _HINT_NOT_FOUND["saas"])
            return Response(
                content=json.dumps({"error": "unauthorized", "message": hint}),
                status_code=401,
                media_type="application/json",
            )

        request.state.org_id = org.id
        request.state.org = org
        return await call_next(request)

    @staticmethod
    async def _lookup_org(api_key: str) -> Organization | None:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Organization).where(Organization.api_key == api_key)
            )
            return result.scalar_one_or_none()


async def set_rls_org(session: object, org_id: UUID) -> None:
    """Set the RLS context for the current session."""
    from sqlalchemy.ext.asyncio import AsyncSession

    if isinstance(session, AsyncSession):
        await session.execute(text(f"SET LOCAL app.current_org = '{org_id}'"))
