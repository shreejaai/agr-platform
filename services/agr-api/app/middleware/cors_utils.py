from fastapi import Request, Response

from app.config import settings


def apply_cors_headers(request: Request, response: Response) -> Response:
    """Mirror the app's CORS policy onto early middleware responses.

    FastAPI's CORSMiddleware handles normal route responses and preflights, but
    auth/rate-limit middleware can sometimes short-circuit before the browser
    sees the expected CORS headers. Applying the same policy here keeps browser
    clients from turning valid 401/429 responses into opaque CORS failures.
    """

    origin = request.headers.get("origin")
    if not origin:
        return response

    if settings.cors_uses_wildcard:
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    if origin not in settings.cors_origins:
        return response

    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    if settings.cors_allow_credentials:
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response
