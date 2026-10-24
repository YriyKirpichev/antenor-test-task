from fastapi import APIRouter, status

from app.api.deps import GeozoneRepoDep, UserIdDep
from app.core.exceptions import NotFoundError
from app.schemas.geozone import GeozoneCreate, GeozoneRead, GeozoneUpdate

router = APIRouter(prefix="/geozones", tags=["geozones"])


@router.get("", response_model=list[GeozoneRead])
async def list_geozones(user_id: UserIdDep, repo: GeozoneRepoDep):
    return await repo.list_for_user(user_id)


@router.post("", response_model=GeozoneRead, status_code=status.HTTP_201_CREATED)
async def create_geozone(
    payload: GeozoneCreate, user_id: UserIdDep, repo: GeozoneRepoDep
):
    return await repo.create(user_id, payload.to_dto())


@router.get("/{geozone_id}", response_model=GeozoneRead)
async def get_geozone(geozone_id: int, user_id: UserIdDep, repo: GeozoneRepoDep):
    zone = await repo.get(user_id, geozone_id)
    if zone is None:
        raise NotFoundError("Geozone not found")
    return zone


@router.patch("/{geozone_id}", response_model=GeozoneRead)
async def update_geozone(
    geozone_id: int,
    payload: GeozoneUpdate,
    user_id: UserIdDep,
    repo: GeozoneRepoDep,
):
    zone = await repo.update(user_id, geozone_id, payload.to_dto())
    if zone is None:
        raise NotFoundError("Geozone not found")
    return zone


@router.delete("/{geozone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_geozone(
    geozone_id: int, user_id: UserIdDep, repo: GeozoneRepoDep
) -> None:
    if not await repo.delete(user_id, geozone_id):
        raise NotFoundError("Geozone not found")
