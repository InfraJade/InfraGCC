"""Persist one collector batch in a single transaction.

Readings go in with `COPY` (asyncpg `copy_records_to_table`); everything else is set-based SQL over `unnest`
arrays, so a batch costs a fixed number of round trips whatever its size. Every statement here is allowed
for the least-privilege `gcc_ingest` role (migrations 0005 and 0006).

Replays are safe: latest values and health only move forward in time, events are unique per server and
entry id, and the batch id itself is deduplicated in Redis before we get here.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Health
from app.core.live import HealthChange, LiveReading
from app.ingest.catalog import MetricCatalog
from app.ingest.health import derive_health
from app.ingest.schemas import ServerPayload

log = logging.getLogger("gcc.ingest.writer")

READING_COLUMNS = ["time", "server_id", "metric_code", "component", "value", "status"]

Key = tuple[int, int, str]  # server_id, metric_code, component


@dataclass
class ServerResult:
    server_id: int
    site_id: int
    readings: list[LiveReading] = field(default_factory=list)
    health_changes: list[HealthChange] = field(default_factory=list)
    server_health: str = Health.UNKNOWN.value


@dataclass
class WriteResult:
    readings: int = 0
    events: int = 0
    events_new: int = 0
    skipped_readings: int = 0
    servers: dict[int, ServerResult] = field(default_factory=dict)


async def _driver(session: AsyncSession) -> Any:
    """The asyncpg connection behind the session, inside the session's open transaction."""
    # Run one statement through SQLAlchemy first so its asyncpg adapter has started the transaction.
    await session.execute(text("SELECT 1"))
    conn = await session.connection()
    raw = await conn.get_raw_connection()
    return raw.driver_connection


async def write_batch(
    session: AsyncSession,
    payloads: list[ServerPayload],
    site_by_server: dict[int, int],
    catalog: MetricCatalog,
    now: datetime,
) -> WriteResult:
    pg = await _driver(session)
    result = WriteResult(
        servers={sid: ServerResult(sid, site) for sid, site in site_by_server.items()},
    )
    server_ids = sorted(site_by_server)

    # ---------------------------------------------------------------- readings (COPY) and latest values
    records: list[tuple[datetime, int, int, str, float | None, str | None]] = []
    latest: dict[Key, tuple[datetime, float | None, str | None]] = {}
    state_latest: dict[Key, tuple[datetime, float | None, str | None, str]] = {}
    for payload in payloads:
        for r in payload.readings or ():
            metric = catalog.get(r.metric)
            if metric is None or metric.type not in ("gauge", "state"):
                result.skipped_readings += 1
                continue
            records.append((r.time, payload.server_id, metric.id, r.component, r.value, r.status))
            key = (payload.server_id, metric.id, r.component)
            prev = latest.get(key)
            if prev is None or r.time >= prev[0]:
                latest[key] = (r.time, r.value, r.status)
                if metric.type == "state":
                    state_latest[key] = (r.time, r.value, r.status, metric.code)
    if result.skipped_readings:
        log.warning("skipped %d readings with unknown or non-reading metric codes", result.skipped_readings)
    if records:
        await pg.copy_records_to_table("readings", records=records, columns=READING_COLUMNS)
        result.readings = len(records)
    if latest:
        keys = list(latest)
        await pg.execute(
            """
            INSERT INTO latest_readings (server_id, metric_code, component, value, status, time)
            SELECT * FROM unnest($1::int[], $2::smallint[], $3::text[], $4::float8[], $5::text[],
                                 $6::timestamptz[])
            ON CONFLICT (server_id, metric_code, component) DO UPDATE
               SET value = EXCLUDED.value, status = EXCLUDED.status, time = EXCLUDED.time
             WHERE latest_readings.time <= EXCLUDED.time
            """,
            [k[0] for k in keys],
            [k[1] for k in keys],
            [k[2] for k in keys],
            [latest[k][1] for k in keys],
            [latest[k][2] for k in keys],
            [latest[k][0] for k in keys],
        )
        for (sid, mid, comp), (t, value, status) in latest.items():
            result.servers[sid].readings.append(
                LiveReading(
                    metric=catalog.by_id[mid].code, component=comp, value=value, status=status, time=t
                )
            )

    # ---------------------------------------------------------------- inventory (before health: D19)
    for payload in payloads:
        if payload.components is not None:
            await _write_components(pg, payload)
        if payload.firmware is not None:
            await _write_firmware(pg, payload)

    # ---------------------------------------------------------------- health
    if state_latest:
        await _write_health(pg, state_latest, server_ids, result)

    # ---------------------------------------------------------------- BMC limits
    limits: dict[Key, tuple[float | None, float | None, float | None, float | None]] = {}
    for payload in payloads:
        for lim in payload.bmc_limits or ():
            metric = catalog.get(lim.metric)
            if metric is None:
                continue
            limits[(payload.server_id, metric.id, lim.component)] = (
                lim.lower_critical,
                lim.lower_warning,
                lim.upper_warning,
                lim.upper_critical,
            )
    if limits:
        keys = list(limits)
        await pg.execute(
            """
            INSERT INTO bmc_thresholds (server_id, metric_code, component, lower_critical, lower_warning,
                                        upper_warning, upper_critical, updated_at)
            SELECT u.*, now() FROM unnest($1::int[], $2::smallint[], $3::text[], $4::float8[], $5::float8[],
                                          $6::float8[], $7::float8[]) AS u
            ON CONFLICT (server_id, metric_code, component) DO UPDATE
               SET lower_critical = EXCLUDED.lower_critical, lower_warning = EXCLUDED.lower_warning,
                   upper_warning = EXCLUDED.upper_warning, upper_critical = EXCLUDED.upper_critical,
                   updated_at = EXCLUDED.updated_at
            """,
            [k[0] for k in keys],
            [k[1] for k in keys],
            [k[2] for k in keys],
            *([limits[k][i] for k in keys] for i in range(4)),
        )

    # ---------------------------------------------------------------- events
    ev_rows = [(p.server_id, e) for p in payloads for e in (p.events or ())]
    if ev_rows:
        rows = await pg.fetch(
            """
            INSERT INTO events (server_id, time, severity, message, message_id, entry_id)
            SELECT * FROM unnest($1::int[], $2::timestamptz[], $3::text[], $4::text[], $5::text[], $6::text[])
            ON CONFLICT (server_id, entry_id) DO NOTHING
            RETURNING id
            """,
            [sid for sid, _ in ev_rows],
            [e.time for _, e in ev_rows],
            [e.severity for _, e in ev_rows],
            [e.message for _, e in ev_rows],
            [e.message_id for _, e in ev_rows],
            [e.entry_id for _, e in ev_rows],
        )
        result.events = len(ev_rows)
        result.events_new = len(rows)

    # ---------------------------------------------------------------- identity and last seen
    for payload in payloads:
        ident = payload.identity
        if ident is None:
            continue
        await pg.execute(
            """
            UPDATE servers SET
              vendor = COALESCE($2, vendor),
              model = COALESCE($3, model),
              serial = COALESCE($4, serial),
              bmc_model = COALESCE($5, bmc_model),
              bmc_mac = COALESCE($6, bmc_mac),
              system_path = COALESCE($7, system_path),
              host_ips = COALESCE($8::varchar[], host_ips),
              name = COALESCE(name, $9),
              discovered_at = COALESCE(discovered_at, $10),
              updated_at = now()
            WHERE id = $1
            """,
            payload.server_id,
            ident.vendor,
            ident.model,
            ident.serial,
            ident.bmc_model,
            ident.bmc_mac,
            ident.system_path,
            ident.host_ips,
            ident.hostname,
            payload.polled_at,
        )
    seen: dict[int, datetime] = {}
    for payload in payloads:
        if payload.server_id not in seen or payload.polled_at > seen[payload.server_id]:
            seen[payload.server_id] = payload.polled_at
    if seen:
        await pg.execute(
            """
            UPDATE servers s SET last_seen_at = GREATEST(COALESCE(s.last_seen_at, u.t), u.t)
            FROM unnest($1::int[], $2::timestamptz[]) AS u(id, t)
            WHERE s.id = u.id
            """,
            list(seen),
            list(seen.values()),
        )
    return result


async def _write_components(pg: Any, payload: ServerPayload) -> None:
    snapshot = {(c.type, c.name): c for c in payload.components or ()}
    items = list(snapshot.values())
    t = payload.polled_at
    if items:
        await pg.execute(
            """
            INSERT INTO components (server_id, type, name, model, manufacturer, serial, capacity,
                                    capacity_unit, firmware_version, location, expected_link_up, extra,
                                    first_seen_at, last_seen_at, removed_at)
            SELECT $1, u.type, u.name, u.model, u.manufacturer, u.serial, u.capacity, u.capacity_unit,
                   u.firmware_version, u.location, u.link_up, u.extra::jsonb, $2, $2, NULL
            FROM unnest($3::text[], $4::text[], $5::text[], $6::text[], $7::text[], $8::float8[], $9::text[],
                        $10::text[], $11::text[], $12::bool[], $13::text[])
                 AS u(type, name, model, manufacturer, serial, capacity, capacity_unit, firmware_version,
                      location, link_up, extra)
            ON CONFLICT (server_id, type, name) DO UPDATE SET
              model = EXCLUDED.model, manufacturer = EXCLUDED.manufacturer, serial = EXCLUDED.serial,
              capacity = EXCLUDED.capacity, capacity_unit = EXCLUDED.capacity_unit,
              firmware_version = EXCLUDED.firmware_version, location = EXCLUDED.location,
              extra = EXCLUDED.extra, last_seen_at = EXCLUDED.last_seen_at, removed_at = NULL,
              expected_link_up = COALESCE(components.expected_link_up, EXCLUDED.expected_link_up)
            """,
            payload.server_id,
            t,
            [c.type for c in items],
            [c.name for c in items],
            [c.model for c in items],
            [c.manufacturer for c in items],
            [c.serial for c in items],
            [c.capacity for c in items],
            [c.capacity_unit for c in items],
            [c.firmware_version for c in items],
            [c.location for c in items],
            # D19: only NICs carry an expected link state; it is fixed at first sighting.
            [c.link_up if c.type == "nic" else None for c in items],
            [json.dumps(c.extra) for c in items],
        )
    await pg.execute(
        """
        UPDATE components SET removed_at = $2
        WHERE server_id = $1 AND removed_at IS NULL
          AND NOT ((type, name) IN (SELECT * FROM unnest($3::text[], $4::text[])))
        """,
        payload.server_id,
        t,
        [k[0] for k in snapshot],
        [k[1] for k in snapshot],
    )


async def _write_firmware(pg: Any, payload: ServerPayload) -> None:
    snapshot = {f.component: f for f in payload.firmware or ()}
    items = list(snapshot.values())
    if items:
        await pg.execute(
            """
            INSERT INTO firmware_inventory (server_id, component, component_key, component_type, version,
                                            collected_at)
            SELECT $1, u.component, u.key, u.type, u.version, $2
            FROM unnest($3::text[], $4::text[], $5::text[], $6::text[]) AS u(component, key, type, version)
            ON CONFLICT (server_id, component) DO UPDATE SET
              component_key = EXCLUDED.component_key, component_type = EXCLUDED.component_type,
              version = EXCLUDED.version, collected_at = EXCLUDED.collected_at
            """,
            payload.server_id,
            payload.polled_at,
            [f.component for f in items],
            [f.component_key for f in items],
            [f.component_type for f in items],
            [f.version for f in items],
        )
    await pg.execute(
        "DELETE FROM firmware_inventory WHERE server_id = $1 AND NOT (component = ANY($2::text[]))",
        payload.server_id,
        list(snapshot),
    )


async def _write_health(
    pg: Any,
    state_latest: dict[Key, tuple[datetime, float | None, str | None, str]],
    server_ids: list[int],
    result: WriteResult,
) -> None:
    existing: dict[Key, tuple[str, datetime, datetime]] = {}
    worst: dict[int, dict[Key, Health]] = defaultdict(dict)
    for row in await pg.fetch(
        "SELECT server_id, metric_code, component, health, since, updated_at FROM health_status "
        "WHERE server_id = ANY($1::int[])",
        server_ids,
    ):
        key = (row["server_id"], row["metric_code"], row["component"])
        existing[key] = (row["health"], row["since"], row["updated_at"])
        worst[row["server_id"]][key] = Health(row["health"])
    expected: dict[tuple[int, str], bool | None] = {
        (row["server_id"], row["name"]): row["expected_link_up"]
        for row in await pg.fetch(
            "SELECT server_id, name, expected_link_up FROM components "
            "WHERE server_id = ANY($1::int[]) AND type = 'nic' AND removed_at IS NULL",
            server_ids,
        )
    }

    keys: list[Key] = []
    healths: list[str] = []
    states: list[str | None] = []
    times: list[datetime] = []
    for key, (t, value, status, code) in state_latest.items():
        prev = existing.get(key)
        if prev is not None and prev[2] > t:
            continue  # an older replay; the stored health is newer
        health = derive_health(code, value, status, expected_link_up=expected.get((key[0], key[2])))
        keys.append(key)
        healths.append(health.value)
        states.append(status)
        times.append(t)
        worst[key[0]][key] = health
        if prev is None or prev[0] != health.value:
            result.servers[key[0]].health_changes.append(
                HealthChange(metric=code, component=key[2], health=health.value, state=status, since=t)
            )
    if keys:
        await pg.execute(
            """
            INSERT INTO health_status (server_id, metric_code, component, health, state, since, updated_at)
            SELECT u.sid, u.mid, u.comp, u.health, u.state, u.t, u.t
            FROM unnest($1::int[], $2::smallint[], $3::text[], $4::text[], $5::text[], $6::timestamptz[])
                 AS u(sid, mid, comp, health, state, t)
            ON CONFLICT (server_id, metric_code, component) DO UPDATE SET
              since = CASE WHEN health_status.health = EXCLUDED.health THEN health_status.since
                           ELSE EXCLUDED.since END,
              health = EXCLUDED.health, state = EXCLUDED.state, updated_at = EXCLUDED.updated_at
            WHERE health_status.updated_at <= EXCLUDED.updated_at
            """,
            [k[0] for k in keys],
            [k[1] for k in keys],
            [k[2] for k in keys],
            healths,
            states,
            times,
        )
    for sid, per_key in worst.items():
        if sid in result.servers:
            result.servers[sid].server_health = Health.worst(list(per_key.values())).value
