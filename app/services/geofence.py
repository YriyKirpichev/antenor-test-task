from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import ARRAY, BigInteger, Float, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.events import Position


class AlertMode(StrEnum):
    ENTER = "enter"
    EVERY_REPORT = "every_report"


@dataclass(slots=True, frozen=True)
class ZoneHit:
    device_id: int
    geozone_id: int
    user_id: str


@dataclass(slots=True, frozen=True)
class GeofenceAlert:
    user_id: str
    device_id: int
    geozone_id: int
    event: str
    lat: float
    lon: float
    ts: float


@dataclass(slots=True, frozen=True)
class GeofenceBatch:
    alerts: list[GeofenceAlert] = field(default_factory=list)
    zone_state: dict[int, frozenset[int]] = field(default_factory=dict)
    fired_pairs: list[tuple[int, int]] = field(default_factory=list)


_MAX_RADIUS_SQL = text("SELECT coalesce(max(radius_m), 0.0) FROM geozones")

_MATCH_SQL = text(
    """
    SELECT p.device_id, z.id AS geozone_id, z.user_id
    FROM unnest(:device_ids, :lons, :lats) AS p(device_id, lon, lat)
    JOIN geozones z
        ON ST_DWithin(
            z.center,
            ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)::geography,
            :max_radius_m
        )
        AND ST_DWithin(
            z.center,
            ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)::geography,
            z.radius_m
        )
    """
).bindparams(
    bindparam("device_ids", type_=ARRAY(BigInteger)),
    bindparam("lons", type_=ARRAY(Float)),
    bindparam("lats", type_=ARRAY(Float)),
    bindparam("max_radius_m", type_=Float),
)


def encode_zone_state(zone_ids: frozenset[int]) -> str:
    return ",".join(str(zone_id) for zone_id in sorted(zone_ids))


def decode_zone_state(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    try:
        return frozenset(int(part) for part in raw.split(",") if part)
    except ValueError:
        return frozenset()


def latest_per_device(positions: Iterable[Position]) -> dict[int, Position]:
    latest: dict[int, Position] = {}
    for position in positions:
        latest[position.device_id] = position
    return latest


async def match_zones(
    session: AsyncSession,
    positions: Sequence[Position],
    *,
    max_radius_m: float | None = None,
) -> list[ZoneHit]:
    if not positions:
        return []

    if max_radius_m is None:
        max_radius_m = float(
            (await session.execute(_MAX_RADIUS_SQL)).scalar_one()
        )
    if max_radius_m <= 0.0:
        return []

    result = await session.execute(
        _MATCH_SQL,
        {
            "device_ids": [p.device_id for p in positions],
            "lons": [p.lon for p in positions],
            "lats": [p.lat for p in positions],
            "max_radius_m": max_radius_m,
        },
    )
    return [
        ZoneHit(device_id=row.device_id, geozone_id=row.geozone_id, user_id=row.user_id)
        for row in result
    ]


def compute_events(
    positions: Mapping[int, Position],
    hits: Iterable[ZoneHit],
    previous_state: Mapping[int, frozenset[int]],
    *,
    mode: AlertMode = AlertMode.ENTER,
    now: float = 0.0,
    cooldown_until: Mapping[tuple[int, int], float] | None = None,
) -> GeofenceBatch:
    cooldown_until = cooldown_until or {}
    batch = GeofenceBatch()

    current: dict[int, set[int]] = {}
    owners: dict[int, str] = {}
    for hit in hits:
        current.setdefault(hit.device_id, set()).add(hit.geozone_id)
        owners[hit.geozone_id] = hit.user_id

    for device_id, zones in current.items():
        position = positions.get(device_id)
        if position is None:
            continue
        previous = previous_state.get(device_id, frozenset())

        for geozone_id in sorted(zones):
            if mode is AlertMode.ENTER:
                if geozone_id in previous:
                    continue
                event = "ENTER"
            else:
                if cooldown_until.get((device_id, geozone_id), 0.0) > now:
                    continue
                event = "ENTER" if geozone_id not in previous else "INSIDE"

            batch.alerts.append(
                GeofenceAlert(
                    user_id=owners[geozone_id],
                    device_id=device_id,
                    geozone_id=geozone_id,
                    event=event,
                    lat=position.lat,
                    lon=position.lon,
                    ts=position.ts,
                )
            )
            batch.fired_pairs.append((device_id, geozone_id))

    for device_id in positions:
        now_zones = frozenset(current.get(device_id, ()))
        if now_zones != previous_state.get(device_id, frozenset()):
            batch.zone_state[device_id] = now_zones

    return batch
