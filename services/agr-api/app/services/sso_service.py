"""Deterministic SSO/SAML mapping helpers built on top of Clerk sessions."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.config import settings
from app.models import AuthSession, Organization, OrgMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_ROLE_RANK: dict[str, int] = {"viewer": 0, "operator": 1, "admin": 2}
_ROLE_HINTS: dict[str, str] = {
    "admin": "admin",
    "administrator": "admin",
    "owner": "admin",
    "operator": "operator",
    "editor": "operator",
    "developer": "operator",
    "viewer": "viewer",
    "read_only": "viewer",
    "readonly": "viewer",
}
_ORG_HINT_KEYS = (
    "org",
    "org_id",
    "org_slug",
    "organization",
    "organization_id",
    "organization_slug",
)
_ROLE_HINT_KEYS = ("org_role", "role", "roles", "groups")


@dataclass(slots=True)
class ResolvedSessionAccess:
    org: Organization
    role: str
    identity_email: str | None
    used_sso: bool


def parse_sso_domains(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def serialize_sso_domains(domains: list[str] | None) -> str | None:
    if not domains:
        return None
    normalized = sorted({domain.strip().lower() for domain in domains if domain.strip()})
    return ",".join(normalized) if normalized else None


def map_identity_role(claims: dict[str, Any], default_role: str) -> str:
    resolved = default_role if default_role in _ROLE_RANK else "viewer"

    for key in _ROLE_HINT_KEYS:
        raw = claims.get(key)
        values: list[str]
        if isinstance(raw, str):
            values = [raw]
        elif isinstance(raw, list):
            values = [item for item in raw if isinstance(item, str)]
        else:
            continue
        for value in values:
            for token in value.replace(",", " ").split():
                mapped = _ROLE_HINTS.get(token.strip().lower())
                if mapped and _ROLE_RANK[mapped] > _ROLE_RANK[resolved]:
                    resolved = mapped
    return resolved


def extract_email_from_clerk_user(user_data: dict[str, Any], claims: dict[str, Any]) -> str | None:
    email_addresses = user_data.get("email_addresses")
    if isinstance(email_addresses, list):
        for item in email_addresses:
            if isinstance(item, dict):
                candidate = item.get("email_address")
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip().lower()
    claim_email = claims.get("email")
    if isinstance(claim_email, str) and claim_email.strip():
        return claim_email.strip().lower()
    return None


def _org_hints(claims: dict[str, Any]) -> set[str]:
    hints: set[str] = set()
    for key in _ORG_HINT_KEYS:
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            hints.add(value.strip())
    return hints


async def issue_auth_session(
    session: AsyncSession,
    org: Organization,
    *,
    identity_sub: str,
    identity_email: str | None,
    role: str,
) -> AuthSession:
    token = "agr_usr_" + secrets.token_hex(24)
    auth_session = AuthSession(
        org_id=org.id,
        token=token,
        identity_sub=identity_sub,
        identity_email=identity_email,
        role=role,
        expires_at=datetime.now(UTC) + timedelta(hours=settings.auth_session_ttl_hours),
    )
    session.add(auth_session)
    await session.flush()
    return auth_session


async def resolve_session_access(
    session: AsyncSession,
    *,
    user_id: str,
    identity_email: str | None,
    claims: dict[str, Any],
) -> ResolvedSessionAccess | None:
    email = (
        identity_email.strip().lower()
        if isinstance(identity_email, str) and identity_email
        else None
    )
    hints = _org_hints(claims)

    if email:
        member_result = await session.execute(
            select(OrgMember, Organization)
            .join(Organization, Organization.id == OrgMember.org_id)
            .where(func.lower(OrgMember.email) == email)
        )
        member_matches = member_result.all()
        if hints:
            member_matches = [
                row
                for row in member_matches
                if row[1].slug in hints or row[1].sso_entity_id in hints or row[1].name in hints
            ]
        if member_matches:
            active_matches = [row for row in member_matches if row[0].status != "revoked"]
            if len(active_matches) > 1:
                raise ValueError("multiple_org_memberships")
            if not active_matches:
                raise PermissionError("revoked_membership")
            member, org = active_matches[0]
            if member.status == "invited":
                member.status = "active"
                member.joined_at = datetime.now(UTC)
            return ResolvedSessionAccess(
                org=org,
                role=member.role,
                identity_email=email,
                used_sso=True,
            )

    org_result = await session.execute(
        select(Organization).where(Organization.sso_enabled.is_(True))
    )
    sso_orgs = org_result.scalars().all()
    domain = email.split("@", 1)[1] if email and "@" in email else None
    candidate_orgs: list[Organization] = []
    for org in sso_orgs:
        domains = parse_sso_domains(org.sso_domains)
        hint_match = bool(hints) and (
            org.slug in hints or org.sso_entity_id in hints or org.name in hints
        )
        domain_match = domain is not None and domain in domains
        if hint_match or domain_match:
            candidate_orgs.append(org)

    if len(candidate_orgs) > 1:
        raise ValueError("ambiguous_sso_mapping")
    if not candidate_orgs:
        return None

    org = candidate_orgs[0]
    if email:
        member_result = await session.execute(
            select(OrgMember).where(
                OrgMember.org_id == org.id,
                func.lower(OrgMember.email) == email,
            )
        )
        existing_member = member_result.scalar_one_or_none()
        if existing_member is not None:
            if existing_member.status == "revoked":
                raise PermissionError("revoked_membership")
            if existing_member.status == "invited":
                existing_member.status = "active"
                existing_member.joined_at = datetime.now(UTC)
            return ResolvedSessionAccess(
                org=org,
                role=existing_member.role,
                identity_email=email,
                used_sso=True,
            )

    if not org.sso_auto_join:
        raise PermissionError("sso_membership_required")

    role = map_identity_role(claims, org.sso_default_role)
    if email:
        session.add(
            OrgMember(
                org_id=org.id,
                email=email,
                role=role,
                status="active",
                invited_by=f"sso:{user_id}",
                joined_at=datetime.now(UTC),
            )
        )
    return ResolvedSessionAccess(org=org, role=role, identity_email=email, used_sso=True)
