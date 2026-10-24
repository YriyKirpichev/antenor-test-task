import asyncio
import logging
import os
import signal

from app.clients.redis import redis_lifespan
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.services.geofence import AlertMode
from app.worker.geofence import GeofenceConsumer
from app.worker.history import HistoryConsumer

logger = logging.getLogger(__name__)


async def _sleep_or_stop(stop: asyncio.Event, delay: float) -> bool:
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay)
    except TimeoutError:
        return False
    return True


async def _report(
    geofence: GeofenceConsumer,
    history: HistoryConsumer,
    stop: asyncio.Event,
    interval: float,
) -> None:
    while not stop.is_set():
        if await _sleep_or_stop(stop, interval):
            return

        fence = geofence.snapshot()
        logger.info(
            "geofence: %d batches, %d entries, %d devices, %d hits, %d alerts, "
            "malformed %d, failures %d, last batch %.0fms, lag %d",
            fence["batches"],
            fence["entries"],
            fence["devices"],
            fence["hits"],
            fence["alerts"],
            fence["malformed"],
            fence["failures"],
            fence["last_batch_ms"],
            await geofence.lag(),
        )

        archive = history.snapshot()
        logger.info(
            "history: %d rows in %d batches (last %d rows in %.0fms), "
            "malformed %d, failures %d, pending %d, lag %d",
            archive["rows"],
            archive["batches"],
            archive["last_batch_rows"],
            archive["last_copy_ms"],
            archive["malformed"],
            archive["failures"],
            await history.pending_count(),
            await history.lag(),
        )


async def run(settings: Settings) -> None:
    engine = create_engine(
        settings, pool_size=settings.WORKER_DB_POOL_SIZE, max_overflow=0
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    instance = f"{os.uname().nodename}-{os.getpid()}"

    try:
        async with redis_lifespan(settings) as redis:
            geofence = GeofenceConsumer(
                redis,
                create_session_factory(engine),
                consumer_name=f"geofence-{instance}",
                batch_size=settings.GEOFENCE_BATCH_SIZE,
                block_ms=settings.GEOFENCE_BLOCK_MS,
                mode=AlertMode(settings.ALERT_MODE),
                cooldown_s=settings.ALERT_COOLDOWN_S,
            )
            history = HistoryConsumer(
                redis,
                engine,
                consumer_name=f"history-{instance}",
                batch_size=settings.HISTORY_BATCH_SIZE,
                block_ms=settings.HISTORY_BLOCK_MS,
                partition_ahead_days=settings.HISTORY_PARTITION_AHEAD_DAYS,
            )

            await geofence.setup()
            await history.setup()

            async with asyncio.TaskGroup() as tg:
                tg.create_task(geofence.run(stop), name="geofence")
                tg.create_task(history.run(stop), name="history")
                tg.create_task(
                    _report(
                        geofence, history, stop, settings.GEOFENCE_REPORT_INTERVAL_S
                    ),
                    name="worker-report",
                )
            logger.info(
                "Consumers stopped (geofence=%s, history=%s)",
                geofence.snapshot(),
                history.snapshot(),
            )
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    configure_logging()
    logger.info("Starting worker (env=%s)", settings.ENV)
    asyncio.run(run(settings))
    logger.info("Worker shutdown complete")


if __name__ == "__main__":
    main()
