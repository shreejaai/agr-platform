"""Health check endpoints.

GET /health       — lightweight liveness probe (always 200 if process is alive)
GET /health/ready — readiness probe: checks DB and Redis connectivity, returns
                    200 if healthy or 503 if any dependency is down.
                    Used by load balancers to stop routing traffic to broken instances.
"""

import json

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe — returns 200 if the process is running."""
    return HealthResponse(status="ok")


@router.get("/health/ready")
async def health_ready() -> Response:
    """Readiness probe — verifies DB and Redis are reachable.

    Returns 200 {"status": "ok", "checks": {...}} if all dependencies are healthy.
    Returns 503 {"status": "degraded", "checks": {...}} if any check fails.
    Load balancers should use this endpoint, not /health.
    """
    from app.database import engine
    from app.services.redis_service import _get_redis

    checks: dict[str, str] = {}
    healthy = True

    # --- Database ping ---
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"
        healthy = False

    # --- Redis ping ---
    r = _get_redis()
    if r is None:
        checks["redis"] = "not_configured"
    else:
        try:
            await r.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"
            healthy = False

    return Response(
        content=json.dumps({"status": "ok" if healthy else "degraded", "checks": checks}),
        status_code=200 if healthy else 503,
        media_type="application/json",
    )
