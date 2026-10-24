from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.core.resources import Resources
from app.repositories.geozone import GeozoneRepository
from app.repositories.notification import NotificationRepository
from app.services.alerts import AlertsListener
from app.services.connections import ConnectionManager
from app.services.ingest import PositionIngestor
from app.services.map_stream import MapBroadcaster
from app.services.runtime import Services


def get_resources(conn: HTTPConnection) -> Resources:
    return conn.app.state.resources


ResourcesDep = Annotated[Resources, Depends(get_resources)]


def get_services(conn: HTTPConnection) -> Services:
    return conn.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


async def get_session(resources: ResourcesDep) -> AsyncGenerator[AsyncSession]:
    async with resources.session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_redis(resources: ResourcesDep) -> Redis:
    return resources.redis


RedisDep = Annotated[Redis, Depends(get_redis)]


def get_ingestor(conn: HTTPConnection) -> PositionIngestor:
    return get_services(conn).ingestor


IngestorDep = Annotated[PositionIngestor, Depends(get_ingestor)]


def get_alerts_listener(conn: HTTPConnection) -> AlertsListener:
    return get_services(conn).alerts


AlertsListenerDep = Annotated[AlertsListener, Depends(get_alerts_listener)]


def get_connection_manager(conn: HTTPConnection) -> ConnectionManager:
    return get_services(conn).connections


ConnectionManagerDep = Annotated[ConnectionManager, Depends(get_connection_manager)]


def get_map_broadcaster(conn: HTTPConnection) -> MapBroadcaster:
    return get_services(conn).map_broadcaster


MapBroadcasterDep = Annotated[MapBroadcaster, Depends(get_map_broadcaster)]


def get_user_id(
    x_user_id: Annotated[str, Header(min_length=1, max_length=64)],
) -> str:
    return x_user_id


UserIdDep = Annotated[str, Depends(get_user_id)]


def get_ws_user_id(
    user_id: Annotated[str, Query(min_length=1, max_length=64)],
) -> str:
    return user_id


WsUserIdDep = Annotated[str, Depends(get_ws_user_id)]


def get_geozone_repository(session: SessionDep) -> GeozoneRepository:
    return GeozoneRepository(session)


GeozoneRepoDep = Annotated[GeozoneRepository, Depends(get_geozone_repository)]


def get_notification_repository(session: SessionDep) -> NotificationRepository:
    return NotificationRepository(session)


NotificationRepoDep = Annotated[
    NotificationRepository, Depends(get_notification_repository)
]
