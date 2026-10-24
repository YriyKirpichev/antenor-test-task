from collections.abc import Sequence
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import ColumnElement, cast, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.geozone import GeozoneCreateDTO, GeozoneDTO, GeozoneUpdateDTO
from app.models import Geozone


def _point(lat: float, lon: float) -> ColumnElement[Any]:
    return func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)


_COLUMNS = (
    Geozone.id,
    Geozone.name,
    func.ST_Y(cast(Geozone.center, Geometry)).label("lat"),
    func.ST_X(cast(Geozone.center, Geometry)).label("lon"),
    Geozone.radius_m,
    Geozone.created_at,
    Geozone.updated_at,
)


class GeozoneRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: str) -> Sequence[GeozoneDTO]:
        result = await self._session.execute(
            select(*_COLUMNS).where(Geozone.user_id == user_id).order_by(Geozone.id)
        )
        return [GeozoneDTO(**row) for row in result.mappings()]

    async def get(self, user_id: str, geozone_id: int) -> GeozoneDTO | None:
        result = await self._session.execute(
            select(*_COLUMNS).where(
                Geozone.user_id == user_id, Geozone.id == geozone_id
            )
        )
        row = result.mappings().one_or_none()
        return GeozoneDTO(**row) if row is not None else None

    async def create(self, user_id: str, data: GeozoneCreateDTO) -> GeozoneDTO:
        result = await self._session.execute(
            insert(Geozone)
            .values(
                user_id=user_id,
                name=data.name,
                center=_point(data.lat, data.lon),
                radius_m=data.radius_m,
            )
            .returning(*_COLUMNS)
        )
        await self._session.commit()
        return GeozoneDTO(**result.mappings().one())

    async def update(
        self, user_id: str, geozone_id: int, data: GeozoneUpdateDTO
    ) -> GeozoneDTO | None:
        values: dict[str, object] = {}
        if data.name is not None:
            values["name"] = data.name
        if data.radius_m is not None:
            values["radius_m"] = data.radius_m
        if data.lat is not None or data.lon is not None:
            current = await self.get(user_id, geozone_id)
            if current is None:
                return None
            lat = data.lat if data.lat is not None else current.lat
            lon = data.lon if data.lon is not None else current.lon
            values["center"] = _point(lat, lon)

        if not values:
            return await self.get(user_id, geozone_id)

        result = await self._session.execute(
            update(Geozone)
            .where(Geozone.user_id == user_id, Geozone.id == geozone_id)
            .values(**values)
            .returning(*_COLUMNS)
        )
        row = result.mappings().one_or_none()
        if row is None:
            await self._session.rollback()
            return None
        await self._session.commit()
        return GeozoneDTO(**row)

    async def delete(self, user_id: str, geozone_id: int) -> bool:
        result = await self._session.execute(
            delete(Geozone).where(
                Geozone.user_id == user_id, Geozone.id == geozone_id
            )
        )
        await self._session.commit()
        return bool(result.rowcount)
