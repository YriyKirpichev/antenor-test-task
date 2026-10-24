import logging

import msgspec
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.api.deps import IngestorDep
from app.services.ingest import decode_positions

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest"])

_encode = msgspec.json.Encoder().encode


@router.websocket("/ws/devices")
async def ingest_devices(websocket: WebSocket, ingestor: IngestorDep) -> None:
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return

            raw = message.get("bytes") or message.get("text")
            if not raw:
                continue

            try:
                positions = decode_positions(raw)
            except msgspec.MsgspecError as exc:
                ingestor.metrics.rejected += 1
                await websocket.send_bytes(
                    _encode({"type": "error", "detail": str(exc)})
                )
                continue

            ingestor.submit(positions)
    except WebSocketDisconnect:
        return
