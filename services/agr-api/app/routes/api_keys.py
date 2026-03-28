import hashlib
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_scope
from app.models import ApiKey
from app.schemas import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyResponse

router = APIRouter(
    prefix="/v1/org",
    tags=["org"],
    dependencies=[Depends(require_scope("org:admin"))],
)


def _to_response(api_key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=str(api_key.id),
        key_prefix=api_key.key_prefix,
        scopes=list(api_key.scopes or []),
        name=api_key.name,
        created_by=api_key.created_by,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        revoked=api_key.revoked,
        created_at=api_key.created_at,
    )


@router.get("/api_keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> list[ApiKeyResponse]:
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.org_id == request.state.org_id)
        .order_by(ApiKey.created_at.desc())
    )
    return [_to_response(item) for item in result.scalars().all()]


@router.post("/api_keys", response_model=ApiKeyCreateResponse, status_code=201)
async def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ApiKeyCreateResponse:
    raw_key = "agr_sk_" + secrets.token_hex(24)
    api_key = ApiKey(
        id=uuid.uuid4(),
        org_id=request.state.org_id,
        key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
        key_prefix=raw_key[:12],
        scopes=body.scopes or ["*"],
        name=body.name,
        created_by=getattr(request.state, "identity_email", None) or "api-key@agr.local",
        expires_at=body.expires_at,
        revoked=False,
    )
    session.add(api_key)
    await session.flush()
    await session.refresh(api_key)

    return ApiKeyCreateResponse(**_to_response(api_key).model_dump(), key=raw_key)


@router.delete("/api_keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.org_id == request.state.org_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found.")
    api_key.revoked = True
    await session.flush()
