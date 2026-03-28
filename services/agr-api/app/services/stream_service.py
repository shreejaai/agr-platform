"""In-memory org-scoped event fanout for realtime evaluation updates."""

from __future__ import annotations

import asyncio
from collections import defaultdict

_subscribers: dict[str, list[asyncio.Queue[dict[str, object]]]] = defaultdict(list)
_MAX_QUEUE_SIZE = 100


async def subscribe(org_id: str) -> asyncio.Queue[dict[str, object]]:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
    _subscribers[org_id].append(queue)
    return queue


async def unsubscribe(org_id: str, queue: asyncio.Queue[dict[str, object]]) -> None:
    subscribers = _subscribers.get(org_id, [])
    if queue in subscribers:
        subscribers.remove(queue)
    if not subscribers and org_id in _subscribers:
        _subscribers.pop(org_id, None)


async def publish(org_id: str, event: dict[str, object]) -> None:
    for queue in list(_subscribers.get(org_id, [])):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            continue
