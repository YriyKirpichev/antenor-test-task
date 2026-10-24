from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import NotificationRepoDep, UserIdDep
from app.schemas.notification import NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
async def list_notifications(
    user_id: UserIdDep,
    repo: NotificationRepoDep,
    since_id: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    return await repo.list_for_user(user_id, since_id=since_id, limit=limit)
