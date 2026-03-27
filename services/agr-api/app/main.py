"""FastAPI application — AGR API gateway."""

import logging
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.config import settings
from app.database import async_session_factory
from app.middleware.auth import AuthMiddleware
from app.middleware.logging_mw import RequestIDFormatter, RequestLoggingMiddleware
from app.models import Organization
from app.routes import (
    agents,
    approvals,
    audit,
    clerk,
    evaluate,
    health,
    org,
    policies,
    slack,
    webhooks,
)
from app.routes.compliance import router as compliance_router
from app.routes.copilot import router as copilot_router
from app.routes.members import router as members_router
from app.routes.risk_config import router as risk_config_router
from app.routes.usage import router as usage_router

# Structured logging with request_id injected by RequestIDFormatter
_handler = logging.StreamHandler()
_handler.setFormatter(
    RequestIDFormatter("%(asctime)s [%(request_id)s] %(name)s %(levelname)s %(message)s")
)
logging.basicConfig(
    level=logging.INFO if settings.env == "production" else logging.DEBUG,
    handlers=[_handler],
    force=True,
)

logger = logging.getLogger(__name__)


async def _onprem_bootstrap() -> None:
    """Validate license and auto-create the single org on first start (onprem mode)."""
    from app.license import validate_license
    from app.services.org_service import seed_default_policies

    # Hard stop if license is invalid or expired
    license_payload = validate_license(settings.license_key)

    async with async_session_factory() as session:
        count = await session.scalar(select(func.count(Organization.id)))
        if count and count > 0:
            logger.info("AGR on-prem: org already bootstrapped, skipping init.")
            return

        api_key = "agr_sk_" + secrets.token_hex(24)
        eval_limit = int(str(license_payload.get("evals") or 0))

        org_obj = Organization(
            id=uuid.uuid4(),
            name=settings.onprem_org_name,
            slug="onprem",
            plan="enterprise",
            api_key=api_key,
            eval_count=0,
            eval_limit=eval_limit,
            eval_week_start=datetime.now(UTC),  # L3: always UTC-aware on creation
        )
        session.add(org_obj)
        await session.flush()
        await seed_default_policies(session, org_obj.id)
        await session.commit()

        # Print key to stdout ONCE — ops team copies it from Docker logs on first boot
        logger.warning(
            "\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            " AGR ON-PREM INITIALIZED\n"
            " Org:     %s\n"
            " API Key: %s\n"
            " Copy this key — it will NOT be shown again.\n"
            " Set it in your dashboard or SDK: AGR_API_KEY=<key>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            settings.onprem_org_name,
            api_key,
        )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    # S2/M5: fail fast on dangerous production misconfigurations
    settings.validate_production_settings()

    if settings.deployment_mode == "onprem":
        await _onprem_bootstrap()

    # Register built-in compliance plugins
    from app.services.compliance_plugins.audit_trail_check import AuditTrailCompliancePlugin
    from app.services.compliance_service import get_registry

    registry = get_registry()
    registry.register(AuditTrailCompliancePlugin())
    logger.info("Compliance registry ready (%d plugins)", len(registry.plugins))

    yield


app = FastAPI(
    title="AGR — Agentic Governance Runtime",
    description=(
        "Drop-in governance layer for AI agent frameworks. "
        "Every agent tool call is evaluated against Cedar policies before execution. "
        "Sensitive actions require human approval.\n\n"
        "## Authentication\n\n"
        "All endpoints (except `/v1/health`) require `Authorization: Bearer agr_sk_<key>` header.\n\n"
        "## Decision Values\n\n"
        "- `ALLOW` — agent may proceed\n"
        "- `DENY` — action is blocked\n"
        "- `APPROVAL_REQUIRED` — action is queued for human approval"
    ),
    version="0.1.0",
    contact={"name": "Shreeja AI", "url": "https://shreejaai.com"},
    openapi_tags=[
        {"name": "evaluate", "description": "Evaluate agent actions against Cedar policies."},
        {
            "name": "policies",
            "description": "Create, update, simulate, import/export Cedar policies.",
        },
        {"name": "approvals", "description": "Manage human approval workflows."},
        {"name": "agents", "description": "Register and manage AI agents."},
        {"name": "audit", "description": "Query the hash-chained audit log."},
        {
            "name": "org",
            "description": "Organization profile, usage stats, and team member management.",
        },
        {"name": "webhooks", "description": "Configure outbound webhooks."},
        {"name": "compliance", "description": "Compliance posture and findings."},
        {"name": "risk", "description": "Per-org risk scoring configuration."},
        {"name": "copilot", "description": "AI-powered policy authoring assistant."},
        {"name": "health", "description": "Health and readiness check."},
    ],
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(health.router)
app.include_router(evaluate.router)
app.include_router(policies.router)
app.include_router(approvals.router)
app.include_router(slack.router)
app.include_router(audit.router)
app.include_router(agents.router)
app.include_router(clerk.router)
app.include_router(webhooks.router)
app.include_router(org.router)
app.include_router(copilot_router)
app.include_router(risk_config_router)
app.include_router(compliance_router)
app.include_router(members_router)
app.include_router(usage_router)
