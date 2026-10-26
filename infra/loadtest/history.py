"""Synthetic 30-day history so the dashboard queries run against a full month of rollups.

The live load test only produces minutes of data, but the design target is about 30-day views. Before the
measurement starts, `ensure_history` checks how far back `readings` goes and, if it does not reach the
requested number of days, writes one sample per series every 5 minutes for every onboarded server from the
start of the range up to the oldest existing reading (so live data is never touched), using COPY, newest day
first. After each day it refreshes `readings_5m` and the hierarchical `readings_1h` over that day.

One sample per 5 minutes gives the same number of rollup rows per series as real 60-second data, which is
what the dashboard queries read. Part names follow D13 ("CPU1", "Fan 1", "PSU 1") so the series line up
with what the collector reports.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

STEP = timedelta(minutes=5)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
COLUMNS = ["time", "server_id", "metric_code", "component", "value", "status"]

Series = tuple[str, str]  # (metric code, component)

_HANDFUL: list[Series] = [
    ("inlet_temp_c", ""),
    ("exhaust_temp_c", ""),
    ("power_w", ""),
    ("cpu_temp_c", "CPU1"),
    ("cpu_temp_c", "CPU2"),
]
_DASHBOARD: list[Series] = [*_HANDFUL, *[("fan_rpm", f"Fan {i}") for i in range(1, 7)]]
_FULL: list[Series] = [
    *_DASHBOARD,
    *[("dimm_temp_c", f"DIMM A{i}") for i in range(1, 5)],
    ("psu_input_v", "PSU 1"),
    ("psu_input_v", "PSU 2"),
    ("system_health", ""),
    ("power_state", ""),
    ("bmc_reachable", ""),
    ("psu_health", "PSU 1"),
    ("psu_health", "PSU 2"),
    *[("fan_health", f"Fan {i}") for i in range(1, 7)],
]

# handful: the series the brief asks for; dashboard: what the dashboard queries read, with real part
# counts; full: about half of a real server's series (adds DIMM temperatures, PSU voltage and state series),
# so metric-filtered scans read a realistic share of other metrics' rows.
PROFILES: dict[str, list[Series]] = {"handful": _HANDFUL, "dashboard": _DASHBOARD, "full": _FULL}

STATE_METRICS = {"system_health", "power_state", "bmc_reachable", "psu_health", "fan_health"}


def floor_step(t: datetime, step: timedelta = STEP) -> datetime:
    epoch = t.timestamp()
    s = step.total_seconds()
    return datetime.fromtimestamp(epoch - epoch % s, tz=UTC)


@dataclass(frozen=True)
class HistoryPlan:
    start: datetime
    end: datetime  # exclusive
    existing_from: datetime | None

    @property
    def needed(self) -> bool:
        return self.end > self.start

    @property
    def days(self) -> float:
        return max(0.0, (self.end - self.start) / DAY)


def plan_history(now: datetime, days: int, earliest: datetime | None) -> HistoryPlan:
    """Backfill [now - days, earliest) on 5-minute boundaries; nothing if data already reaches back."""
    start = floor_step(now - timedelta(days=days))
    end = floor_step(earliest) if earliest is not None else floor_step(now)
    # Data that starts within one step of the range start counts as covering it.
    if earliest is not None and earliest <= start + STEP:
        end = start
    return HistoryPlan(start=start, end=max(start, end), existing_from=earliest)


def synth_value(metric: str, server_id: int, component: str, t: datetime, rng: random.Random) -> float:
    """A plausible, deterministic-ish value: daily cycle + per-server offset + noise."""
    day_phase = 2 * math.pi * ((t.timestamp() % 86400) / 86400)
    load = 0.5 + 0.3 * math.sin(day_phase - math.pi / 2) + rng.uniform(-0.05, 0.05)
    offset = (server_id % 7) * 0.4
    part = int(component[-1]) if component[-1:].isdigit() else 0
    match metric:
        case "inlet_temp_c":
            return round(20.5 + offset + 2.0 * math.sin(day_phase) + rng.gauss(0, 0.3), 1)
        case "exhaust_temp_c":
            return round(33.0 + offset + 12.0 * load + rng.gauss(0, 0.5), 1)
        case "power_w":
            return round(260.0 + 30.0 * (server_id % 3) + 220.0 * load + rng.gauss(0, 8), 0)
        case "cpu_temp_c":
            return round(42.0 + 2.0 * part + 25.0 * load + rng.gauss(0, 1.0), 1)
        case "dimm_temp_c":
            return round(34.0 + 0.5 * part + 8.0 * load + rng.gauss(0, 0.5), 1)
        case "fan_rpm":
            return round(5200.0 + 120.0 * part + 4500.0 * load + rng.gauss(0, 80), 0)
        case "psu_input_v":
            return round(230.0 + rng.gauss(0, 1.5), 1)
        case "power_state" | "bmc_reachable":
            return 1.0
        case _:
            return 0.0  # health states: OK


def _status(metric: str) -> str | None:
    if metric == "power_state":
        return "On"
    if metric == "bmc_reachable":
        return "Reachable"
    return "OK"


Record = tuple[datetime, int, int, str, float, str | None]


def day_records(
    servers: list[int],
    series: list[tuple[int, str, str]],
    start: datetime,
    end: datetime,
    seed: int,
) -> Iterator[Record]:
    """Rows for [start, end): (time, server_id, metric_code, component, value, status)."""
    rng = random.Random(seed)
    t = start
    while t < end:
        for server_id in servers:
            for metric_id, code, component in series:
                yield (
                    t,
                    server_id,
                    metric_id,
                    component,
                    synth_value(code, server_id, component, t, rng),
                    _status(code),
                )
        t += STEP


async def _earliest_reading(conn: asyncpg.Connection[Any]) -> datetime | None:
    value = await conn.fetchval("SELECT min(time) FROM readings")
    return value if isinstance(value, datetime) else None


async def _copy(conn: asyncpg.Connection[Any], records: list[Record], fast: bool) -> None:
    """COPY one day of rows.

    The fast path (superuser only) skips the per-row FK checks, which dominate COPY time on a busy dev
    database (~0.5 ms per row), by setting session_replication_role = replica for the bulk of the rows.
    That also skips TimescaleDB's continuous-aggregate invalidation trigger, so the first and last row of
    the day go in afterwards, in the same transaction, with triggers on: the trigger logs the [min, max]
    time range a transaction touched, so the whole day is invalidated and the refresh re-materializes it.
    Row ids come from the database itself, so skipping the FK checks cannot admit bad references.
    """
    if not fast or len(records) <= 2:
        await conn.copy_records_to_table("readings", records=records, columns=COLUMNS)
        return
    async with conn.transaction():
        await conn.execute("SET LOCAL session_replication_role = replica")
        await conn.copy_records_to_table("readings", records=records[1:-1], columns=COLUMNS)
        await conn.execute("SET LOCAL session_replication_role = origin")
        await conn.copy_records_to_table("readings", records=[records[0], records[-1]], columns=COLUMNS)


async def _refresh(conn: asyncpg.Connection[Any], view: str, start: datetime, end: datetime) -> None:
    # CALL cannot take bind parameters through every protocol path; the values are our own timestamps.
    await conn.execute(
        f"CALL refresh_continuous_aggregate('{view}', '{start.isoformat()}'::timestamptz, "
        f"'{end.isoformat()}'::timestamptz)"
    )


async def ensure_history(
    conn: asyncpg.Connection[Any],
    *,
    days: int,
    profile: str,
    log: Callable[[str], None],
    allow_fast: bool = True,
) -> dict[str, Any]:
    """Make sure `days` of readings and rollups exist. Returns what was done, for the report."""
    now = await conn.fetchval("SELECT now()")
    assert isinstance(now, datetime)
    plan = plan_history(now, days, await _earliest_reading(conn))
    summary: dict[str, Any] = {
        "days": days,
        "profile": profile,
        "range_start": plan.start.isoformat(timespec="seconds"),
        "existing_from": plan.existing_from.isoformat(timespec="seconds") if plan.existing_from else None,
    }
    if not plan.needed:
        log(f"history: readings already reach back {days} days; no backfill")
        summary["backfilled_rows"] = 0
        return summary

    metric_ids = {code: mid for mid, code in await conn.fetch("SELECT id, code FROM metric_definitions")}
    series = [(metric_ids[code], code, comp) for code, comp in PROFILES[profile]]
    servers = [
        sid
        for (sid,) in await conn.fetch("SELECT id FROM servers WHERE status <> 'decommissioned' ORDER BY id")
    ]
    if not servers:
        raise RuntimeError("no onboarded servers: run `python -m app.seed loadtest --servers N` first")
    log(
        f"history: backfilling {plan.days:.1f} days x {len(servers)} servers x {len(series)} series "
        f"({plan.start:%Y-%m-%d %H:%M} .. {plan.end:%Y-%m-%d %H:%M} UTC)"
    )

    fast = allow_fast and bool(
        await conn.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    )
    log("history: fast COPY path (superuser, FK checks skipped)" if fast else "history: standard COPY path")
    # Rollup refreshes group millions of rows; the dev image's tuned work_mem is a few MB.
    await conn.execute("SET work_mem = '256MB'")

    rows = 0
    copy_s = 0.0
    refresh_s = 0.0
    # Newest day first: an interrupted run leaves [x, end) filled, and the next run plans [start, x).
    day_end = plan.end
    while day_end > plan.start:
        day_start = max(day_end - DAY, plan.start)
        t0 = time.perf_counter()
        records = list(day_records(servers, series, day_start, day_end, seed=int(day_start.timestamp())))
        await _copy(conn, records, fast)
        t1 = time.perf_counter()
        await _refresh(conn, "readings_5m", day_start, day_end)
        # readings_1h is built from readings_5m: refresh every whole hour this day touches.
        await _refresh(
            conn,
            "readings_1h",
            floor_step(day_start, HOUR),
            floor_step(day_end - timedelta(microseconds=1), HOUR) + HOUR,
        )
        t2 = time.perf_counter()
        copy_s += t1 - t0
        refresh_s += t2 - t1
        rows += len(records)
        log(
            f"history: {day_start:%Y-%m-%d %H:%M} {len(records):,} rows (total {rows:,}); "
            f"COPY {t1 - t0:.0f} s, refresh {t2 - t1:.0f} s"
        )
        day_end = day_start

    log(f"history: done, {rows:,} rows; COPY {copy_s:.0f} s, rollup refresh {refresh_s:.0f} s")
    summary.update(
        backfilled_rows=rows,
        fast_path=fast,
        servers=len(servers),
        series_per_server=len(series),
        copy_s=round(copy_s, 1),
        refresh_s=round(refresh_s, 1),
    )
    return summary
