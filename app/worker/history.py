import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.redis_keys import POSITIONS_STREAM

logger = logging.getLogger(__name__)

HISTORY_GROUP = "history"

TABLE = "device_positions"
COLUMNS = ["device_id", "lat", "lon", "recorded_at"]

Record = tuple[int, float, float, datetime]


def partition_name(day: date) -> str:
    return f"{TABLE}_{day:%Y%m%d}"


def partition_ddl(day: date) -> str:
    return (
        f'CREATE TABLE IF NOT EXISTS "{partition_name(day)}" '
        f"PARTITION OF {TABLE} FOR VALUES "
        f"FROM ('{day.isoformat()} 00:00:00+00') "
        f"TO ('{(day + timedelta(days=1)).isoformat()} 00:00:00+00')"
    )


def parse_entries(
    entries: list[tuple[str, dict[str, str]]],
) -> tuple[list[Record], list[str], int]:
    records: list[Record] = []
    entry_ids: list[str] = []
    malformed = 0

    for entry_id, fields in entries:
        entry_ids.append(entry_id)
        try:
            records.append(
                (
                    int(fields["device_id"]),
                    float(fields["lat"]),
                    float(fields["lon"]),
                    datetime.fromtimestamp(float(fields["ts"]), UTC),
                )
            )
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            malformed += 1

    return records, entry_ids, malformed


@dataclass(slots=True)
class HistoryMetrics:
    batches: int = 0
    rows: int = 0
    malformed: int = 0
    failures: int = 0
    last_batch_rows: int = 0
    last_copy_ms: float = 0.0


class HistoryConsumer:
    def __init__(
        self,
        redis: Redis,
        engine: AsyncEngine,
        *,
        consumer_name: str,
        batch_size: int,
        block_ms: int,
        partition_ahead_days: int,
    ) -> None:
        self._redis = redis
        self._engine = engine
        self._consumer_name = consumer_name
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._partition_ahead_days = partition_ahead_days
        self._draining_pending = True
        self._partitions_for: date | None = None
        self.metrics = HistoryMetrics()

    async def setup(self) -> None:
        try:
            await self._redis.xgroup_create(
                POSITIONS_STREAM, HISTORY_GROUP, id="0", mkstream=True
            )
            logger.info("Created consumer group %r", HISTORY_GROUP)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        await self.ensure_partitions()

    async def ensure_partitions(self) -> None:
        today = datetime.now(UTC).date()
        for offset in range(self._partition_ahead_days + 1):
            day = today + timedelta(days=offset)
            try:
                async with self._engine.begin() as conn:
                    await conn.execute(text(partition_ddl(day)))
            except Exception:
                logger.exception(
                    "Could not ensure partition %s", partition_name(day)
                )
        self._partitions_for = today

    async def run(self, stop: asyncio.Event) -> None:
        logger.info(
            "History consumer %r started (batch=%d, block=%dms)",
            self._consumer_name,
            self._batch_size,
            self._block_ms,
        )
        while not stop.is_set():
            try:
                if self._partitions_for != datetime.now(UTC).date():
                    await self.ensure_partitions()
                await self._step()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.metrics.failures += 1
                logger.exception("History batch failed; retrying")
                await asyncio.sleep(1.0)

    async def _step(self) -> int:
        stream_id = "0" if self._draining_pending else ">"
        response = await self._redis.xreadgroup(
            groupname=HISTORY_GROUP,
            consumername=self._consumer_name,
            streams={POSITIONS_STREAM: stream_id},
            count=self._batch_size,
            block=None if self._draining_pending else self._block_ms,
        )

        entries = response[0][1] if response else []
        if not entries:
            if self._draining_pending:
                logger.info("Pending entries drained; following the stream live")
                self._draining_pending = False
            return 0

        records, entry_ids, malformed = parse_entries(entries)
        if records:
            await self._copy(records)

        await self._redis.xack(POSITIONS_STREAM, HISTORY_GROUP, *entry_ids)

        self.metrics.batches += 1
        self.metrics.rows += len(records)
        self.metrics.malformed += malformed
        self.metrics.last_batch_rows = len(records)
        return len(entry_ids)

    async def _copy(self, records: list[Record]) -> None:
        started = time.perf_counter()
        async with self._engine.begin() as conn:
            raw = await conn.get_raw_connection()
            await raw.driver_connection.copy_records_to_table(
                TABLE, records=records, columns=COLUMNS
            )
        self.metrics.last_copy_ms = (time.perf_counter() - started) * 1000

    async def pending_count(self) -> int:
        return await self._group_field("pending")

    async def lag(self) -> int:
        return await self._group_field("lag")

    async def _group_field(self, field: str) -> int:
        try:
            groups = await self._redis.xinfo_groups(POSITIONS_STREAM)
        except ResponseError:
            return 0
        for group in groups:
            if group.get("name") == HISTORY_GROUP:
                return int(group.get(field) or 0)
        return 0

    def snapshot(self) -> dict[str, float | int]:
        return asdict(self.metrics)
