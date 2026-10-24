from typing import Annotated, Literal

import msgspec

DeviceId = Annotated[int, msgspec.Meta(ge=1)]
Latitude = Annotated[float, msgspec.Meta(ge=-90.0, le=90.0)]
Longitude = Annotated[float, msgspec.Meta(ge=-180.0, le=180.0)]
Timestamp = Annotated[float, msgspec.Meta(ge=0.0)]


class Position(msgspec.Struct, frozen=True, gc=False):
    device_id: DeviceId
    lat: Latitude
    lon: Longitude
    ts: Timestamp


class PositionBatch(msgspec.Struct, frozen=True, gc=False):
    positions: list[Position]


class BBox(msgspec.Struct, frozen=True, gc=False):
    min_lat: Latitude
    min_lon: Longitude
    max_lat: Latitude
    max_lon: Longitude

    def contains(self, lat: float, lon: float) -> bool:
        return (
            self.min_lat <= lat <= self.max_lat
            and self.min_lon <= lon <= self.max_lon
        )


class SetBBox(msgspec.Struct, tag="bbox", tag_field="type", frozen=True, gc=False):
    bbox: BBox | None = None


class MapSnapshot(
    msgspec.Struct, tag="snapshot", tag_field="type", frozen=True, gc=False
):
    ts: float
    count: int
    devices: list[tuple[int, float, float, float]]


class AlertMessage(
    msgspec.Struct, tag="alert", tag_field="type", frozen=True, gc=False
):
    event: Literal["ENTER", "INSIDE"]
    geozone_id: int
    device_id: int
    lat: float
    lon: float
    ts: float
    notification_id: int | None = None
