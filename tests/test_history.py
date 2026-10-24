from datetime import UTC, date, datetime

from app.worker.history import parse_entries, partition_ddl, partition_name


def entry(
    entry_id: str = "1-0",
    device_id: str = "42",
    lat: str = "50.45",
    lon: str = "30.52",
    ts: str = "1792785550.5",
) -> tuple[str, dict[str, str]]:
    return entry_id, {"device_id": device_id, "lat": lat, "lon": lon, "ts": ts}


class TestParseEntries:
    def test_stream_fields_become_copy_tuples(self):
        records, ids, malformed = parse_entries([entry()])

        assert ids == ["1-0"]
        assert malformed == 0
        device_id, lat, lon, recorded_at = records[0]
        assert (device_id, lat, lon) == (42, 50.45, 30.52)
        assert recorded_at == datetime.fromtimestamp(1792785550.5, UTC)
        assert recorded_at.tzinfo is not None

    def test_every_entry_is_acknowledged_even_when_unusable(self):
        records, ids, malformed = parse_entries(
            [
                entry("1-0"),
                entry("2-0", lat="not-a-number"),
                entry("3-0"),
                ("4-0", {"device_id": "7"}),
            ]
        )

        assert ids == ["1-0", "2-0", "3-0", "4-0"]
        assert len(records) == 2
        assert malformed == 2

    def test_an_unrepresentable_clock_is_counted_not_raised(self):
        records, ids, malformed = parse_entries([entry(ts="999999999999999")])

        assert (records, ids, malformed) == ([], ["1-0"], 1)

    def test_empty_batch(self):
        assert parse_entries([]) == ([], [], 0)


class TestPartitions:
    def test_name_is_derived_from_the_day(self):
        assert partition_name(date(2026, 10, 23)) == "device_positions_20261023"

    def test_bounds_cover_exactly_one_utc_day(self):
        ddl = partition_ddl(date(2026, 10, 23))

        assert "FROM ('2026-10-23 00:00:00+00')" in ddl
        assert "TO ('2026-10-24 00:00:00+00')" in ddl

    def test_month_and_year_boundaries_roll_over(self):
        assert "TO ('2026-11-01 00:00:00+00')" in partition_ddl(date(2026, 10, 31))
        assert "TO ('2027-01-01 00:00:00+00')" in partition_ddl(date(2026, 12, 31))

    def test_creation_is_idempotent(self):
        assert "IF NOT EXISTS" in partition_ddl(date(2026, 10, 23))
