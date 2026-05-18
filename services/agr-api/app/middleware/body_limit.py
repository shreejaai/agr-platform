"""Reject oversized request bodies before they hit route handlers.

Rationale:
  FastAPI / Starlette will happily buffer arbitrarily large request bodies
  into memory before invoking the handler, which is a trivial DoS vector. We
  cap every request at ``settings.max_request_body_bytes`` (default 256 KB)
  and respond with 413 + a structured JSON body and the early CORS headers
  applied so browser clients see the same shape as other 4xx responses.

Strategy:
  1. Trust ``Content-Length`` when present — short-circuit fast.
  2. Wrap the ASGI ``receive`` callable to count bytes as they stream in,
     so chunked / unknown-length uploads are also bounded.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.middleware.cors_utils import apply_cors_headers


def _too_large_response(request: Request, limit: int) -> Response:
    return apply_cors_headers(
        request,
        Response(
            content=json.dumps(
                {
                    "error": "payload_too_large",
                    "message": (
                        f"Request body exceeds {limit} bytes. "
                        "Increase MAX_REQUEST_BODY_BYTES if this is expected, or "
                        "split the payload into smaller requests."
                    ),
                    "limit_bytes": limit,
                }
            ),
            status_code=413,
            media_type="application/json",
        ),
    )


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Enforces a hard cap on request body size."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        limit = settings.max_request_body_bytes
        # Defensive: if misconfigured to <=0 we just skip (config validator
        # blocks this at startup in production).
        if limit <= 0:
            return await call_next(request)

        # Fast path: declared content length we can trust without buffering.
        cl_header = request.headers.get("content-length")
        if cl_header is not None:
            try:
                if int(cl_header) > limit:
                    return _too_large_response(request, limit)
            except ValueError:
                # malformed header — let downstream parsing reject it
                pass

        # Slow path: wrap receive to count bytes for chunked uploads.
        received_bytes = 0
        original_receive = request.receive

        async def counting_receive() -> dict:  # type: ignore[type-arg]
            nonlocal received_bytes
            message = await original_receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"") or b""
                received_bytes += len(body)
                if received_bytes > limit:
                    # Mark the stream complete so the handler doesn't hang
                    # waiting for further chunks; the response is sent below.
                    raise _BodyTooLarge(limit)
            return message

        # Re-bind the wrapped receive onto the request scope so downstream
        # body parsing sees the byte-counted stream.
        request._receive = counting_receive  # type: ignore[attr-defined]

        try:
            return await call_next(request)
        except _BodyTooLarge as exc:
            return _too_large_response(request, exc.limit)


class _BodyTooLarge(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"body exceeded {limit} bytes")
        self.limit = limit
