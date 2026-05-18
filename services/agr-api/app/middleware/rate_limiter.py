from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import settings
from app.middleware.auth import UNPROTECTED_PATHS
from app.middleware.cors_utils import apply_cors_headers
from app.services.redis_service import check_rate_limit, get_redis_client

_RATE_LIMITED_PATHS = frozenset({"/v1/evaluate"})
_REDIS_CLOSED_RETRY_SECONDS = 5


class RateLimiterMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            not settings.rate_limit_enabled
            or request.method == "OPTIONS"
            or request.url.path in UNPROTECTED_PATHS
            or request.url.path not in _RATE_LIMITED_PATHS
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

        # W3.3 — when Redis is down, decide based on configured fail mode.
        if not result.redis_available:
            fail_mode = (settings.rate_limit_fail_mode or "open").lower()
            try:
                from app.services.metrics_service import record_rate_limit_redis_unavailable

                record_rate_limit_redis_unavailable(fail_mode)
            except Exception:
                pass
            import logging

            logging.getLogger(__name__).critical(
                "Rate limiter: Redis unavailable (org=%s, fail_mode=%s)", org_id, fail_mode
            )
            if fail_mode == "closed":
                return apply_cors_headers(
                    request,
                    JSONResponse(
                        status_code=503,
                        content={
                            "error": "rate_limit_unavailable",
                            "message": ("Rate limiter dependency is unavailable; retry shortly."),
                        },
                        headers={"Retry-After": str(_REDIS_CLOSED_RETRY_SECONDS)},
                    ),
                )

        if not result.allowed:
            retry_after = result.retry_after or 0
            try:
                from app.services.metrics_service import record_rate_limit_drop

                record_rate_limit_drop()
            except Exception:
                pass
            return apply_cors_headers(
                request,
                JSONResponse(
                    status_code=429,
                    content={"error": "rate_limited", "message": "Rate limit exceeded."},
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(result.reset_at),
                    },
                ),
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(result.reset_at)
        return response
