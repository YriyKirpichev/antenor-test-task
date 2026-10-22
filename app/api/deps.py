from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.core.resources import Resources


def get_resources(conn: HTTPConnection) -> Resources:
    return conn.app.state.resources


ResourcesDep = Annotated[Resources, Depends(get_resources)]


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


