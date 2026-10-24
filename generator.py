#!/usr/bin/env python

import asyncio
import math
import random
import resource
import signal
import time
from dataclasses import dataclass

import msgspec
import websockets

URL = "ws://localhost:8000/ws/devices"

DEVICES = 10_000

MIN_PERIOD_SECONDS = 1.0
MAX_PERIOD_SECONDS = 5.0
STEP_METERS = 20000

MIN_LAT = -85.0
MAX_LAT = 85.0
MIN_LON = -180.0
MAX_LON = 180.0

RAMP_UP_SECONDS = 20.0

DURATION_SECONDS = 0.0
REPORT_INTERVAL_SECONDS = 2.0
SEED = 42

METERS_PER_DEGREE = 111_320.0

_encode = msgspec.json.Encoder().encode


@dataclass(slots=True)
class Stats:
    sent: int = 0
    live: int = 0
    connects: int = 0
    failures: int = 0
    last_error: str = ""


def raise_fd_limit(needed: int) -> None:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    wanted = needed + 256
    if soft < wanted:
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(wanted, hard), hard))
        soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    if soft < wanted:
        print(
            f"warning: only {soft} file descriptors available for {needed} "
            f"devices; raise the hard limit or lower DEVICES",
            flush=True,
        )


def start_position() -> tuple[float, float]:
    return random.uniform(MIN_LAT, MAX_LAT), random.uniform(MIN_LON, MAX_LON)


def shift(lat: float, lon: float) -> tuple[float, float]:
    lat += random.uniform(-STEP_METERS, STEP_METERS) / METERS_PER_DEGREE
    lon += random.uniform(-STEP_METERS, STEP_METERS) / (
        METERS_PER_DEGREE * math.cos(math.radians(lat))
    )
    return max(-85.0, min(85.0, lat)), (lon + 180.0) % 360.0 - 180.0


async def _sleep_or_stop(stop: asyncio.Event, delay: float) -> bool:
    if delay <= 0.0:
        return stop.is_set()
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay)
    except TimeoutError:
        return False
    return True


async def device(device_id: int, stats: Stats, stop: asyncio.Event) -> None:
    lat, lon = start_position()
    period = random.uniform(MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS)

    if await _sleep_or_stop(stop, random.uniform(0.0, RAMP_UP_SECONDS)):
        return

    attempt = 0
    while not stop.is_set():
        try:
            async with websockets.connect(
                URL, open_timeout=30, ping_interval=None
            ) as ws:
                attempt = 0
                stats.connects += 1
                stats.live += 1
                try:
                    while not stop.is_set():
                        lat, lon = shift(lat, lon)
                        await ws.send(
                            _encode(
                                {
                                    "device_id": device_id,
                                    "lat": round(lat, 6),
                                    "lon": round(lon, 6),
                                    "ts": time.time(),
                                }
                            )
                        )
                        stats.sent += 1
                        if await _sleep_or_stop(stop, period):
                            return
                finally:
                    stats.live -= 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stats.failures += 1
            stats.last_error = f"{type(exc).__name__}: {exc}"
            attempt += 1
            backoff = min(10.0, 0.5 * 2 ** (attempt - 1)) * (0.5 + random.random())
            if await _sleep_or_stop(stop, backoff):
                return


async def reporter(stats: Stats, stop: asyncio.Event) -> None:
    started = time.monotonic()
    previous = 0
    while not stop.is_set():
        if await _sleep_or_stop(stop, REPORT_INTERVAL_SECONDS):
            return
        sent = stats.sent
        rate = (sent - previous) / REPORT_INTERVAL_SECONDS
        previous = sent
        print(
            f"[{time.monotonic() - started:6.1f}s] "
            f"connections {stats.live:>6}/{DEVICES}  {rate:>8.0f} pos/s  "
            f"sent {sent:>9}  failures {stats.failures}"
            + (f"  last: {stats.last_error}" if stats.last_error else ""),
            flush=True,
        )


async def _stop_after(stop: asyncio.Event, delay: float) -> None:
    await _sleep_or_stop(stop, delay)
    stop.set()


def reports_per_second() -> float:
    if MAX_PERIOD_SECONDS == MIN_PERIOD_SECONDS:
        return 1.0 / MIN_PERIOD_SECONDS
    return math.log(MAX_PERIOD_SECONDS / MIN_PERIOD_SECONDS) / (
        MAX_PERIOD_SECONDS - MIN_PERIOD_SECONDS
    )


async def run() -> None:
    random.seed(SEED)
    raise_fd_limit(DEVICES)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    stats = Stats()
    print(
        f"{DEVICES} devices, one connection each, to {URL}\n"
        f"period {MIN_PERIOD_SECONDS}-{MAX_PERIOD_SECONDS}s, "
        f"step up to {STEP_METERS} m, ramp-up {RAMP_UP_SECONDS}s\n"
        f"start box lat [{MIN_LAT}, {MAX_LAT}] lon [{MIN_LON}, {MAX_LON}], "
        f"expected ~{DEVICES * reports_per_second():.0f} pos/s once fully ramped",
        flush=True,
    )

    started = time.monotonic()
    async with asyncio.TaskGroup() as tg:
        for device_id in range(1, DEVICES + 1):
            tg.create_task(device(device_id, stats, stop))
        tg.create_task(reporter(stats, stop))
        if DURATION_SECONDS > 0:
            tg.create_task(_stop_after(stop, DURATION_SECONDS))

    elapsed = time.monotonic() - started
    print(
        f"\nsent {stats.sent} positions over {elapsed:.1f}s "
        f"({stats.sent / max(elapsed, 1e-9):.0f} pos/s), "
        f"connects {stats.connects}, failures {stats.failures}"
        + (f", last error: {stats.last_error}" if stats.last_error else "")
    )


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
