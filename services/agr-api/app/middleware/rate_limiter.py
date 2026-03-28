from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import settings
from app.middleware.auth import UNPROTECTED_PATHS
from app.services.redis_service import check_rate_limit, get_redis_client


class RateLimiterMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            not settings.rate_limit_enabled
            or request.method == "OPTIONS"
            or request.url.path in UNPROTECTED_PATHS
        ):
            return await call_next(request)

        org_id = getattr(request.state, "org_id", None)
        if org_id is None:
            return await call_next(request)

        result = await check_rate_limit(
            get_redis_client(),
            str(org_id),
            settings.rate_limit_per_second,
            settings.rate_limit_burst,
        )
        limit = settings.rate_limit_per_second

        if not result.allowed:
            retry_after = result.retry_after or 0
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "message": "Rate limit exceeded."},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(result.reset_at),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(result.reset_at)
        return response
