from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..database import SessionLocal
from ..models import DepositSession
from ..security.jwt import decode_access_token
from ..security.revocation import revocations
from ..services import event_bus

logger = __import__("logging").getLogger("recycle.websocket")

router = APIRouter(tags=["websocket"])

_AUTH_PARAM = "token"


def _owns_operation_sync(operation_id: str, user_id: str, token_version: int) -> bool:
    """Ownership AND token-generation check, run off the event loop."""
    from ..models import User

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            return False
        # Tokens minted before the latest credential change are dead.
        if int(token_version) != int(user.token_version or 0):
            return False
        session = (
            db.query(DepositSession)
            .filter(DepositSession.operation_id == operation_id)
            .first()
        )
        return session is not None and session.user_id == user_id
    finally:
        db.close()


@router.websocket("/ws/deposits/{operation_id}")
async def ws_deposit_status(websocket: WebSocket, operation_id: str) -> None:
    token = websocket.query_params.get(_AUTH_PARAM, "")

    # Decode and validate JWT.
    try:
        claims = decode_access_token(token, settings.jwt_secret)
    except Exception:
        # RFC 6455 §7.4: server MUST complete the handshake before closing.
        await websocket.accept()
        await websocket.close(code=4401, reason="Unauthorized")
        return

    # Revocation check: a logged-out token is rejected even if still in-expiry.
    if revocations.is_revoked(str(claims.get("jti", ""))):
        await websocket.accept()
        await websocket.close(code=4401, reason="Token revoked")
        return

    # Session ownership + token generation: run the sync DB call off the event
    # loop so it cannot stall other coroutines under concurrent connections.
    loop = asyncio.get_running_loop()
    owns = await loop.run_in_executor(
        None, _owns_operation_sync, operation_id,
        str(claims.get("sub", "")), int(claims.get("ver", 0)),
    )
    if not owns:
        await websocket.accept()
        await websocket.close(code=4403, reason="Forbidden")
        return

    await websocket.accept()
    queue = event_bus.subscribe(operation_id)
    try:
        await websocket.send_json({"type": "subscribed", "operation_id": operation_id})
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=25.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "keepalive"})
                continue
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(operation_id, queue)
