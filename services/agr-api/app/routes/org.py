"""Organization self-info endpoint."""

from fastapi import APIRouter, Request

from app.models import Organization
from app.schemas import OrgMeResponse

router = APIRouter(prefix="/v1")


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
        created_at=org.created_at,
    )
