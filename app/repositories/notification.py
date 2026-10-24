from collections.abc import Sequence
from dataclasses import asdict

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.notification import NotificationCreateDTO, NotificationDTO
from app.models import Notification


_COLUMNS = (
    Notification.id,
    Notification.geozone_id,
    Notification.device_id,
    Notification.event,
    Notification.lat,
    Notification.lon,
    Notification.occurred_at,
    Notification.created_at,
)


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(
        self, user_id: str, *, since_id: int | None = None, limit: int = 100
    ) -> Sequence[NotificationDTO]:
        stmt = select(*_COLUMNS).where(Notification.user_id == user_id)
        if since_id is not None:
            stmt = stmt.where(Notification.id > since_id)
        stmt = stmt.order_by(Notification.id.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return [NotificationDTO(**row) for row in result.mappings()]

    async def bulk_create(
        self, rows: Sequence[NotificationCreateDTO]
    ) -> list[int]:
        if not rows:
            return []
        result = await self._session.execute(
            insert(Notification).returning(
                Notification.id, sort_by_parameter_order=True
            ),
            [asdict(row) for row in rows],
        )
        ids = list(result.scalars())
        await self._session.commit()
        return ids
