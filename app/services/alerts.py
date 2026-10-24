import asyncio
import logging
from dataclasses import asdict, dataclass

from redis.asyncio import Redis

from app.core.redis_keys import ALERTS_CHANNEL_PATTERN
from app.services.connections import ConnectionManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AlertMetrics:
    received: int = 0
    delivered: int = 0
    no_sessions: int = 0
    failures: int = 0


class AlertsListener:
    def __init__(self, redis: Redis, manager: ConnectionManager) -> None:
        self._redis = redis
        self._manager = manager
        self._task: asyncio.Task[None] | None = None
        self.metrics = AlertMetrics()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="alerts-listener")
            logger.info("Alerts listener started (%s)", ALERTS_CHANNEL_PATTERN)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Alerts listener stopped")

    async def _run(self) -> None:
        while True:
            pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            try:
                await pubsub.psubscribe(ALERTS_CHANNEL_PATTERN)
                async for message in pubsub.listen():
                    if message.get("type") != "pmessage":
                        continue
                    self._dispatch(message["channel"], message["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                self.metrics.failures += 1
                logger.exception("Alerts subscription dropped; resubscribing")
                await asyncio.sleep(1.0)
            finally:
                await pubsub.aclose()

    def _dispatch(self, channel: str, payload: str | bytes) -> None:
        user_id = channel.split(":", 1)[1] if ":" in channel else ""
        if not user_id:
            return

        data = payload.encode() if isinstance(payload, str) else payload
        self.metrics.received += 1

        delivered = self._manager.send_to_user(user_id, data, droppable=False)
        if delivered:
            self.metrics.delivered += delivered
        else:
            self.metrics.no_sessions += 1

    def snapshot(self) -> dict[str, int]:
        return asdict(self.metrics)
