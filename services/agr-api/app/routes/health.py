"""Health check and metrics endpoints.

GET /health       — lightweight liveness probe (always 200 if process is alive)
GET /health/ready — readiness probe: checks DB, Redis, Cedar CLI; returns
                    200 if healthy or 503 if any dependency is down.
GET /metrics      — Prometheus metrics in text format (all registered counters).
"""

import json
import shutil

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe — returns 200 if the process is running."""
    return HealthResponse(status="ok")


@router.get("/health/ready")
async def health_ready() -> Response:
    """Readiness probe — verifies DB, Redis, and Cedar CLI availability.

    Returns 200 {"status": "ok", "checks": {...}} if all critical deps are healthy.
    Returns 503 {"status": "degraded", "checks": {...}} if any critical check fails.
    Cedar CLI absence is advisory — it degrades gracefully to Python fallback.
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
            # Redis down is degraded but not fatal (policy eval has DB fallback)
            checks["redis"] = f"degraded: {exc}"

    # --- Cedar CLI ---
    # W1.1: when the operator has declared the CLI a hard requirement, treat
    # its absence as a readiness failure (Kubernetes / load balancers will then
    # stop routing traffic to this pod). Otherwise it's purely advisory.
    from app.config import settings as _settings

    cedar_path = shutil.which("cedar")
    if cedar_path:
        checks["cedar_cli"] = "available"
    else:
        checks["cedar_cli"] = "not_found (python_fallback_active)"
        if _settings.cedar_require_cli and not _settings.allow_cedar_fallback_in_prod:
            healthy = False
            checks["cedar_cli"] = "not_found (CEDAR_REQUIRE_CLI=true)"

    return Response(
        content=json.dumps({"status": "ok" if healthy else "degraded", "checks": checks}),
        status_code=200 if healthy else 503,
        media_type="application/json",
    )


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    """Prometheus-format metrics endpoint.

    Exposes:
      agr_evaluations_total        — by decision label
      agr_risk_score               — histogram (0–100 buckets)
      agr_approval_decisions_total — by decision label
      agr_policy_changes_total     — by operation label
      agr_webhook_deliveries_total — by status label
    """
    from app.services.metrics_service import get_metrics_output

    body, content_type = get_metrics_output()
    return Response(content=body, media_type=content_type)
