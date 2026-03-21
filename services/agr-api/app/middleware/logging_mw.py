"""Request ID logging middleware.

Generates a short unique ID for every incoming request and:
  - Stores it in a ContextVar accessible to all log calls
  - Injects it into the response as X-Request-ID header
  - Logs method + path + status + latency on completion

Usage in log lines:
    logger.info("Policy evaluated", extra={"request_id": get_request_id()})
    # Or just call logger.info(...) — the formatter adds the request_id automatically.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import Request, Response

# Module-level ContextVar — each async task gets its own value
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="—")


def get_request_id() -> str:
    """Return the current request ID, or '—' outside of a request context."""
    return _request_id_ctx.get()


class RequestIDFormatter(logging.Formatter):
    """Log formatter that prepends [request_id] to every message."""

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = _request_id_ctx.get("—")
        return super().format(record)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Assigns a unique request_id to every request and logs completion."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = uuid.uuid4().hex[:12]
        token = _request_id_ctx.set(rid)
        request.state.request_id = rid
        start = time.perf_counter()

        try:
            response = await call_next(request)
            elapsed_ms = (time.perf_counter() - start) * 1000
            response.headers["X-Request-ID"] = rid
            logging.getLogger("agr.access").info(
                "%s %s %d %.1fms",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
            return response
        finally:
            # M6: always reset ContextVar — even if call_next raises, so stale
            # request_id never leaks into subsequent requests on the same task
            _request_id_ctx.reset(token)
