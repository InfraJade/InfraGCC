"""Maintenance muting (DECISIONS.md D16).

A server is muted while a maintenance window covering it (by server, rack or site) is active, and while its
status is `maintenance`. Collector alerts are muted by site-wide windows at the collector's site.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import MaintenanceScope, ServerStatus
from app.models import MaintenanceWindow, Server


async def _active_windows(session: AsyncSession, now: datetime) -> list[MaintenanceWindow]:
    rows = await session.execute(
        select(MaintenanceWindow).where(MaintenanceWindow.starts_at <= now, MaintenanceWindow.ends_at > now)
    )
    return list(rows.scalars())


async def muted_server_ids(
    session: AsyncSession, now: datetime, server_ids: list[int] | None = None
) -> set[int]:
    windows = await _active_windows(session, now)
    server_scope = {w.server_id for w in windows if w.scope == MaintenanceScope.SERVER.value}
    rack_scope = {w.rack_id for w in windows if w.scope == MaintenanceScope.RACK.value}
    site_scope = {w.site_id for w in windows if w.scope == MaintenanceScope.SITE.value}
    conditions = [Server.status == ServerStatus.MAINTENANCE.value]
    if server_scope:
        conditions.append(Server.id.in_(server_scope))
    if rack_scope:
        conditions.append(Server.rack_id.in_(rack_scope))
    if site_scope:
        conditions.append(Server.site_id.in_(site_scope))
    query = select(Server.id).where(or_(*conditions))
    if server_ids is not None:
        query = query.where(Server.id.in_(server_ids))
    return set((await session.execute(query)).scalars())


async def muted_site_ids(session: AsyncSession, now: datetime) -> set[int]:
    return {
        w.site_id
        for w in await _active_windows(session, now)
        if w.scope == MaintenanceScope.SITE.value and w.site_id is not None
    }
