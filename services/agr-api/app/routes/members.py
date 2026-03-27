"""GET/POST/PATCH/DELETE /v1/org/members — team invite and role management.

Access control:
  - All endpoints require a valid AGR API key (standard AuthMiddleware).
  - Mutating endpoints (invite, update role, revoke) require role=admin.
  - List endpoint is accessible to all authenticated roles.

Every admin action writes an audit event (event_type: MEMBER_INVITED,
MEMBER_ROLE_UPDATED, MEMBER_REVOKED).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.database import get_session
from app.models import OrgMember
from app.schemas import (
    ErrorResponse,
    OrgMemberInviteRequest,
    OrgMemberResponse,
    OrgMemberUpdateRequest,
)
from app.services.audit_service import create_audit_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/org", tags=["org"])


def _to_response(m: OrgMember) -> OrgMemberResponse:
    return OrgMemberResponse(
        id=str(m.id),
        org_id=str(m.org_id),
        email=m.email,
        role=m.role,
        status=m.status,
        invited_by=m.invited_by,
        joined_at=m.joined_at,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _require_admin(request: Request) -> None:
    """Raise 403 if the caller's API key is not admin role."""
    org_role: str = getattr(request.state.org, "role", "viewer")
    if org_role != "admin":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "forbidden",
                "message": (
                    "This action requires admin role. " "Your API key has role: " + org_role
                ),
            },
        )


@router.get(
    "/members",
    response_model=list[OrgMemberResponse],
    responses={401: {"model": ErrorResponse}},
    summary="List team members",
    description=(
        "Returns all members of the authenticated organization, "
        "including invited, active, and revoked members."
    ),
)
async def list_members(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[OrgMemberResponse]:
    org_id: uuid.UUID = request.state.org_id
    result = await session.execute(
        select(OrgMember).where(OrgMember.org_id == org_id).order_by(OrgMember.created_at)
    )
    members = result.scalars().all()
    return [_to_response(m) for m in members]


@router.post(
    "/members/invite",
    response_model=OrgMemberResponse,
    status_code=201,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    summary="Invite a team member",
    description=(
        "Sends an invite to the given email address. "
        "Requires admin role. "
        "An audit event (MEMBER_INVITED) is written for every invite."
    ),
)
async def invite_member(
    body: OrgMemberInviteRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> OrgMemberResponse:
    _require_admin(request)
    org_id: uuid.UUID = request.state.org_id
    inviter_email: str = getattr(request.state.org, "slug", str(org_id))

    # Check for existing active/invited member with this email
    existing = await session.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.email == body.email,
            OrgMember.status.in_(["invited", "active"]),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "already_invited",
                "message": f"{body.email} is already an active or invited member.",
            },
        )

    member = OrgMember(
        id=uuid.uuid4(),
        org_id=org_id,
        email=body.email,
        role=body.role,
        status="invited",
        invited_by=inviter_email,
    )
    session.add(member)
    await session.flush()

    await create_audit_event(
        session=session,
        org_id=org_id,
        event_type="MEMBER_INVITED",
        agent_id="__admin__",
        action="invite_member",
        resource=body.email,
        decision="ALLOW",
        payload={"role": body.role, "invited_by": inviter_email},
    )

    logger.info("Invited member %s with role=%s to org %s", body.email, body.role, org_id)
    return _to_response(member)


@router.patch(
    "/members/{member_id}",
    response_model=OrgMemberResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Update a member's role",
    description=(
        "Changes the role of an existing member. "
        "Requires admin role. "
        "An audit event (MEMBER_ROLE_UPDATED) is written."
    ),
)
async def update_member_role(
    member_id: uuid.UUID,
    body: OrgMemberUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> OrgMemberResponse:
    _require_admin(request)
    org_id: uuid.UUID = request.state.org_id

    result = await session.execute(
        select(OrgMember).where(OrgMember.id == member_id, OrgMember.org_id == org_id)
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "message": "Member not found."}
        )

    old_role = member.role
    member.role = body.role
    await session.flush()
    await session.refresh(member)

    await create_audit_event(
        session=session,
        org_id=org_id,
        event_type="MEMBER_ROLE_UPDATED",
        agent_id="__admin__",
        action="update_member_role",
        resource=member.email,
        decision="ALLOW",
        payload={"old_role": old_role, "new_role": body.role},
    )

    logger.info("Updated member %s role: %s → %s", member.email, old_role, body.role)
    return _to_response(member)


@router.delete(
    "/members/{member_id}",
    status_code=204,
    response_model=None,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
    summary="Revoke member access",
    description=(
        "Revokes the member's access (sets status to 'revoked'). "
        "Does not delete the row — the member remains in the audit history. "
        "Requires admin role."
    ),
)
async def revoke_member(
    member_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_admin(request)
    org_id: uuid.UUID = request.state.org_id

    result = await session.execute(
        select(OrgMember).where(OrgMember.id == member_id, OrgMember.org_id == org_id)
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "message": "Member not found."}
        )
    if member.status == "revoked":
        raise HTTPException(
            status_code=409,
            detail={"error": "already_revoked", "message": "Member access is already revoked."},
        )

    member.status = "revoked"
    await session.flush()

    await create_audit_event(
        session=session,
        org_id=org_id,
        event_type="MEMBER_REVOKED",
        agent_id="__admin__",
        action="revoke_member",
        resource=member.email,
        decision="ALLOW",
        payload={"role": member.role},
    )

    logger.info("Revoked member %s from org %s", member.email, org_id)
