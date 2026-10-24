import asyncio
import logging
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import msgspec
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.redis_keys import DEVICE_LAST_POSITION, POSITIONS_STREAM
from app.schemas.events import Position

logger = logging.getLogger(__name__)

_single_decoder = msgspec.json.Decoder(Position)
_batch_decoder = msgspec.json.Decoder(list[Position])


def decode_positions(raw: bytes | str) -> list[Position]:
    payload = raw.encode() if isinstance(raw, str) else raw
    if payload.lstrip()[:1] == b"[":
        return _batch_decoder.decode(payload)
    return [_single_decoder.decode(payload)]


@dataclass(slots=True)
class IngestMetrics:
    accepted: int = 0
    rejected: int = 0
    dropped: int = 0
    written: int = 0
    flushes: int = 0
    flush_failures: int = 0
    buffered: int = 0
    last_flush_ms: float = 0.0


class PositionIngestor:
    def __init__(
        self,
        redis: Redis,
        *,
        buffer_maxsize: int,
        flush_interval: float,
        stream_maxlen: int,
    ) -> None:
        self._redis = redis
        self._buffer: deque[Position] = deque(maxlen=buffer_maxsize)
        self._flush_interval = flush_interval
        self._stream_maxlen = stream_maxlen
        self._task: asyncio.Task[None] | None = None
        self.metrics = IngestMetrics()

    def submit(self, positions: Sequence[Position]) -> None:
        buffer = self._buffer
        maxsize = buffer.maxlen
        metrics = self.metrics
        for position in positions:
            if len(buffer) == maxsize:
                metrics.dropped += 1
            buffer.append(position)
        metrics.accepted += len(positions)

    async def flush(self) -> int:
        buffer = self._buffer
        if not buffer:
            return 0

        batch = list(buffer)
        buffer.clear()

        started = time.perf_counter()
        pipe = self._redis.pipeline(transaction=False)
        for position in batch:
            pipe.xadd(
                POSITIONS_STREAM,
                {
                    "device_id": position.device_id,
                    "lat": position.lat,
                    "lon": position.lon,
                    "ts": position.ts,
                },
                maxlen=self._stream_maxlen,
                approximate=True,
            )
        pipe.hset(
            DEVICE_LAST_POSITION,
            mapping={
                str(p.device_id): f"{p.lat},{p.lon},{p.ts}" for p in batch
            },
        )

        try:
            await pipe.execute()
        except Exception:
            self.metrics.flush_failures += 1
            logger.exception("Failed to flush %d positions to Redis", len(batch))
            return 0

        self.metrics.written += len(batch)
        self.metrics.flushes += 1
        self.metrics.last_flush_ms = (time.perf_counter() - started) * 1000
        return len(batch)

    def snapshot(self) -> dict[str, float | int]:
        self.metrics.buffered = len(self._buffer)
        return asdict(self.metrics)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval)
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected error in the ingest flush loop")

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="ingest-flusher")
            logger.info(
                "Ingest flusher started (buffer=%d, interval=%.0fms)",
                self._buffer.maxlen or 0,
                self._flush_interval * 1000,
            )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.flush()
        logger.info("Ingest flusher stopped (metrics=%s)", self.snapshot())


def create_ingestor(redis: Redis, settings: Settings) -> PositionIngestor:
    return PositionIngestor(
        redis,
        buffer_maxsize=settings.INGEST_BUFFER_MAXSIZE,
        flush_interval=settings.INGEST_FLUSH_INTERVAL_MS / 1000,
        stream_maxlen=settings.INGEST_STREAM_MAXLEN,
    )
