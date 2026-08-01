import logging
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..auth import get_admin_from_token
from .. import config as app_config
from ..database import SessionLocal
from ..websocket_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _bridge_token_matches(provided: str) -> bool:
    bridge = app_config.WS_BROADCAST_BRIDGE_TOKEN
    if not bridge or not provided:
        return False
    if len(provided) != len(bridge):
        return False
    return secrets.compare_digest(provided, bridge)


@router.websocket("/ws")
async def live_feed(websocket: WebSocket):
    token = (
        websocket.query_params.get("token")
        or websocket.cookies.get(app_config.AUTH_COOKIE_NAME)
        or ""
    )
    if not token:
        await websocket.close(code=1008)
        return

    if _bridge_token_matches(token):
        logger.info(
            "WebSocket subscriber connected token_kind=bridge token_len=%s",
            len(token),
        )
    else:
        db = SessionLocal()
        try:
            get_admin_from_token(db, token)
        except Exception:
            logger.info("WebSocket rejected token_kind=jwt_invalid")
            await websocket.close(code=1008)
            return
        finally:
            db.close()
        logger.info("WebSocket subscriber connected token_kind=admin_jwt")

    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    finally:
        if websocket.client_state != WebSocketState.DISCONNECTED:
            manager.disconnect(websocket)
