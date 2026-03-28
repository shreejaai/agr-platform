import re
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_VERSION_HEADER_RE = re.compile(r"\bv(?P<version>\d+)\b")
_URL_PREFIX_RE = re.compile(r"^/v(?P<version>\d+)(?:/|$)")


class VersionNegotiationMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.api_version = _resolve_version(request)
        response = await call_next(request)
        response.headers["AGR-API-Version"] = request.state.api_version
        return response


def _resolve_version(request: Request) -> str:
    header = request.headers.get("Accept-Version", "")
    header_match = _VERSION_HEADER_RE.search(header)
    if header_match is not None:
        return f"v{header_match.group('version')}"

    path_match = _URL_PREFIX_RE.match(request.url.path)
    if path_match is not None:
        return f"v{path_match.group('version')}"

    return "v1"


def mark_deprecated(response: Response, sunset_date: str, successor_url: str) -> Response:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = sunset_date
    response.headers["Link"] = f'<{successor_url}>; rel="successor-version"'
    return response
