import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.clients.redis import redis_lifespan
from app.core.config import Settings
from app.db.session import create_session_factory, database_lifespan

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class Resources:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis


@asynccontextmanager
async def build_resources(settings: Settings) -> AsyncGenerator[Resources]:
    async with AsyncExitStack() as stack:
        engine = await stack.enter_async_context(database_lifespan(settings))
        redis = await stack.enter_async_context(redis_lifespan(settings))

        logger.info("All resources initialized")
        yield Resources(
            settings=settings,
            engine=engine,
            session_factory=create_session_factory(engine),
            redis=redis,
        )
    logger.info("All resources released")
