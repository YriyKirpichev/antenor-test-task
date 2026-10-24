from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    geozone_id: int
    device_id: int
    event: str
    lat: float
    lon: float
    occurred_at: datetime
    created_at: datetime
