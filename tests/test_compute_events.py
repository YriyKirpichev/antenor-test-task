from app.schemas.events import Position
from app.services.geofence import (
    AlertMode,
    ZoneHit,
    compute_events,
    decode_zone_state,
    encode_zone_state,
    latest_per_device,
)

ALICE = "alice"
BOB = "bob"


def position(device_id: int, lat: float = 50.45, lon: float = 30.52, ts: float = 1.0):
    return Position(device_id=device_id, lat=lat, lon=lon, ts=ts)


def batch(*positions: Position) -> dict[int, Position]:
    return {p.device_id: p for p in positions}


class TestEnterMode:
    def test_first_report_inside_a_zone_alerts(self):
        result = compute_events(
            batch(position(1)), [ZoneHit(1, 10, ALICE)], previous_state={}
        )

        assert len(result.alerts) == 1
        alert = result.alerts[0]
        assert (alert.device_id, alert.geozone_id, alert.event) == (1, 10, "ENTER")
        assert alert.user_id == ALICE
        assert result.zone_state == {1: frozenset({10})}

    def test_staying_inside_does_not_alert_again(self):
        result = compute_events(
            batch(position(1)),
            [ZoneHit(1, 10, ALICE)],
            previous_state={1: frozenset({10})},
        )

        assert result.alerts == []
        assert result.zone_state == {}

    def test_leaving_clears_state_without_alerting(self):
        result = compute_events(
            batch(position(1)), hits=[], previous_state={1: frozenset({10})}
        )

        assert result.alerts == []
        assert result.zone_state == {1: frozenset()}

    def test_re_entering_alerts_again(self):
        left = compute_events(
            batch(position(1)), hits=[], previous_state={1: frozenset({10})}
        )
        returned = compute_events(
            batch(position(1)),
            [ZoneHit(1, 10, ALICE)],
            previous_state=left.zone_state,
        )

        assert [a.event for a in returned.alerts] == ["ENTER"]

    def test_staying_outside_writes_no_state(self):
        result = compute_events(batch(position(1)), hits=[], previous_state={})

        assert result.alerts == []
        assert result.zone_state == {}

    def test_overlapping_zones_alert_once_each(self):
        result = compute_events(
            batch(position(1)),
            [ZoneHit(1, 10, ALICE), ZoneHit(1, 20, ALICE)],
            previous_state={},
        )

        assert [(a.geozone_id, a.event) for a in result.alerts] == [
            (10, "ENTER"),
            (20, "ENTER"),
        ]
        assert result.zone_state == {1: frozenset({10, 20})}

    def test_entering_a_second_zone_alerts_only_for_that_zone(self):
        result = compute_events(
            batch(position(1)),
            [ZoneHit(1, 10, ALICE), ZoneHit(1, 20, ALICE)],
            previous_state={1: frozenset({10})},
        )

        assert [a.geozone_id for a in result.alerts] == [20]
        assert result.zone_state == {1: frozenset({10, 20})}

    def test_alerts_go_to_the_zone_owner(self):
        result = compute_events(
            batch(position(1)),
            [ZoneHit(1, 10, ALICE), ZoneHit(1, 20, BOB)],
            previous_state={},
        )

        assert {(a.geozone_id, a.user_id) for a in result.alerts} == {
            (10, ALICE),
            (20, BOB),
        }

    def test_alert_carries_the_reported_position(self):
        reported = position(1, lat=12.5, lon=-7.25, ts=1792766356.5)

        result = compute_events(batch(reported), [ZoneHit(1, 10, ALICE)], {})

        alert = result.alerts[0]
        assert (alert.lat, alert.lon, alert.ts) == (12.5, -7.25, 1792766356.5)

    def test_several_devices_are_diffed_independently(self):
        result = compute_events(
            batch(position(1), position(2), position(3)),
            [ZoneHit(1, 10, ALICE), ZoneHit(2, 10, ALICE)],
            previous_state={2: frozenset({10}), 3: frozenset({10})},
        )

        assert [(a.device_id, a.event) for a in result.alerts] == [(1, "ENTER")]
        assert result.zone_state == {1: frozenset({10}), 3: frozenset()}

    def test_hit_for_a_device_outside_the_batch_is_ignored(self):
        result = compute_events(batch(position(1)), [ZoneHit(99, 10, ALICE)], {})

        assert result.alerts == []

    def test_empty_batch_is_a_no_op(self):
        result = compute_events({}, [], {})

        assert (result.alerts, result.zone_state, result.fired_pairs) == ([], {}, [])

    def test_fired_pairs_mirror_the_alerts(self):
        result = compute_events(
            batch(position(1), position(2)),
            [ZoneHit(1, 10, ALICE), ZoneHit(2, 20, BOB)],
            previous_state={},
        )

        assert result.fired_pairs == [(1, 10), (2, 20)]


class TestEveryReportMode:
    def test_alerts_on_every_report_inside(self):
        result = compute_events(
            batch(position(1)),
            [ZoneHit(1, 10, ALICE)],
            previous_state={1: frozenset({10})},
            mode=AlertMode.EVERY_REPORT,
            now=100.0,
        )

        assert [a.event for a in result.alerts] == ["INSIDE"]

    def test_first_report_is_still_an_enter(self):
        result = compute_events(
            batch(position(1)),
            [ZoneHit(1, 10, ALICE)],
            previous_state={},
            mode=AlertMode.EVERY_REPORT,
            now=100.0,
        )

        assert [a.event for a in result.alerts] == ["ENTER"]

    def test_cooldown_suppresses_a_repeat(self):
        result = compute_events(
            batch(position(1)),
            [ZoneHit(1, 10, ALICE)],
            previous_state={1: frozenset({10})},
            mode=AlertMode.EVERY_REPORT,
            now=100.0,
            cooldown_until={(1, 10): 160.0},
        )

        assert result.alerts == []

    def test_expired_cooldown_lets_the_alert_through(self):
        result = compute_events(
            batch(position(1)),
            [ZoneHit(1, 10, ALICE)],
            previous_state={1: frozenset({10})},
            mode=AlertMode.EVERY_REPORT,
            now=200.0,
            cooldown_until={(1, 10): 160.0},
        )

        assert [a.event for a in result.alerts] == ["INSIDE"]

    def test_cooldown_is_per_device_and_zone(self):
        result = compute_events(
            batch(position(1), position(2)),
            [ZoneHit(1, 10, ALICE), ZoneHit(2, 10, ALICE)],
            previous_state={1: frozenset({10}), 2: frozenset({10})},
            mode=AlertMode.EVERY_REPORT,
            now=100.0,
            cooldown_until={(1, 10): 160.0},
        )

        assert [a.device_id for a in result.alerts] == [2]


class TestLatestPerDevice:
    def test_keeps_the_freshest_report_per_device(self):
        collapsed = latest_per_device(
            [
                position(1, lat=1.0, ts=1.0),
                position(2, lat=2.0, ts=1.0),
                position(1, lat=3.0, ts=2.0),
            ]
        )

        assert set(collapsed) == {1, 2}
        assert collapsed[1].lat == 3.0

    def test_empty_batch(self):
        assert latest_per_device([]) == {}


class TestZoneStateCodec:
    def test_round_trip(self):
        state = frozenset({7, 2, 19})

        assert decode_zone_state(encode_zone_state(state)) == state

    def test_encoding_is_stable(self):
        assert encode_zone_state(frozenset({19, 2, 7})) == "2,7,19"

    def test_empty_state(self):
        assert encode_zone_state(frozenset()) == ""
        assert decode_zone_state("") == frozenset()

    def test_missing_state_is_outside_everything(self):
        assert decode_zone_state(None) == frozenset()

    def test_unreadable_state_does_not_raise(self):
        assert decode_zone_state("7,oops,2") == frozenset()
