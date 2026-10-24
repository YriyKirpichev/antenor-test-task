from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import (
    AlertsListenerDep,
    ConnectionManagerDep,
    IngestorDep,
    MapBroadcasterDep,
    RedisDep,
    SessionDep,
)

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(session: SessionDep, redis: RedisDep) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    await redis.ping()
    return {"status": "ok", "database": "ok", "redis": "ok"}


@router.get("/stats")
async def stats(
    ingestor: IngestorDep,
    manager: ConnectionManagerDep,
    broadcaster: MapBroadcasterDep,
    alerts: AlertsListenerDep,
) -> dict[str, dict[str, float | int]]:
    return {
        "ingest": ingestor.snapshot(),
        "live": manager.snapshot(),
        "map": broadcaster.snapshot(),
        "alerts": alerts.snapshot(),
    }
