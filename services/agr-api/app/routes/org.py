"""Organization self-info endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from fastapi import APIRouter, Depends, Request

from app.database import get_session
from app.dependencies import require_role
from app.models import Organization
from app.schemas import OrgMeResponse, SSOSettingsResponse, SSOSettingsUpdateRequest
from app.services.sso_service import parse_sso_domains, serialize_sso_domains

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/v1", tags=["org"])
_VALID_SSO_DEFAULT_ROLES = frozenset({"admin", "operator", "viewer"})


def _normalize_sso_default_role(role: str) -> Literal["admin", "operator", "viewer"]:
    if role in _VALID_SSO_DEFAULT_ROLES:
        return cast(Literal["admin", "operator", "viewer"], role)
    return "viewer"


@router.get("/org/me", response_model=OrgMeResponse)
async def get_org_me(request: Request) -> OrgMeResponse:
    """Return the authenticated org's profile and usage stats."""
    org: Organization = request.state.org
    return OrgMeResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        eval_count=org.eval_count,
        eval_limit=org.eval_limit,
        eval_warning_threshold_pct=org.eval_warning_threshold_pct,
        eval_soft_limit_enabled=org.eval_soft_limit_enabled,
        eval_week_start=org.eval_week_start,
        role=getattr(request.state, "role", org.role),
        auth_mode=getattr(request.state, "auth_mode", "api_key"),
        auth_expires_at=getattr(request.state, "auth_expires_at", None),
        sso_enabled=org.sso_enabled,
        sso_provider=org.sso_provider,
        created_at=org.created_at,
    )


def _sso_response(org: Organization) -> SSOSettingsResponse:
    return SSOSettingsResponse(
        enabled=org.sso_enabled,
        provider=org.sso_provider,
        metadata_url=org.sso_metadata_url,
        metadata_xml=org.sso_metadata_xml,
        entity_id=org.sso_entity_id,
        domains=parse_sso_domains(org.sso_domains),
        default_role=_normalize_sso_default_role(org.sso_default_role),
        auto_join=org.sso_auto_join,
    )


@router.get(
    "/org/sso",
    response_model=SSOSettingsResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def get_org_sso_settings(request: Request) -> SSOSettingsResponse:
    org: Organization = request.state.org
    return _sso_response(org)


@router.put(
    "/org/sso",
    response_model=SSOSettingsResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def update_org_sso_settings(
    body: SSOSettingsUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SSOSettingsResponse:
    org = await session.get(Organization, request.state.org_id)
    if org is None:
        raise RuntimeError("Authenticated organization could not be reloaded.")

    if body.enabled is not None:
        org.sso_enabled = body.enabled
    if body.provider is not None:
        org.sso_provider = body.provider.strip() or None
    if body.metadata_url is not None:
        org.sso_metadata_url = body.metadata_url.strip() or None
    if body.metadata_xml is not None:
        org.sso_metadata_xml = body.metadata_xml.strip() or None
    if body.entity_id is not None:
        org.sso_entity_id = body.entity_id.strip() or None
    if body.domains is not None:
        org.sso_domains = serialize_sso_domains(body.domains)
    if body.default_role is not None:
        org.sso_default_role = body.default_role
    if body.auto_join is not None:
        org.sso_auto_join = body.auto_join

    await session.flush()
    await session.refresh(org)
    return _sso_response(org)
