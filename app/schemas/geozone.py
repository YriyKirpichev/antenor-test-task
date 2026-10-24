from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.dto.geozone import GeozoneCreateDTO, GeozoneUpdateDTO

Latitude = Annotated[float, Field(ge=-90.0, le=90.0)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0)]
RadiusMeters = Annotated[float, Field(gt=0.0, le=1_000_000.0)]


class GeozoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    lat: Latitude
    lon: Longitude
    radius_m: RadiusMeters

    def to_dto(self) -> GeozoneCreateDTO:
        return GeozoneCreateDTO(
            name=self.name,
            lat=self.lat,
            lon=self.lon,
            radius_m=self.radius_m,
        )


class GeozoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    lat: Latitude | None = None
    lon: Longitude | None = None
    radius_m: RadiusMeters | None = None

    def to_dto(self) -> GeozoneUpdateDTO:
        return GeozoneUpdateDTO(
            name=self.name,
            lat=self.lat,
            lon=self.lon,
            radius_m=self.radius_m,
        )


class GeozoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    lat: float
    lon: float
    radius_m: float
    created_at: datetime
    updated_at: datetime
