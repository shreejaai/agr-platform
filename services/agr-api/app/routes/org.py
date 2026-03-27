"""Organization self-info endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from app.schemas import OrgMeResponse

if TYPE_CHECKING:
    from app.models import Organization

router = APIRouter(prefix="/v1", tags=["org"])


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
        eval_week_start=org.eval_week_start,
        role=org.role,
        created_at=org.created_at,
    )
