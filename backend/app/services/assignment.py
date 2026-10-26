"""Which servers each collector polls, including HA takeover (DECISIONS.md D9).

`servers.collector_id` is the preferred collector. A server whose preferred collector is offline (no heartbeat
for `collector_offline_after_s`), disabled, or unset is shared among the live collectors of the server's site,
split deterministically by server id: live collectors are sorted by id and server *s* goes to
`live[s.id % len(live)]`. Every collector computes the same split, so no coordination is needed, and the
split reverses on its own once the preferred collector heartbeats again.

The requesting collector always counts as live (it is talking to us right now).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ServerStatus
from app.models import AppSetting, Collector, Server, Site

COLLECTOR_SETTINGS_KEY = "collector_settings"


@dataclass(frozen=True)
class Assigned:
    id: int
    bmc_host: str
    vendor: str | None
    status: str
    takeover: bool


@dataclass(frozen=True)
class Assignment:
    collector_id: int
    collector_name: str
    site_id: int
    site_code: str
    servers: list[Assigned]

    @property
    def server_ids(self) -> set[int]:
        return {s.id for s in self.servers}


def is_live(collector: Collector, now: datetime, offline_after_s: int) -> bool:
    if not collector.enabled or collector.last_heartbeat is None:
        return False
    return collector.last_heartbeat >= now - timedelta(seconds=offline_after_s)


async def compute_assignment(
    session: AsyncSession, collector: Collector, now: datetime, offline_after_s: int
) -> Assignment:
    site = await session.get(Site, collector.site_id)
    assert site is not None
    collectors = list(
        (await session.execute(select(Collector).where(Collector.site_id == collector.site_id))).scalars()
    )
    live_set = {c.id for c in collectors if is_live(c, now, offline_after_s)}
    if collector.enabled:
        live_set.add(collector.id)
    live_ids = sorted(live_set)
    all_collectors = {c.id: c for c in collectors}
    candidates = list(
        (
            await session.execute(
                select(Server)
                .where(
                    Server.status != ServerStatus.DECOMMISSIONED.value,
                    or_(Server.site_id == collector.site_id, Server.collector_id == collector.id),
                )
                .order_by(Server.id)
            )
        ).scalars()
    )
    # A preferred collector at another site (misconfiguration) still counts when it is live.
    foreign_ids = {
        s.collector_id
        for s in candidates
        if s.collector_id is not None and s.collector_id not in all_collectors
    }
    if foreign_ids:
        extra = await session.execute(select(Collector).where(Collector.id.in_(foreign_ids)))
        all_collectors.update({c.id: c for c in extra.scalars()})

    servers: list[Assigned] = []
    for server in candidates:
        preferred = all_collectors.get(server.collector_id) if server.collector_id is not None else None
        if server.collector_id == collector.id:
            if collector.enabled:
                servers.append(_assigned(server, takeover=False))
            continue
        if preferred is not None and (preferred.id in live_set or is_live(preferred, now, offline_after_s)):
            continue
        if server.site_id != collector.site_id or not live_ids:
            continue
        if live_ids[server.id % len(live_ids)] == collector.id:
            servers.append(_assigned(server, takeover=True))
    return Assignment(collector.id, collector.name, site.id, site.code, servers)


def _assigned(server: Server, *, takeover: bool) -> Assigned:
    return Assigned(server.id, server.bmc_host, server.vendor, server.status, takeover)


async def collector_settings(session: AsyncSession, defaults: dict[str, int]) -> dict[str, int]:
    """Collector settings with admin overrides from `app_settings['collector_settings']`."""
    row = await session.get(AppSetting, COLLECTOR_SETTINGS_KEY)
    merged = dict(defaults)
    if row is not None:
        for key, value in row.value.items():
            if key in merged and isinstance(value, int) and value > 0:
                merged[key] = value
    return merged


def config_version(assignment: Assignment, settings: dict[str, int]) -> str:
    """Opaque hash of everything in the config response."""
    doc = {
        "collector": [assignment.collector_id, assignment.collector_name, assignment.site_code],
        "settings": sorted(settings.items()),
        "servers": [[s.id, s.bmc_host, s.vendor, s.status, s.takeover] for s in assignment.servers],
    }
    return hashlib.sha256(json.dumps(doc, separators=(",", ":")).encode()).hexdigest()[:12]
