import asyncio
import itertools
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

from app.schemas.events import BBox

logger = logging.getLogger(__name__)

_connection_ids = itertools.count(1)

WS_TRY_AGAIN_LATER = 1013


@dataclass(slots=True, eq=False)
class Connection:
    id: int
    user_id: str
    websocket: WebSocket
    queue: asyncio.Queue[bytes]
    bbox: BBox | None = None
    sender: asyncio.Task[None] | None = field(default=None, repr=False)
    dropped: int = 0
    closing: bool = False


class ConnectionManager:
    def __init__(self, *, queue_maxsize: int) -> None:
        self._queue_maxsize = queue_maxsize
        self._by_user: dict[str, set[Connection]] = {}
        self._closing: set[asyncio.Task[None]] = set()
        self.dropped = 0
        self.closed_slow = 0

    @property
    def connection_count(self) -> int:
        return sum(len(sessions) for sessions in self._by_user.values())

    @property
    def user_count(self) -> int:
        return len(self._by_user)

    def connections(self) -> list[Connection]:
        return [conn for sessions in self._by_user.values() for conn in sessions]

    def sessions_of(self, user_id: str) -> tuple[Connection, ...]:
        return tuple(self._by_user.get(user_id, ()))

    async def connect(self, websocket: WebSocket, user_id: str) -> Connection:
        await websocket.accept()
        connection = Connection(
            id=next(_connection_ids),
            user_id=user_id,
            websocket=websocket,
            queue=asyncio.Queue(maxsize=self._queue_maxsize),
        )
        connection.sender = asyncio.create_task(
            self._sender(connection), name=f"ws-sender-{connection.id}"
        )
        self._by_user.setdefault(user_id, set()).add(connection)
        return connection

    async def disconnect(self, connection: Connection) -> None:
        sessions = self._by_user.get(connection.user_id)
        if sessions is not None:
            sessions.discard(connection)
            if not sessions:
                del self._by_user[connection.user_id]

        sender = connection.sender
        connection.sender = None
        if sender is not None:
            sender.cancel()
            try:
                await sender
            except asyncio.CancelledError:
                pass

    def enqueue(
        self, connection: Connection, payload: bytes, *, droppable: bool
    ) -> bool:
        try:
            connection.queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            pass

        if not droppable:
            if not connection.closing:
                self.closed_slow += 1
                self._schedule_close(connection)
            return False

        try:
            connection.queue.get_nowait() 
        except asyncio.QueueEmpty:
            pass
        connection.dropped += 1
        self.dropped += 1
        try:
            connection.queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            return False

    def send_to_user(self, user_id: str, payload: bytes, *, droppable: bool) -> int:
        return sum(
            self.enqueue(connection, payload, droppable=droppable)
            for connection in self.sessions_of(user_id)
        )

    def _schedule_close(self, connection: Connection) -> None:
        connection.closing = True
        task = asyncio.create_task(
            self._close(connection), name=f"ws-close-{connection.id}"
        )
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def _close(self, connection: Connection) -> None:
        try:
            await connection.websocket.close(code=WS_TRY_AGAIN_LATER)
        except Exception:
            logger.debug("Closing connection %d failed", connection.id, exc_info=True)

    async def _sender(self, connection: Connection) -> None:
        try:
            while True:
                payload = await connection.queue.get()
                await connection.websocket.send_bytes(payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Sender %d stopped", connection.id, exc_info=True)

    def snapshot(self) -> dict[str, int]:
        return {
            "users": self.user_count,
            "connections": self.connection_count,
            "dropped_frames": self.dropped,
            "closed_slow": self.closed_slow,
        }
