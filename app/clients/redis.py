import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from redis.asyncio import Redis

from app.core.config import Settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def redis_lifespan(settings: Settings) -> AsyncGenerator[Redis]:
    client = Redis.from_url(
        str(settings.redis_dsn),
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        decode_responses=True,
        health_check_interval=30,
    )
    logger.info("Redis client created")
    try:
        yield client
    finally:
        await client.aclose()
        logger.info("Redis client closed")
