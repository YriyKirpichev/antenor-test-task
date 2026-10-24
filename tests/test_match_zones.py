import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.events import Position
from app.services.geofence import _MATCH_SQL, match_zones

ALICE = "alice"
BOB = "bob"


async def project(
    session: AsyncSession, lat: float, lon: float, distance_m: float, azimuth_deg: float
) -> tuple[float, float]:
    row = (
        await session.execute(
            text(
                """
                SELECT ST_Y(projected::geometry) AS lat,
                        ST_X(projected::geometry) AS lon
                FROM (
                    -- the casts pick an overload: an untyped parameter leaves
                    -- ST_Project ambiguous
                    SELECT ST_Project(
                        ST_SetSRID(
                            ST_MakePoint(
                                CAST(:lon AS double precision),
                                CAST(:lat AS double precision)
                            ),
                            4326
                        )::geography,
                        CAST(:distance AS double precision),
                        radians(CAST(:azimuth AS double precision))
                    ) AS projected
                ) AS p
                """
            ),
            {"lat": lat, "lon": lon, "distance": distance_m, "azimuth": azimuth_deg},
        )
    ).one()
    return row.lat, row.lon


def position(device_id: int, lat: float, lon: float, ts: float = 1.0) -> Position:
    return Position(device_id=device_id, lat=lat, lon=lon, ts=ts)


async def test_device_inside_the_radius_is_matched(session, make_zone):
    zone = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=1000)
    lat, lon = await project(session, 50.45, 30.52, distance_m=500, azimuth_deg=0)

    hits = await match_zones(session, [position(1, lat, lon)])

    assert [(h.device_id, h.geozone_id, h.user_id) for h in hits] == [
        (1, zone.id, ALICE)
    ]


async def test_device_outside_the_radius_is_not_matched(session, make_zone):
    await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=1000)
    lat, lon = await project(session, 50.45, 30.52, distance_m=1500, azimuth_deg=90)

    hits = await match_zones(session, [position(1, lat, lon)])

    assert hits == []


@pytest.mark.parametrize("azimuth", [0.0, 90.0, 180.0, 270.0])
async def test_radius_is_a_circle_in_every_direction(session, make_zone, azimuth):
    zone = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=1000)
    inside = await project(session, 50.45, 30.52, 990, azimuth)
    outside = await project(session, 50.45, 30.52, 1010, azimuth)

    hits = await match_zones(
        session, [position(1, *inside), position(2, *outside)]
    )

    assert [(h.device_id, h.geozone_id) for h in hits] == [(1, zone.id)]


async def test_distance_is_metres_on_the_globe_not_degrees(session, make_zone):
    equator = await make_zone(ALICE, lat=0.0, lon=0.0, radius_m=2000)
    far_north = await make_zone(ALICE, lat=70.0, lon=0.0, radius_m=2000)

    hits = await match_zones(
        session,
        [position(1, 0.0, 0.025), position(2, 70.0, 0.025)],
    )

    matched = {(h.device_id, h.geozone_id) for h in hits}
    assert matched == {(2, far_north.id)}
    assert (1, equator.id) not in matched


async def test_one_point_in_two_users_zones_yields_both_owners(session, make_zone):
    alice_zone = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=1000)
    bob_zone = await make_zone(BOB, lat=50.45, lon=30.52, radius_m=1500)

    hits = await match_zones(session, [position(1, 50.45, 30.52)])

    assert {(h.geozone_id, h.user_id) for h in hits} == {
        (alice_zone.id, ALICE),
        (bob_zone.id, BOB),
    }


async def test_a_batch_of_devices_is_matched_in_one_query(session, make_zone):
    north = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=1000)
    south = await make_zone(BOB, lat=49.00, lon=30.52, radius_m=1000)

    hits = await match_zones(
        session,
        [
            position(1, 50.4505, 30.5205),
            position(2, 49.0005, 30.5205),
            position(3, 10.0, 10.0),
        ],
    )

    assert {(h.device_id, h.geozone_id) for h in hits} == {
        (1, north.id),
        (2, south.id),
    }


async def test_zones_of_other_users_are_still_evaluated(session, make_zone):
    bob_zone = await make_zone(BOB, lat=50.45, lon=30.52, radius_m=1000)

    hits = await match_zones(session, [position(1, 50.45, 30.52)])

    assert [(h.geozone_id, h.user_id) for h in hits] == [(bob_zone.id, BOB)]


async def test_empty_batch_short_circuits(session):
    assert await match_zones(session, []) == []


async def test_device_matches_only_the_zone_it_is_in(session, make_zone):
    near = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=1000)
    await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=100)
    lat, lon = await project(session, 50.45, 30.52, distance_m=500, azimuth_deg=45)

    hits = await match_zones(session, [position(1, lat, lon)])

    assert [h.geozone_id for h in hits] == [near.id]


async def test_the_widest_zone_still_matches_at_its_edge(session, make_zone):
    await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=300)
    widest = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=5000)
    lat, lon = await project(session, 50.45, 30.52, distance_m=4990, azimuth_deg=30)

    hits = await match_zones(session, [position(1, lat, lon)])

    assert [h.geozone_id for h in hits] == [widest.id]


async def test_each_zone_keeps_its_own_radius(session, make_zone):
    small = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=300)
    large = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=1000)
    near, far = (
        await project(session, 50.45, 30.52, 200, 0),
        await project(session, 50.45, 30.52, 800, 0),
    )

    hits = await match_zones(session, [position(1, *near), position(2, *far)])

    assert {(h.device_id, h.geozone_id) for h in hits} == {
        (1, small.id),
        (1, large.id),
        (2, large.id),
    }


async def test_no_zones_means_no_hits(session):
    assert await match_zones(session, [position(1, 50.45, 30.52)]) == []


async def test_caller_can_supply_the_max_radius(session, make_zone):
    zone = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=1000)
    lat, lon = await project(session, 50.45, 30.52, distance_m=500, azimuth_deg=0)

    hits = await match_zones(
        session, [position(1, lat, lon)], max_radius_m=1000.0
    )

    assert [h.geozone_id for h in hits] == [zone.id]


async def test_the_query_can_use_the_spatial_index(session, make_zone):
    await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=1000)

    statement = _MATCH_SQL.bindparams(
        device_ids=[1], lons=[30.52], lats=[50.45], max_radius_m=1000.0
    )
    rendered = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    await session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        (await session.execute(text("EXPLAIN (COSTS OFF) " + rendered)))
        .scalars()
        .all()
    )

    assert "Index Scan using ix_geozones_center" in plan
    assert "_st_expand" in plan
