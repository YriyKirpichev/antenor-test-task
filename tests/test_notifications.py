from datetime import UTC, datetime, timedelta

from app.dto.notification import NotificationCreateDTO
from app.repositories.notification import NotificationRepository

ALICE = "alice"
BOB = "bob"


def alert(user_id: str, geozone_id: int, device_id: int, minutes_ago: int = 0):
    return NotificationCreateDTO(
        user_id=user_id,
        geozone_id=geozone_id,
        device_id=device_id,
        event="ENTER",
        lat=50.45,
        lon=30.52,
        occurred_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


async def test_bulk_create_returns_ids_in_input_order(session, make_zone):
    zone = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=500)
    repository = NotificationRepository(session)
    devices = [101, 102, 103, 104, 105]

    ids = await repository.bulk_create(
        [alert(ALICE, zone.id, device_id) for device_id in devices]
    )

    assert len(ids) == len(devices)
    stored = {n.id: n.device_id for n in await repository.list_for_user(ALICE)}
    assert [stored[notification_id] for notification_id in ids] == devices


async def test_bulk_create_of_nothing_is_a_no_op(session):
    assert await NotificationRepository(session).bulk_create([]) == []


async def test_notifications_are_isolated_per_user(session, make_zone):
    alice_zone = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=500)
    bob_zone = await make_zone(BOB, lat=50.45, lon=30.52, radius_m=500)
    repository = NotificationRepository(session)
    await repository.bulk_create(
        [alert(ALICE, alice_zone.id, 1), alert(BOB, bob_zone.id, 2)]
    )

    for_alice = await repository.list_for_user(ALICE)
    for_bob = await repository.list_for_user(BOB)

    assert [n.device_id for n in for_alice] == [1]
    assert [n.device_id for n in for_bob] == [2]


async def test_since_id_returns_only_what_was_missed(session, make_zone):
    zone = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=500)
    repository = NotificationRepository(session)
    seen = await repository.bulk_create(
        [alert(ALICE, zone.id, 1), alert(ALICE, zone.id, 2)]
    )
    missed = await repository.bulk_create(
        [alert(ALICE, zone.id, 3), alert(ALICE, zone.id, 4)]
    )

    backfill = await repository.list_for_user(ALICE, since_id=max(seen))

    assert sorted(n.id for n in backfill) == sorted(missed)
    assert sorted(n.device_id for n in backfill) == [3, 4]


async def test_newest_first_and_limited(session, make_zone):
    zone = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=500)
    repository = NotificationRepository(session)
    await repository.bulk_create(
        [alert(ALICE, zone.id, device_id) for device_id in (1, 2, 3)]
    )

    newest = await repository.list_for_user(ALICE, limit=2)

    assert [n.device_id for n in newest] == [3, 2]


async def test_deleting_a_zone_takes_its_alerts(session, make_zone):
    from app.repositories.geozone import GeozoneRepository

    zone = await make_zone(ALICE, lat=50.45, lon=30.52, radius_m=500)
    repository = NotificationRepository(session)
    await repository.bulk_create([alert(ALICE, zone.id, 1)])

    await GeozoneRepository(session).delete(ALICE, zone.id)

    assert await repository.list_for_user(ALICE) == []
