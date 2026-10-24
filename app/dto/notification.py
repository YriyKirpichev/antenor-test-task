from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class NotificationDTO:
    id: int
    geozone_id: int
    device_id: int
    event: str
    lat: float
    lon: float
    occurred_at: datetime
    created_at: datetime


@dataclass(slots=True, frozen=True)
class NotificationCreateDTO:
    user_id: str
    geozone_id: int
    device_id: int
    event: str
    lat: float
    lon: float
    occurred_at: datetime
