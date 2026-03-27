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

import contextlib
import hashlib
import json
import logging
from typing import Literal, TypedDict
from uuid import UUID

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_EVAL_CACHE_TTL = 60  # seconds
_RATE_KEY_TTL = 60 * 60 * 24 * 31  # 31 days — reset handled at billing cycle

_redis_client: "aioredis.Redis[str] | None" = None  # type: ignore[type-arg]
_redis_unavailable: bool = False  # set True after a failed init so we stop retrying


def _get_redis() -> "aioredis.Redis[str] | None":  # type: ignore[type-arg]
    """Return the module-level Redis connection pool, lazily initialised.

    `aioredis.from_url()` creates a connection pool (not a single connection).
    The pool is reused across all callers — no per-request reconnection.
    Returns None if REDIS_URL is unset or if the initial setup failed.
    """
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is None:
        if not settings.redis_url:
            _redis_unavailable = True
            return None
        try:
            _redis_client = aioredis.from_url(  # type: ignore[no-untyped-call]
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                # Connection pool settings — tune for your concurrency needs
                max_connections=20,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
                retry_on_timeout=False,
            )
        except Exception as exc:
            logger.warning("Redis client init failed: %s", exc)
            _redis_unavailable = True
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


_SCAN_BATCH_SIZE = 500  # keys per DEL call — prevents single huge command


async def invalidate_org_eval_cache(org_id: UUID) -> None:
    """Delete all cached evaluations for an org. Called on every policy mutation.

    L4: deletes in batches to avoid a single DEL with thousands of keys
    (which would block the Redis event loop for the duration).
    """
    r = _get_redis()
    if r is None:
        return
    try:
        batch: list[str] = []
        total = 0
        async for key in r.scan_iter(f"eval:{org_id}:*"):
            batch.append(key)
            if len(batch) >= _SCAN_BATCH_SIZE:
                await r.unlink(*batch)  # UNLINK is async delete (non-blocking)
                total += len(batch)
                batch = []
        if batch:
            await r.unlink(*batch)
            total += len(batch)
        if total:
            logger.debug("Invalidated %d cache keys for org %s", total, org_id)
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
        return False, db_count  # fall back: DB path in caller handles the check

    try:
        key = _rate_key(org_id)
        # Seed from DB atomically using SET NX (set-if-not-exists) — prevents
        # two concurrent requests both seeding the key and resetting the counter.
        await r.set(key, db_count, nx=True, ex=_RATE_KEY_TTL)

        new_count: int = await r.incr(key)

        if eval_limit > 0 and new_count > eval_limit:
            # Undo the increment — this request is blocked
            await r.decr(key)
            return True, new_count - 1

        return False, new_count

    except Exception as exc:
        logger.warning("Redis rate limit check failed (falling back to DB): %s", exc)
        return False, db_count


_DECIDE_RATE_WINDOW = 300  # 5-minute window
_DECIDE_RATE_MAX = 10  # max attempts per approval within the window


async def check_decide_rate_limit(approval_id: str) -> bool:
    """Return True (blocked) if too many decide attempts for this approval.

    M5: Prevents automated abuse of the email one-click decide endpoint.
    Fails open — if Redis is unavailable the request is allowed through.
    """
    r = _get_redis()
    if r is None:
        return False  # fail-open: don't block when Redis is unavailable
    try:
        key = f"decide_limit:{approval_id}"
        count: int = await r.incr(key)
        if count == 1:
            await r.expire(key, _DECIDE_RATE_WINDOW)
        return count > _DECIDE_RATE_MAX
    except Exception as exc:
        logger.debug("decide rate limit check failed (allowing through): %s", exc)
        return False  # fail-open


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
                sa_update(Organization).where(Organization.id == org_id).values(eval_count=count)
            )
            await session.commit()
    except Exception as exc:
        logger.warning("Failed to sync eval_count to DB for org %s: %s", org_id, exc)


# ── Copilot conversation cache ────────────────────────────────────────────────
_COPILOT_CACHE_TTL = 3600  # 1 hour


class ConversationCacheMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


async def get_conversation_cache(conversation_id: str) -> list[ConversationCacheMessage] | None:
    """Return cached message list for a conversation, or None on miss/error."""
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(f"copilot:hist:{conversation_id}")
        if raw is None:
            return None
        import json as _json

        loaded = _json.loads(raw)
        if not isinstance(loaded, list):
            return None

        messages: list[ConversationCacheMessage] = []
        for item in loaded:
            if not isinstance(item, dict):
                return None

            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                return None

            messages.append({"role": role, "content": content})

        return messages
    except Exception:
        return None


async def set_conversation_cache(
    conversation_id: str,
    messages: list[ConversationCacheMessage],
) -> None:
    """Cache the full message list for a conversation (1 h TTL)."""
    r = _get_redis()
    if r is None:
        return
    try:
        import json as _json

        await r.setex(
            f"copilot:hist:{conversation_id}",
            _COPILOT_CACHE_TTL,
            _json.dumps(messages),
        )
    except Exception:
        pass


async def invalidate_conversation_cache(conversation_id: str) -> None:
    """Remove cached messages for a conversation."""
    r = _get_redis()
    if r is None:
        return
    with contextlib.suppress(Exception):
        await r.delete(f"copilot:hist:{conversation_id}")
