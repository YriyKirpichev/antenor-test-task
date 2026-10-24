from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class GeozoneDTO:
    id: int
    name: str
    lat: float
    lon: float
    radius_m: float
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class GeozoneCreateDTO:
    name: str
    lat: float
    lon: float
    radius_m: float


@dataclass(slots=True, frozen=True)
class GeozoneUpdateDTO:
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    radius_m: float | None = None
