import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import select, text
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import async_session_factory
from app.models import Organization

logger = logging.getLogger(__name__)

UNPROTECTED_PATHS = {
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/v1/approvals/decide",
    "/v1/clerk/webhook",
    "/v1/clerk/api-key",  # uses Clerk session JWT, not agr_sk_ key
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in UNPROTECTED_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return Response(
                content='{"error":"unauthorized","message":"Missing or invalid Authorization '
                "header. Provide a Bearer token. Get your API key at "
                'https://dashboard.agr.dev/settings"}',
                status_code=401,
                media_type="application/json",
            )

        api_key = auth_header.removeprefix("Bearer ").strip()
        if not api_key.startswith("agr_sk_"):
            return Response(
                content='{"error":"unauthorized","message":"Invalid API key format. '
                'Keys start with agr_sk_. Check https://dashboard.agr.dev/settings"}',
                status_code=401,
                media_type="application/json",
            )

        org = await self._lookup_org(api_key)
        if org is None:
            return Response(
                content='{"error":"unauthorized","message":"API key not found. '
                'Verify your key at https://dashboard.agr.dev/settings"}',
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
