from app.middleware.versioning import VersionNegotiationMiddleware
from fastapi import Response
from starlette.requests import Request


def _request(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "scheme": "http",
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


async def test_version_middleware_sets_request_state_from_accept_version() -> None:
    middleware = VersionNegotiationMiddleware(app=lambda scope, receive, send: None)
    request = _request(
        "/v1/evaluate",
        headers=[(b"accept-version", b"application/vnd.agr.v1+json")],
    )

    async def call_next(inner_request: Request) -> Response:
        assert inner_request.state.api_version == "v1"
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.headers["AGR-API-Version"] == "v1"


async def test_version_middleware_falls_back_to_url_prefix() -> None:
    middleware = VersionNegotiationMiddleware(app=lambda scope, receive, send: None)
    request = _request("/v1/meta")

    async def call_next(inner_request: Request) -> Response:
        assert inner_request.state.api_version == "v1"
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.headers["AGR-API-Version"] == "v1"
