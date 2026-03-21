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
from app.routes import agents, approvals, audit, clerk, evaluate, health, org, policies, webhooks

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
        eval_limit = int(license_payload.get("evals", 0))

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
    if settings.deployment_mode == "onprem":
        await _onprem_bootstrap()
    yield


app = FastAPI(
    title="AGR — Agentic Governance Runtime",
    description="Drop-in governance layer for AI agent frameworks.",
    version="0.1.0",
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
app.include_router(audit.router)
app.include_router(agents.router)
app.include_router(clerk.router)
app.include_router(webhooks.router)
app.include_router(org.router)
