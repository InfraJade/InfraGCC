"""Missing-data rules: servers that stop reporting and collectors that stop heartbeating.

- Server: no data for `polls` sensor intervals (60 s each; or the rule duration when longer) → alert.
  Not opened while no collector at the server's site is live — the collector alert already says why.
- Collector: no heartbeat for `after_s` → alert at the collector's site.
Both resolve as soon as data flows again. A server or collector that never reported counts from when it
was created.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertState, RuleType, ServerStatus
from app.models import Alert, Collector, Server
from app.services.alerts.effects import Effects
from app.services.alerts.maintenance import muted_server_ids, muted_site_ids
from app.services.alerts.rules import LoadedRule, load_rules
from app.services.alerts.store import AlertStore, Firing, collector_key, nodata_key
from app.services.assignment import is_live

SENSOR_INTERVAL_S = 60


async def _active_by_key(session: AsyncSession, rule: LoadedRule) -> dict[str, Alert]:
    rows = await session.execute(
        select(Alert).where(Alert.rule_id == rule.id, Alert.state != AlertState.RESOLVED.value)
    )
    return {a.dedupe_key: a for a in rows.scalars()}


def _ago(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} h"
    if seconds >= 120:
        return f"{seconds / 60:.0f} min"
    return f"{seconds:.0f} s"


async def check_servers(
    session: AsyncSession, now: datetime, effects: Effects, offline_after_s: int
) -> tuple[int, int]:
    """Returns (opened or updated, resolved)."""
    fired = resolved = 0
    for rule in await load_rules(session, RuleType.MISSING_DATA):
        if rule.condition.get("target", "server") != "server":
            continue
        after_s = max(rule.cond_int("polls", 3) * SENSOR_INTERVAL_S, rule.rule.duration_s)
        active = await _active_by_key(session, rule)
        servers = list(
            (
                await session.execute(
                    select(Server).where(Server.status != ServerStatus.DECOMMISSIONED.value)
                )
            ).scalars()
        )
        collectors = list((await session.execute(select(Collector))).scalars())
        live_sites = {c.site_id for c in collectors if is_live(c, now, offline_after_s)}
        muted = await muted_server_ids(session, now)
        store = AlertStore(session, now, effects)
        cutoff = now - timedelta(seconds=after_s)
        seen_keys: set[str] = set()
        for server in servers:
            key = nodata_key(server.id)
            seen_keys.add(key)
            reference = server.last_seen_at or server.created_at
            existing = active.get(key)
            if reference < cutoff:
                if existing is None and server.site_id not in live_sites:
                    continue
                silent = (now - reference).total_seconds()
                await store.fire(
                    Firing(
                        rule=rule.rule,
                        key=key,
                        severity=rule.severity,
                        title=f"{rule.rule.name}: {server.display_name}",
                        message=(
                            f"No data from {server.display_name} for {_ago(silent)}"
                            + (" (never reported)." if server.last_seen_at is None else ".")
                        ),
                        site_id=server.site_id,
                        server_id=server.id,
                        muted=server.id in muted,
                    ),
                    existing,
                )
                fired += 1
            elif existing is not None:
                await store.resolve(existing, "Data is flowing again.")
                resolved += 1
        for key, alert in active.items():
            if key not in seen_keys:  # decommissioned or deleted
                await store.resolve(alert, "Server is no longer monitored.")
                resolved += 1
    return fired, resolved


async def check_collectors(session: AsyncSession, now: datetime, effects: Effects) -> tuple[int, int]:
    fired = resolved = 0
    for rule in await load_rules(session, RuleType.MISSING_DATA):
        if rule.condition.get("target") != "collector":
            continue
        after_s = rule.cond_int("after_s", 0) or rule.rule.duration_s or 120
        active = await _active_by_key(session, rule)
        muted_sites = await muted_site_ids(session, now)
        store = AlertStore(session, now, effects)
        cutoff = now - timedelta(seconds=after_s)
        collectors = list((await session.execute(select(Collector))).scalars())
        seen_keys: set[str] = set()
        for collector in collectors:
            key = collector_key(collector.id)
            existing = active.get(key)
            if not collector.enabled:
                continue
            seen_keys.add(key)
            reference = collector.last_heartbeat or collector.created_at
            if reference < cutoff:
                silent = (now - reference).total_seconds()
                await store.fire(
                    Firing(
                        rule=rule.rule,
                        key=key,
                        severity=rule.severity,
                        title=f"{rule.rule.name}: {collector.name}",
                        message=(
                            f"Collector {collector.name} has not sent a heartbeat for {_ago(silent)}"
                            + (" (never connected)." if collector.last_heartbeat is None else ".")
                        ),
                        site_id=collector.site_id,
                        collector_id=collector.id,
                        muted=collector.site_id in muted_sites,
                    ),
                    existing,
                )
                fired += 1
            elif existing is not None:
                await store.resolve(existing, "Heartbeats are arriving again.")
                resolved += 1
        for key, alert in active.items():
            if key not in seen_keys:
                await store.resolve(alert, "Collector disabled or removed.")
                resolved += 1
    return fired, resolved
