import logging

import msgspec
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.api.deps import ConnectionManagerDep, MapBroadcasterDep, WsUserIdDep
from app.schemas.events import SetBBox

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])

_encode = msgspec.json.Encoder().encode
_decode_command = msgspec.json.Decoder(SetBBox).decode


@router.websocket("/ws/client")
async def stream_to_client(
    websocket: WebSocket,
    user_id: WsUserIdDep,
    manager: ConnectionManagerDep,
    broadcaster: MapBroadcasterDep,
) -> None:
    connection = await manager.connect(websocket, user_id)
    logger.info(
        "Client session %d open (user=%s, sessions=%d)",
        connection.id,
        user_id,
        len(manager.sessions_of(user_id)),
    )
    try:
        await broadcaster.send_initial(connection)
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return

            raw = message.get("bytes") or message.get("text")
            if not raw:
                continue

            try:
                command = _decode_command(raw)
            except msgspec.MsgspecError as exc:
                manager.enqueue(
                    connection,
                    _encode({"type": "error", "detail": str(exc)}),
                    droppable=True,
                )
                continue

            connection.bbox = command.bbox
            await broadcaster.send_initial(connection)
    except WebSocketDisconnect:
        return
    finally:
        await manager.disconnect(connection)
        logger.info("Client session %d closed (user=%s)", connection.id, user_id)
