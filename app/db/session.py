import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings

logger = logging.getLogger(__name__)


def create_engine(
    settings: Settings,
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
) -> AsyncEngine:
    return create_async_engine(
        str(settings.database_url),
        echo=settings.DB_ECHO,
        pool_size=pool_size if pool_size is not None else settings.DB_POOL_SIZE,
        max_overflow=(
            max_overflow if max_overflow is not None else settings.DB_MAX_OVERFLOW
        ),
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@asynccontextmanager
async def database_lifespan(settings: Settings) -> AsyncGenerator[AsyncEngine]:
    engine = create_engine(settings)
    logger.info("Database engine created")
    try:
        yield engine
    finally:
        await engine.dispose()
        logger.info("Database engine disposed")
