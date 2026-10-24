from fastapi import APIRouter

from app.api.v1.endpoints import geozones, notifications

api_router = APIRouter()
api_router.include_router(geozones.router)
api_router.include_router(notifications.router)
