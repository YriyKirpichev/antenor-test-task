from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import create_engine
from app.dto.geozone import GeozoneCreateDTO, GeozoneDTO
from app.repositories.geozone import GeozoneRepository


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
async def connection(settings: Settings) -> AsyncIterator[AsyncConnection]:
    engine = create_engine(settings, pool_size=1, max_overflow=0)
    try:
        try:
            conn = await engine.connect()
        except Exception as exc:
            pytest.skip(f"PostgreSQL with PostGIS is not reachable: {exc}")

        try:
            transaction = await conn.begin()
            try:
                await conn.execute(text("DELETE FROM geozones"))
                yield conn
            finally:
                await transaction.rollback()
        finally:
            await conn.close()
    finally:
        await engine.dispose()


@pytest.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    async with factory() as session:
        yield session


ZoneFactory = Callable[..., Awaitable[GeozoneDTO]]


@pytest.fixture
async def make_zone(session: AsyncSession) -> ZoneFactory:
    repository = GeozoneRepository(session)
    counter = 0

    async def _make(
        user_id: str,
        lat: float,
        lon: float,
        radius_m: float,
        name: str | None = None,
    ) -> GeozoneDTO:
        nonlocal counter
        counter += 1
        return await repository.create(
            user_id,
            GeozoneCreateDTO(
                name=name or f"zone-{counter}",
                lat=lat,
                lon=lon,
                radius_m=radius_m,
            ),
        )

    return _make
