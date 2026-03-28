"""Realtime evaluation event stream."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.middleware.auth import authenticate_token
from app.services.stream_service import subscribe, unsubscribe

router = APIRouter(prefix="/v1", tags=["stream"])


@router.websocket("/stream/evaluations")
async def evaluation_stream(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "").strip()
    if not token:
        await websocket.close(code=4401)
        return

    auth_context = await authenticate_token(token)
    if auth_context is None:
        await websocket.close(code=4401)
        return

    org, _, _, _, scopes = auth_context
    if "*" not in scopes and "evaluate:write" not in scopes:
        await websocket.close(code=4403)
        return

    org_id = str(org.id)
    queue = await subscribe(org_id)
    await websocket.accept()

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        await unsubscribe(org_id, queue)
