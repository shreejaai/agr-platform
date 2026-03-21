"""Policy bulk import/export service.

Supports three input formats:
  - json     — list of policy objects (standard)
  - yaml     — same structure as JSON but YAML-encoded
  - cedar_raw — one or more Cedar policy strings separated by blank lines;
                each is wrapped into a PolicyImportItem with a generated name

Export always returns JSON (the canonical format).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models import Policy
from app.schemas import (
    PolicyImportItem,
    PolicyImportRequest,
    PolicyImportResponse,
    PolicyImportResult,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


_YAML_MAX_BYTES = 1_000_000  # 1 MB — prevents billion-laughs DoS via huge inputs


def parse_yaml_import(raw: str) -> PolicyImportRequest:
    """Parse a YAML string into a PolicyImportRequest.

    Raises ValueError on bad YAML or schema validation errors.
    """
    # M8: reject large inputs before parsing to prevent YAML DoS attacks
    if len(raw.encode()) > _YAML_MAX_BYTES:
        raise ValueError(
            f"Policy file too large ({len(raw.encode()):,} bytes). "
            f"Maximum allowed: {_YAML_MAX_BYTES:,} bytes."
        )

    try:
        import yaml  # optional dep — only needed for YAML path
    except ImportError as exc:
        raise ValueError("pyyaml is not installed. Add pyyaml>=6.0 to requirements.") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("YAML root must be a mapping with a 'policies' key.")

    return PolicyImportRequest.model_validate(data)


def parse_cedar_raw_import(raw: str, dry_run: bool = False) -> PolicyImportRequest:
    """Parse a block of Cedar rules (blank-line separated) into a PolicyImportRequest.

    Each policy block becomes an org-level policy named "Imported policy N".
    """
    blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]
    items = []
    for idx, block in enumerate(blocks, start=1):
        items.append(
            PolicyImportItem(
                name=f"Imported policy {idx}",
                level="org",
                cedar_rule=block,
            )
        )
    return PolicyImportRequest(policies=items, dry_run=dry_run)


def _policy_to_export_dict(p: Policy) -> dict[str, object]:
    return {
        "name": p.name,
        "level": p.level,
        "cedar_rule": p.cedar_rule,
        "project_id": str(p.project_id) if p.project_id else None,
        "agent_id": p.agent_id,
        "active": p.active,
    }


async def export_policies(
    session: AsyncSession,
    org_id: uuid.UUID,
    active_only: bool = False,
) -> list[dict[str, object]]:
    """Return all org policies as a list of export dicts (JSON-serialisable)."""
    stmt = select(Policy).where(Policy.org_id == org_id)
    if active_only:
        stmt = stmt.where(Policy.active.is_(True))
    stmt = stmt.order_by(Policy.created_at)
    result = await session.execute(stmt)
    return [_policy_to_export_dict(p) for p in result.scalars().all()]


async def import_policies(
    session: AsyncSession,
    org_id: uuid.UUID,
    req: PolicyImportRequest,
) -> PolicyImportResponse:
    """Bulk-create or update policies for an org.

    Args:
        session: DB session (caller manages transaction).
        org_id:  Organisation to import into.
        req:     Validated import request.

    Returns:
        PolicyImportResponse with per-policy results.
    """
    results: list[PolicyImportResult] = []
    created = updated = skipped = errors = 0

    # Pre-load existing policies by name (needed for skip and overwrite detection)
    existing_by_name: dict[str, Policy] = {}
    stmt = select(Policy).where(Policy.org_id == org_id)
    result = await session.execute(stmt)
    for p in result.scalars().all():
        existing_by_name[p.name] = p

    for item in req.policies:
        try:
            existing = existing_by_name.get(item.name)

            if existing and not req.overwrite:
                results.append(PolicyImportResult(name=item.name, status="skipped"))
                skipped += 1
                continue

            if req.dry_run:
                status = "updated" if existing else "created"
                results.append(PolicyImportResult(name=item.name, status=status))
                if existing:
                    updated += 1
                else:
                    created += 1
                continue

            if existing and req.overwrite:
                existing.cedar_rule = item.cedar_rule
                existing.level = item.level
                existing.active = item.active
                if item.project_id is not None:
                    existing.project_id = item.project_id
                if item.agent_id is not None:
                    existing.agent_id = item.agent_id
                existing.version += 1
                await session.flush()
                results.append(
                    PolicyImportResult(name=item.name, status="updated", policy_id=str(existing.id))
                )
                updated += 1
            else:
                policy = Policy(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    name=item.name,
                    level=item.level,
                    cedar_rule=item.cedar_rule,
                    active=item.active,
                    project_id=item.project_id,
                    agent_id=item.agent_id,
                )
                session.add(policy)
                await session.flush()
                results.append(
                    PolicyImportResult(name=item.name, status="created", policy_id=str(policy.id))
                )
                created += 1

        except Exception as exc:
            results.append(PolicyImportResult(name=item.name, status="error", error=str(exc)))
            errors += 1

    return PolicyImportResponse(
        dry_run=req.dry_run,
        total=len(req.policies),
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
        results=results,
    )
