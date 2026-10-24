import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings
from app.core.resources import Resources
from app.services.alerts import AlertsListener
from app.services.connections import ConnectionManager
from app.services.ingest import PositionIngestor, create_ingestor
from app.services.map_stream import MapBroadcaster, create_map_broadcaster

logger = logging.getLogger(__name__)


class BackgroundService(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


@dataclass(slots=True, frozen=True)
class Services:
    ingestor: PositionIngestor
    connections: ConnectionManager
    map_broadcaster: MapBroadcaster
    alerts: AlertsListener


@asynccontextmanager
async def _running(service: BackgroundService) -> AsyncGenerator[None]:
    await service.start()
    try:
        yield
    finally:
        await service.stop()


@asynccontextmanager
async def build_services(
    resources: Resources, settings: Settings
) -> AsyncGenerator[Services]:
    connections = ConnectionManager(queue_maxsize=settings.WS_CLIENT_QUEUE_MAXSIZE)
    ingestor = create_ingestor(resources.redis, settings)
    map_broadcaster = create_map_broadcaster(resources.redis, connections, settings)
    alerts = AlertsListener(resources.redis, connections)

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(_running(ingestor))
        await stack.enter_async_context(_running(map_broadcaster))
        await stack.enter_async_context(_running(alerts))

        logger.info("Background services started")
        yield Services(
            ingestor=ingestor,
            connections=connections,
            map_broadcaster=map_broadcaster,
            alerts=alerts,
        )
    logger.info("Background services stopped")
