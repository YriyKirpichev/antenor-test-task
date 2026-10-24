import asyncio
import logging
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import msgspec
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.redis_keys import (
    DEVICE_ZONES,
    POSITIONS_STREAM,
    alerts_channel,
)
from app.dto.notification import NotificationCreateDTO
from app.repositories.notification import NotificationRepository
from app.schemas.events import AlertMessage, Position
from app.services.geofence import (
    AlertMode,
    GeofenceAlert,
    compute_events,
    decode_zone_state,
    encode_zone_state,
    latest_per_device,
    match_zones,
)

logger = logging.getLogger(__name__)

GEOFENCE_GROUP = "geofence"

_encode = msgspec.json.Encoder().encode


@dataclass(slots=True)
class GeofenceMetrics:
    batches: int = 0
    entries: int = 0
    devices: int = 0
    malformed: int = 0
    hits: int = 0
    alerts: int = 0
    failures: int = 0
    last_batch_ms: float = 0.0


class GeofenceConsumer:
    def __init__(
        self,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        consumer_name: str,
        batch_size: int,
        block_ms: int,
        mode: AlertMode = AlertMode.ENTER,
        cooldown_s: float = 60.0,
    ) -> None:
        self._redis = redis
        self._session_factory = session_factory
        self._consumer_name = consumer_name
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._mode = mode
        self._cooldown_s = cooldown_s
        self._cooldown_until: dict[tuple[int, int], float] = {}
        self._draining_pending = True
        self.metrics = GeofenceMetrics()

    async def setup(self) -> None:
        try:
            await self._redis.xgroup_create(
                POSITIONS_STREAM, GEOFENCE_GROUP, id="$", mkstream=True
            )
            logger.info("Created consumer group %r", GEOFENCE_GROUP)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def run(self, stop: asyncio.Event) -> None:
        logger.info(
            "Geofence consumer %r started (mode=%s, batch=%d, block=%dms)",
            self._consumer_name,
            self._mode,
            self._batch_size,
            self._block_ms,
        )
        while not stop.is_set():
            try:
                await self._step()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.metrics.failures += 1
                logger.exception("Geofence batch failed; retrying")
                await asyncio.sleep(1.0)

    async def _step(self) -> int:
        entries = await self._read()
        if not entries:
            return 0

        started = time.perf_counter()
        positions, entry_ids, malformed = _parse(entries)
        latest = latest_per_device(positions)

        if latest:
            await self._evaluate(latest)

        await self._redis.xack(POSITIONS_STREAM, GEOFENCE_GROUP, *entry_ids)

        self.metrics.batches += 1
        self.metrics.entries += len(entry_ids)
        self.metrics.devices += len(latest)
        self.metrics.malformed += malformed
        self.metrics.last_batch_ms = (time.perf_counter() - started) * 1000
        return len(entry_ids)

    async def _read(self) -> list[tuple[str, dict[str, str]]]:
        stream_id = "0" if self._draining_pending else ">"
        response = await self._redis.xreadgroup(
            groupname=GEOFENCE_GROUP,
            consumername=self._consumer_name,
            streams={POSITIONS_STREAM: stream_id},
            count=self._batch_size,
            block=None if self._draining_pending else self._block_ms,
        )
        entries = response[0][1] if response else []
        if not entries and self._draining_pending:
            logger.info("Pending entries drained; following the stream live")
            self._draining_pending = False
        return entries

    async def _evaluate(self, latest: dict[int, Position]) -> None:
        previous = await self._load_state(latest)

        async with self._session_factory() as session:
            hits = await match_zones(session, list(latest.values()))
            self.metrics.hits += len(hits)

            batch = compute_events(
                latest,
                hits,
                previous,
                mode=self._mode,
                now=time.time(),
                cooldown_until=self._cooldown_until,
            )

            notification_ids: list[int] = []
            if batch.alerts:
                notification_ids = await NotificationRepository(
                    session
                ).bulk_create([_to_notification(alert) for alert in batch.alerts])

        await self._publish_and_save(batch.alerts, notification_ids, batch.zone_state)

        if self._mode is AlertMode.EVERY_REPORT and batch.fired_pairs:
            self._arm_cooldowns(batch.fired_pairs)

        self.metrics.alerts += len(batch.alerts)

    async def _load_state(self, latest: dict[int, Position]) -> dict[int, frozenset[int]]:
        device_ids = list(latest)
        raw = await self._redis.hmget(
            DEVICE_ZONES, [str(device_id) for device_id in device_ids]
        )
        return {
            device_id: decode_zone_state(value)
            for device_id, value in zip(device_ids, raw, strict=True)
            if value
        }

    async def _publish_and_save(
        self,
        alerts: list[GeofenceAlert],
        notification_ids: list[int],
        zone_state: dict[int, frozenset[int]],
    ) -> None:
        if not alerts and not zone_state:
            return

        pipe = self._redis.pipeline(transaction=False)

        for index, alert in enumerate(alerts):
            message = AlertMessage(
                event=alert.event,  # type: ignore[arg-type]
                geozone_id=alert.geozone_id,
                device_id=alert.device_id,
                lat=alert.lat,
                lon=alert.lon,
                ts=alert.ts,
                notification_id=(
                    notification_ids[index] if index < len(notification_ids) else None
                ),
            )
            pipe.publish(alerts_channel(alert.user_id), _encode(message))

        entered = {
            str(device_id): encode_zone_state(zones)
            for device_id, zones in zone_state.items()
            if zones
        }
        left = [
            str(device_id) for device_id, zones in zone_state.items() if not zones
        ]
        if entered:
            pipe.hset(DEVICE_ZONES, mapping=entered)
        if left:
            pipe.hdel(DEVICE_ZONES, *left)

        await pipe.execute()

    def _arm_cooldowns(self, pairs: Iterable[tuple[int, int]]) -> None:
        until = time.time() + self._cooldown_s
        for pair in pairs:
            self._cooldown_until[pair] = until
        if len(self._cooldown_until) > 100_000:
            now = time.time()
            self._cooldown_until = {
                pair: expiry
                for pair, expiry in self._cooldown_until.items()
                if expiry > now
            }

    async def lag(self) -> int:
        try:
            groups = await self._redis.xinfo_groups(POSITIONS_STREAM)
        except ResponseError:
            return 0
        for group in groups:
            if group.get("name") == GEOFENCE_GROUP:
                return int(group.get("lag") or 0)
        return 0

    def snapshot(self) -> dict[str, float | int]:
        return asdict(self.metrics)


def _to_notification(alert: GeofenceAlert) -> NotificationCreateDTO:
    try:
        occurred_at = datetime.fromtimestamp(alert.ts, UTC)
    except (OverflowError, OSError, ValueError):
        occurred_at = datetime.now(UTC)
    return NotificationCreateDTO(
        user_id=alert.user_id,
        geozone_id=alert.geozone_id,
        device_id=alert.device_id,
        event=alert.event,
        lat=alert.lat,
        lon=alert.lon,
        occurred_at=occurred_at,
    )


def _parse(
    entries: list[tuple[str, dict[str, str]]],
) -> tuple[list[Position], list[str], int]:
    positions: list[Position] = []
    entry_ids: list[str] = []
    malformed = 0

    for entry_id, fields in entries:
        entry_ids.append(entry_id)
        try:
            positions.append(
                Position(
                    device_id=int(fields["device_id"]),
                    lat=float(fields["lat"]),
                    lon=float(fields["lon"]),
                    ts=float(fields["ts"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            malformed += 1

    return positions, entry_ids, malformed
