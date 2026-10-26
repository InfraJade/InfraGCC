"""Dev-only history backfill, so charts and Superset have days of data on first start.

Runs once, from the scheduler at startup, when `DEV_BACKFILL_ENABLED` is true, `APP_ENV=dev` and `readings`
holds nothing older than a day. It writes `DEV_BACKFILL_DAYS` of 5-minute samples for the simulated servers'
main gauges (inlet / exhaust / CPU temperatures, fan speed, power draw, PSU input voltage) with `COPY`, using
the part names the collector reports (D13) so live data continues the same series, then refreshes both
rollups over the backfilled range. A transaction-level advisory lock plus an `app_settings` marker keep it to
one run even with several scheduler processes.

The simulated fleet layout mirrors `mockups/src/gcc_redfish_sim/catalog.py`: BMC *i* listens on
`SEED_SIM_BASE_PORT + i` and runs `FLEET[(i - 1) % 6]`.
"""

from __future__ import annotations

import logging
import math
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings
from app.models import AppSetting, MetricDefinition, Server

log = logging.getLogger("gcc.backfill")

SETTING_KEY = "dev_backfill"
LOCK_KEY = 0x47434302  # "GCC" + 2
STEP = timedelta(minutes=5)
_PORT = re.compile(r":(\d+)/?$")


@dataclass(frozen=True)
class Profile:
    fans: int
    fan_metric: str  # fan_rpm or fan_pct
    fan_base: float  # RPM or % at idle
    fan_span: float  # extra RPM or % at full load
    idle_w: float
    peak_w: float
    capacity_w: float
    volts: float


# FLEET order: dell-r750, hpe-dl380-gen10, lenovo-sr650-v3, dell-r650, hpe-dl360-gen10, lenovo-sr630-v3
FLEET_PROFILES = [
    Profile(6, "fan_rpm", 6800, 5000, 280, 720, 1400, 231),
    Profile(6, "fan_pct", 32, 30, 260, 680, 1400, 230),
    Profile(6, "fan_rpm", 7300, 6000, 270, 700, 1100, 229),
    Profile(8, "fan_rpm", 10000, 8000, 190, 470, 800, 231),
    Profile(7, "fan_pct", 34, 32, 180, 450, 800, 230),
    Profile(8, "fan_rpm", 9800, 9000, 185, 460, 750, 229),
]


@dataclass
class BackfillResult:
    ran: bool
    reason: str
    servers: int = 0
    rows: int = 0
    seconds: float = 0.0


def sim_index(bmc_host: str, base_port: int) -> int | None:
    match = _PORT.search(bmc_host)
    if match is None:
        return None
    index = int(match.group(1)) - base_port
    return index if 1 <= index <= 10_000 else None


def generate_rows(
    server_id: int, index: int, metric_ids: dict[str, int], start: datetime, end: datetime, seed: int = 0
) -> list[tuple[datetime, int, int, str, float, str | None]]:
    """Plausible, correlated history for one server: load drives power, CPU temperature and fan speed."""
    prof = FLEET_PROFILES[(index - 1) % len(FLEET_PROFILES)]
    rng = random.Random(seed * 100_003 + server_id)
    phase = rng.uniform(-1.0, 1.0)
    base_load = rng.uniform(0.25, 0.55)
    inlet_base = rng.uniform(21.0, 24.0)
    rows: list[tuple[datetime, int, int, str, float, str | None]] = []
    t = start
    while t < end:
        hour = t.hour + t.minute / 60 + 5.5  # local time in India drives the business-hours load
        day = 0.5 + 0.5 * math.sin((hour - 9 + phase) / 24 * 2 * math.pi)
        load = min(1.0, max(0.05, base_load + 0.35 * day + rng.gauss(0, 0.04)))
        inlet = inlet_base + 1.6 * math.sin((hour - 14) / 24 * 2 * math.pi) + rng.gauss(0, 0.15)
        power = prof.idle_w + (prof.peak_w - prof.idle_w) * load + rng.gauss(0, 6)
        values: list[tuple[str, str, float]] = [
            ("inlet_temp_c", "", round(inlet, 1)),
            ("exhaust_temp_c", "", round(inlet + 8 + 14 * load + rng.gauss(0, 0.3), 1)),
            ("power_w", "", round(power)),
        ]
        for cpu in (1, 2):
            values.append(("cpu_temp_c", f"CPU{cpu}", round(inlet + 22 + 30 * load + rng.gauss(0, 0.8), 1)))
        for fan in range(1, prof.fans + 1):
            speed = prof.fan_base + prof.fan_span * load * 0.8 + rng.gauss(0, prof.fan_span * 0.01)
            values.append(
                (prof.fan_metric, f"Fan {fan}", round(speed, 1 if prof.fan_metric == "fan_pct" else 0))
            )
        for psu in (1, 2):
            values.append(("psu_input_v", f"PSU {psu}", round(prof.volts + rng.gauss(0, 0.8), 1)))
        for code, component, value in values:
            rows.append((t, server_id, metric_ids[code], component, float(value), "OK"))
        t += STEP
    return rows


async def _should_run(session: AsyncSession, settings: Settings) -> str | None:
    """None when the backfill should run, else the reason it should not."""
    if settings.app_env != "dev":
        return f"APP_ENV is {settings.app_env}"
    if not settings.dev_backfill_enabled:
        return "DEV_BACKFILL_ENABLED is false"
    if await session.get(AppSetting, SETTING_KEY) is not None:
        return "already done"
    old = (
        await session.execute(
            text("SELECT EXISTS (SELECT 1 FROM readings WHERE time < now() - interval '1 day')")
        )
    ).scalar_one()
    if old:
        return "readings already hold history"
    return None


async def run_backfill(
    engine: AsyncEngine, settings: Settings, *, owner_engine: AsyncEngine | None = None, seed: int = 0
) -> BackfillResult:
    started = time.monotonic()
    base_port = int(os.environ.get("SEED_SIM_BASE_PORT", "20000"))
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    end -= timedelta(minutes=end.minute % 5)
    start = end - timedelta(days=settings.dev_backfill_days)
    writer = owner_engine or engine
    async with AsyncSession(writer, expire_on_commit=False) as session, session.begin():
        locked = (
            await session.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
        ).scalar_one()
        if not locked:
            return BackfillResult(False, "another process is running it")
        reason = await _should_run(session, settings)
        if reason is not None:
            log.info("dev backfill skipped: %s", reason)
            return BackfillResult(False, reason)
        metric_ids = {m.code: m.id for m in (await session.execute(select(MetricDefinition))).scalars()}
        servers = [
            (s.id, idx)
            for s in (await session.execute(select(Server).order_by(Server.id))).scalars()
            if (idx := sim_index(s.bmc_host, base_port)) is not None
        ]
        if owner_engine is not None:
            # Row triggers (FK checks, rollup invalidation) make COPY into `readings` ~25x slower; the ids
            # come straight from `servers` / `metric_definitions` and the rollups are refreshed below, so the
            # owner skips them for this one-off load when it may (superuser in dev).
            try:
                async with session.begin_nested():
                    await session.execute(text("SET LOCAL session_replication_role = replica"))
            except Exception:
                log.info("dev backfill: cannot skip row triggers; loading with them")
        conn = await session.connection()
        raw = await conn.get_raw_connection()
        pg: Any = raw.driver_connection
        total = 0
        for server_id, index in servers:
            rows = generate_rows(server_id, index, metric_ids, start, end, seed)
            await pg.copy_records_to_table(
                "readings",
                records=rows,
                columns=["time", "server_id", "metric_code", "component", "value", "status"],
            )
            total += len(rows)
        if servers:
            # With row triggers skipped, TimescaleDB never logged the new rows as changed, so a refresh would
            # treat the range as up to date once the rollups' watermark is past it. Touching the first and
            # last samples with triggers on records an invalidation over the whole loaded range.
            await session.execute(text("SET LOCAL session_replication_role = origin"))
            await session.execute(
                text("UPDATE readings SET value = value WHERE server_id = :sid AND time IN (:start, :last)"),
                {"sid": servers[0][0], "start": start, "last": end - STEP},
            )
        session.add(
            AppSetting(
                key=SETTING_KEY,
                value={
                    "done_at": datetime.now(UTC).isoformat(),
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                    "servers": len(servers),
                    "rows": total,
                },
            )
        )
    try:
        await refresh_rollups(writer, start, end)
    except Exception:
        # Refreshing needs the rollups' owner; without MIGRATION_DATABASE_URL only the policies' 2-3 days
        # get materialized.
        log.warning("dev backfill could not refresh the rollups (set MIGRATION_DATABASE_URL)", exc_info=True)
    result = BackfillResult(True, "done", len(servers), total, time.monotonic() - started)
    log.info("dev backfill wrote %d rows for %d servers in %.1f s", total, len(servers), result.seconds)
    return result


async def refresh_rollups(engine: AsyncEngine, start: datetime, end: datetime) -> None:
    """Materialize both rollups over the range (CALL cannot run inside a transaction block)."""
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for view in ("readings_5m", "readings_1h"):
            await conn.execute(
                text(
                    f"CALL refresh_continuous_aggregate('{view}', "
                    "CAST(:start AS timestamptz), CAST(:end AS timestamptz))"
                ),
                {"start": start - timedelta(hours=1), "end": end},
            )
