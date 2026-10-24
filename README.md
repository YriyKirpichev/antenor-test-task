# Real-Time Geo-Tracking & Alerting Service

Ingests coordinates from thousands of devices over WebSockets, streams them to
browsers as a live map, and pushes an alert when a device reports a location
inside one of a user's circular geozones.

FastAPI, PostgreSQL + PostGIS, Redis, async SQLAlchemy. The guiding rule:
**the coordinate path never touches PostgreSQL** — the API validates a report
and buffers it, a flusher moves batches into Redis, and a separate worker does
the spatial and relational work in batches.

## Build and run

Requires Docker and Docker Compose.

```bash
cp .env.example .env
docker compose up -d --build
```

Six services: `migrate` (runs `alembic upgrade head`, then exits), `api`,
`worker`, `web` (nginx: serves the built UI, proxies the API so the browser
stays on one origin), `postgis`, `redis`. `api` and `worker` start only after
the migration succeeds.

| URL | |
| --- | --- |
| <http://localhost:8080> | demo UI — map, zone CRUD, alerts |
| <http://localhost:8000/docs> | OpenAPI |
| <http://localhost:8000/stats> | ingest / live / map / alert counters |
| <http://localhost:8000/health>, `/ready` | liveness, dependency check |

Identity is mocked: REST takes an `X-User-Id` header, the browser socket takes
`?user_id=`. Any string is a user. Open the UI twice with the same id to see one
user with two sessions receiving the same alerts.

```bash
curl -X POST localhost:8000/api/v1/geozones -H 'X-User-Id: u1' \
     -H 'Content-Type: application/json' \
     -d '{"name":"Office","lat":50.45,"lon":30.52,"radius_m":1000}'

# alerts missed while disconnected (Pub/Sub keeps nothing)
curl 'localhost:8000/api/v1/notifications?since_id=0' -H 'X-User-Id: u1'
```

Endpoints: `GET/POST /api/v1/geozones`, `GET/PATCH/DELETE
/api/v1/geozones/{id}`, `GET /api/v1/notifications`, `WS /ws/devices` (ingest),
`WS /ws/client` (live map + alerts).

Tests: `uv sync && uv run pytest` — 56 tests. The alerting rules are pure and
run anywhere; the spatial tests need PostGIS and skip with a message when it is
unreachable (`POSTGIS_HOST=localhost POSTGIS_PORT=5433` against the compose
stack). Database tests run in a transaction that is rolled back.

## Run the load generator

```bash
python generator.py
```

Configured by the constants at the top of the file: 10 000 devices, **one
WebSocket connection each**, a per-device period drawn once from 1–5 s, and a
random delta of up to 30 m on both coordinates per report. Connections open over
a 20 s ramp. It prints live connections, positions/s and failures every two
seconds; `/stats` shows the receiving side, including `dropped`.

Two things that surprise people:

* 10 000 devices with periods uniform in [1, 5] s produce **~4020 positions/s**,
  not 3333 — the rate is `N·ln(5)/4`, and short-period devices dominate.
* Devices start at random points **worldwide**, which stresses ingest but puts
  nobody inside a 1 km zone. To watch alerts fire, narrow the box and raise the
  step: `MIN_LAT/MAX_LAT = 50.30/50.60`, `MIN_LON/MAX_LON = 30.30/30.80`,
  `STEP_METERS = 150`.

## Architectural choices

### Spatial queries

`geozones.center` is `geography(Point, 4326)`, so `ST_DWithin` compares metres on
the spheroid and `radius_m` is used as given. With `geometry` the same longitude
offset would mean 2.8 km at the equator and 950 m at 70° N; a test asserts that
difference.

A batch is matched in **one query**: device ids, longitudes and latitudes go in
as three arrays and are `unnest`-ed server-side, so round trips do not grow with
the fleet. The predicate has two steps:

```sql
JOIN geozones z
  ON ST_DWithin(z.center, point, :max_radius_m)   -- constant: uses the GiST index
 AND ST_DWithin(z.center, point, z.radius_m)      -- exact, on the few candidates
```

`ST_DWithin` can only use the index on `center` when its radius is a constant.
With the per-row `z.radius_m` alone the planner tests every zone against every
point: measured over 1000 points, **5.7 s against 5000 zones versus 15 ms** with
the prefilter. The prefilter cannot hide a match, because every zone's radius is
at most the maximum. A test asserts the query plan, not just the result.

No distance is ever computed in Python.

### WebSocket state management

`ConnectionManager` holds `user_id → {Connection}`. Each connection owns a
bounded `asyncio.Queue` and a sender task that is the only thing that ever
awaits the socket; broadcasts and alerts only `put_nowait`. One client on bad
wifi therefore cannot block the broadcaster or anybody else.

On a full queue the policy depends on the payload: **map snapshots drop
oldest-first** (a stale position is worthless and the next tick is a second
away), while **alerts are not droppable** — the connection is closed with 1013
and the client reconnects and backfills from
`GET /api/v1/notifications?since_id=...`.

Several sessions per user are the normal case: alerts go to every session, and
each session keeps its own viewport. Across instances, alert fan-out is **one
`PSUBSCRIBE alerts:*` per app instance**, not one subscription per user — the
user is read out of the channel name. The API holds no shared local state beyond
its sockets, so it scales horizontally as it stands.

### High-throughput device data

Four stages, each sized so the expensive work is batched:

1. **Validate** — msgspec structs with range constraints, enforced in C. A
   malformed frame is answered and counted, not disconnected.
2. **Buffer** — a bounded `deque`; `submit()` never awaits, so a slow Redis
   cannot stall a socket. On overflow the *oldest* positions are dropped and
   counted: for live tracking only the newest point matters, and dropping is
   what keeps the event loop responsive.
3. **Flush** — one task, every 150 ms, one pipeline: `XADD` per position with
   `MAXLEN ~`, plus a single `HSET` for the batch's latest positions. ~4000
   writes/s become ~7 pipelined round trips/s. Flushes never overlap, so a slow
   Redis grows the buffer instead of queueing unbounded work.
4. **Consume** — the worker reads up to 5000 entries (`XREADGROUP ... BLOCK
   1000`), collapses them to the newest position per device, and spends one
   spatial query, one multi-row `INSERT` and one Redis pipeline on the batch.
   A second consumer group archives the same stream with `COPY` (~104k rows/s)
   into a table partitioned by day, so archiving never delays an alert.

The live map is read-mostly: once a second one `HGETALL` of `devices:last`, and
**one snapshot per distinct viewport** rather than per client — 13 ms for 10 000
devices.

Pools are small because the hot path does not use them: api `pool_size=5,
max_overflow=5` (zone REST only), worker `pool_size=3, max_overflow=0`, zero
database queries per ingested position, one spatial query per second. File
descriptors are raised to 65536 in the app and in compose: the 1024 default caps
the service at ~1000 devices, and the failure looks like a client that never
receives an HTTP response.

## Simplifications

* Authentication is mocked — `X-User-Id` / `?user_id=` with no verification, so
  one user can read another's data by typing their id. There is no user table.
* Devices are not authenticated either and there is no device registry;
  `device_id` is any positive integer. Zone ownership alone decides who is
  alerted.
* A device first seen inside a zone alerts: there is no "initial state" grace
  period. Alerts do not repeat while it stays inside; `ALERT_MODE=every_report`
  alerts on every report instead, throttled per `(device, zone)`.
* Only entry is reported. Departures update state but are never published, and
  there are no dwell-time alerts.
* Zones have no active flag — every zone of every user is evaluated.
* The `every_report` cooldown lives in worker memory, which assumes the single
  worker instance; `max(radius_m)` is read per batch instead of being cached.
* The positions stream is capped at 200 000 entries — only ~50 s of load at 4000
  positions/s. The worker keeps up easily, but a longer outage would lose
  entries to trimming.
* History is write-only: the table and index are built for `(device_id, time
  range)` replay, but no endpoint exposes it.
* Notifications are deleted with their zone (`ON DELETE CASCADE`). No rate
  limiting, and `/stats` is unauthenticated. The UI draws at most 3000 markers.

## Notes for production

* Real authentication, per-user device ownership, credentials on the ingest
  socket. Run containers as a non-root user, keep secrets out of `env_file`.
* The worker is the single instance. `XREADGROUP` already supports several
  consumers per group and the per-device diff is shard-safe; what has to move
  first is the cooldown, into Redis with `HEXPIRE`.
* For hundreds of thousands of zones the max-radius prefilter stops being
  enough: store a precomputed buffer polygon per zone and index it, or bucket
  zones by H3 cell. Zone geometry is almost static and belongs in a worker-side
  cache with an invalidation channel.
* Map payloads are 456 KiB per unfiltered client per second — send deltas in a
  binary encoding and make the viewport filter mandatory.
* Redis needs persistence tuning and Sentinel/Cluster, with the stream on its
  own instance. History needs scheduled partition rollover and retention
  (`pg_partman`), compression, and ideally its own database.
* Prometheus instead of `/stats`, with alerts on `dropped`, `flush_failures`,
  consumer-group lag and a non-empty DEFAULT history partition. Traces across
  ingest → worker → push. `LOG_LEVEL=WARNING` for load runs: uvicorn logs every
  WebSocket connection at INFO, which is 20 000 lines for a 10k-device run.
* CI running the suite, `alembic check` for model/migration drift, and both
  image builds.
