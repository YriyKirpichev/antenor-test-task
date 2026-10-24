import asyncio
import logging
import time
from dataclasses import asdict, dataclass

import msgspec
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.redis_keys import DEVICE_LAST_POSITION
from app.schemas.events import BBox, MapSnapshot
from app.services.connections import Connection, ConnectionManager

logger = logging.getLogger(__name__)

_encode = msgspec.json.Encoder().encode

DevicePoint = tuple[int, float, float, float]


@dataclass(slots=True)
class MapMetrics:
    ticks: int = 0
    snapshots_built: int = 0
    frames_queued: int = 0
    devices_last_tick: int = 0
    last_tick_ms: float = 0.0


class MapBroadcaster:
    def __init__(
        self,
        redis: Redis,
        manager: ConnectionManager,
        *,
        interval: float,
    ) -> None:
        self._redis = redis
        self._manager = manager
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self.metrics = MapMetrics()

    async def tick(self) -> int:
        connections = self._manager.connections()
        if not connections:
            return 0

        started = time.perf_counter()
        devices = _parse(await self._redis.hgetall(DEVICE_LAST_POSITION))
        now = time.time()

        by_bbox: dict[BBox | None, list[Connection]] = {}
        for connection in connections:
            by_bbox.setdefault(connection.bbox, []).append(connection)

        queued = 0
        for bbox, group in by_bbox.items():
            payload = _build(devices, bbox, now)
            self.metrics.snapshots_built += 1
            for connection in group:
                if self._manager.enqueue(connection, payload, droppable=True):
                    queued += 1

        self.metrics.ticks += 1
        self.metrics.frames_queued += queued
        self.metrics.devices_last_tick = len(devices)
        self.metrics.last_tick_ms = (time.perf_counter() - started) * 1000
        return queued

    async def send_initial(self, connection: Connection) -> None:
        devices = _parse(await self._redis.hgetall(DEVICE_LAST_POSITION))
        self._manager.enqueue(
            connection, _build(devices, connection.bbox, time.time()), droppable=True
        )

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Map broadcast tick failed")

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="map-broadcaster")
            logger.info(
                "Map broadcaster started (interval=%.0fms)", self._interval * 1000
            )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Map broadcaster stopped")

    def snapshot(self) -> dict[str, float | int]:
        return asdict(self.metrics)


def _parse(raw: dict[str, str]) -> list[DevicePoint]:
    points: list[DevicePoint] = []
    for device_id, packed in raw.items():
        try:
            lat, lon, ts = packed.split(",")
            points.append((int(device_id), float(lat), float(lon), float(ts)))
        except ValueError:
            logger.warning("Skipping malformed position for device %s", device_id)
    return points


def _build(devices: list[DevicePoint], bbox: BBox | None, now: float) -> bytes:
    selected = (
        devices
        if bbox is None
        else [point for point in devices if bbox.contains(point[1], point[2])]
    )
    return _encode(MapSnapshot(ts=now, count=len(selected), devices=selected))


def create_map_broadcaster(
    redis: Redis, manager: ConnectionManager, settings: Settings
) -> MapBroadcaster:
    return MapBroadcaster(
        redis, manager, interval=settings.MAP_BROADCAST_INTERVAL_MS / 1000
    )
