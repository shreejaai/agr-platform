"""Redis service — Cedar evaluation cache + eval rate limiting.

Both features degrade gracefully: if Redis is unavailable, the app falls back
to DB-only behavior with no crash.

Cache:
  Key:  eval:{org_id}:{sha256(agent+action+resource+context)[:16]}
  TTL:  60 seconds
  Skip: APPROVAL_REQUIRED results (each creates a unique DB row)

Rate limiting:
  Key:  evalcount:{org_id}
  Strategy: Redis INCR (atomic, fast). DB eval_count is synced asynchronously
            via background task — DB is eventual consistency for billing, Redis
            is authoritative for rate limiting.
"""

import hashlib
import json
import logging
from uuid import UUID

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_EVAL_CACHE_TTL = 60          # seconds
_RATE_KEY_TTL   = 60 * 60 * 24 * 31   # 31 days — reset handled at billing cycle

_redis_client: "aioredis.Redis[str] | None" = None


def _get_redis() -> "aioredis.Redis[str] | None":
    """Return the shared Redis client, lazily initialised. None if not configured."""
    global _redis_client
    if _redis_client is None:
        if not settings.redis_url:
            return None
        try:
            _redis_client = aioredis.from_url(
                settings.redis_url, encoding="utf-8", decode_responses=True
            )
        except Exception as exc:
            logger.warning("Redis client init failed: %s", exc)
    return _redis_client


def _eval_key(
    org_id: UUID,
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> str:
    raw = json.dumps(
        {"a": agent_id, "act": action, "r": resource, "ctx": context},
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"eval:{org_id}:{digest}"


def _rate_key(org_id: UUID) -> str:
    return f"evalcount:{org_id}"


# ---------------------------------------------------------------------------
# Cache — get / set / invalidate
# ---------------------------------------------------------------------------


async def get_cached_eval(
    org_id: UUID,
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> dict[str, object] | None:
    """Return cached evaluation result dict, or None on miss / Redis unavailable."""
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(_eval_key(org_id, agent_id, action, resource, context))
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("Cache GET error: %s", exc)
        return None


async def set_cached_eval(
    org_id: UUID,
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
    result: dict[str, object],
) -> None:
    """Cache an evaluation result. APPROVAL_REQUIRED is never cached."""
    if result.get("decision") == "APPROVAL_REQUIRED":
        return
    r = _get_redis()
    if r is None:
        return
    try:
        await r.setex(
            _eval_key(org_id, agent_id, action, resource, context),
            _EVAL_CACHE_TTL,
            json.dumps(result, default=str),
        )
    except Exception as exc:
        logger.debug("Cache SET error: %s", exc)


async def invalidate_org_eval_cache(org_id: UUID) -> None:
    """Delete all cached evaluations for an org. Called on every policy mutation."""
    r = _get_redis()
    if r is None:
        return
    try:
        keys: list[str] = [k async for k in r.scan_iter(f"eval:{org_id}:*")]
        if keys:
            await r.delete(*keys)
            logger.debug("Invalidated %d cache keys for org %s", len(keys), org_id)
    except Exception as exc:
        logger.debug("Cache invalidation error: %s", exc)


# ---------------------------------------------------------------------------
# Rate limiting — check & increment
# ---------------------------------------------------------------------------


async def rate_limit_incr(
    org_id: UUID,
    eval_limit: int,
    db_count: int,
) -> tuple[bool, int]:
    """Atomically increment the eval counter and check the rate limit.

    Args:
        org_id:     Organisation identifier.
        eval_limit: Max evals allowed (0 = unlimited).
        db_count:   Current DB eval_count — used to seed Redis on first call.

    Returns:
        (rate_limited, new_count)
        rate_limited=True  → caller should return 429.
        Falls back to (False, db_count) if Redis is unavailable.
    """
    r = _get_redis()
    if r is None:
        return False, db_count   # fall back: DB path in caller handles the check

    try:
        key = _rate_key(org_id)
        # Seed from DB on first encounter so the counter is accurate
        if not await r.exists(key):
            await r.set(key, db_count, ex=_RATE_KEY_TTL)

        new_count: int = await r.incr(key)

        if eval_limit > 0 and new_count > eval_limit:
            # Undo the increment — this request is blocked
            await r.decr(key)
            return True, new_count - 1

        return False, new_count

    except Exception as exc:
        logger.warning("Redis rate limit check failed (falling back to DB): %s", exc)
        return False, db_count


async def sync_eval_count_to_db(org_id: UUID) -> None:
    """Background task: write the current Redis eval count back to the DB.

    This keeps eval_count accurate for billing dashboards without blocking
    the evaluate response.
    """
    r = _get_redis()
    if r is None:
        return
    try:
        raw = await r.get(_rate_key(org_id))
        if raw is None:
            return
        count = int(raw)
    except Exception as exc:
        logger.warning("Redis eval count read failed: %s", exc)
        return

    try:
        from sqlalchemy import update as sa_update

        from app.database import async_session_factory
        from app.models import Organization

        async with async_session_factory() as session:
            await session.execute(
                sa_update(Organization)
                .where(Organization.id == org_id)
                .values(eval_count=count)
            )
            await session.commit()
    except Exception as exc:
        logger.warning("Failed to sync eval_count to DB for org %s: %s", org_id, exc)
