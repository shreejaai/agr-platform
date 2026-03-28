import logging
from collections.abc import AsyncGenerator
from contextvars import ContextVar, Token
from uuid import UUID

from fastapi import Request
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)
_request_org_id: ContextVar[UUID | None] = ContextVar("request_org_id", default=None)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def set_session_rls(session: AsyncSession, org_id: UUID) -> None:
    await session.execute(
        text("SET LOCAL app.current_org_id = :org_id").bindparams(bindparam("org_id", str(org_id)))
    )


def set_current_org_id(org_id: UUID | None) -> Token[UUID | None]:
    return _request_org_id.set(org_id)


def reset_current_org_id(token: Token[UUID | None]) -> None:
    _request_org_id.reset(token)


async def get_session(org_id: UUID | None = None) -> AsyncGenerator[AsyncSession, None]:
    effective_org_id = org_id if org_id is not None else _request_org_id.get()

    async with async_session_factory() as session:
        try:
            if effective_org_id is not None:
                await set_session_rls(session, effective_org_id)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session_rls(request: Request) -> AsyncGenerator[AsyncSession, None]:
    org_id = getattr(request.state, "org_id", None)
    async for session in get_session(org_id=org_id if isinstance(org_id, UUID) else None):
        yield session
