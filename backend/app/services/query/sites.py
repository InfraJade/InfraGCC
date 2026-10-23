"""Site, room and rack summaries for the Global overview, Site view and Rack view."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertState, Health, ServerStatus, Severity
from app.core.security import Principal, not_found
from app.models import Alert, Collector, LatestReading, Rack, Room, Server, Site
from app.schemas.common import AlertCounts, CollectorRef, HealthCounts, ReadingValue, RoomRef, SiteRef
from app.schemas.inventory import (
    Freshness,
    OverviewOut,
    OverviewTotals,
    RackDetail,
    RackServer,
    RackSummary,
    RoomWithRacks,
    SiteDetail,
    SiteSummary,
)
from app.services.query.common import (
    STALE_AFTER,
    age_s,
    collector_is_online,
    collector_online_expr,
    display_name,
    health_from_rank,
    metrics_by_code,
    now_utc,
    server_rank,
    worst_health_subquery,
)

_NOT_DECOM = Server.status != ServerStatus.DECOMMISSIONED.value


def visible_sites_stmt(principal: Principal) -> Select[Site]:
    return select(Site).where(principal.site_filter(Site.id))


async def site_summaries(session: AsyncSession, sites: Sequence[Site]) -> list[SiteSummary]:
    """Counts, health, alerts, power and freshness for each of `sites` (already scope-checked)."""
    ids = [s.id for s in sites]
    out = {
        s.id: SiteSummary(
            id=s.id, code=s.code, name=s.name, city=s.city, country=s.country, timezone=s.timezone
        )
        for s in sites
    }
    if not ids:
        return []
    now = now_utc()
    cutoff = now - STALE_AFTER
    metrics = await metrics_by_code(session)
    power_id, inlet_id = metrics["power_w"].id, metrics["inlet_temp_c"].id

    rooms = await session.execute(
        select(Room.site_id, func.count()).where(Room.site_id.in_(ids)).group_by(Room.site_id)
    )
    for site_id, n in rooms.all():
        out[site_id].room_count = n
    racks = await session.execute(
        select(Room.site_id, func.count(Rack.id), func.sum(Rack.power_capacity_w))
        .join(Rack, Rack.room_id == Room.id)
        .where(Room.site_id.in_(ids))
        .group_by(Room.site_id)
    )
    for site_id, n, capacity in racks.all():
        out[site_id].rack_count = n
        out[site_id].rack_power_capacity_w = float(capacity) if capacity is not None else None

    wh = worst_health_subquery()
    rank = server_rank(wh)
    health_rows = await session.execute(
        select(Server.site_id, Server.status, rank, func.count())
        .outerjoin(wh, wh.c.server_id == Server.id)
        .where(Server.site_id.in_(ids), _NOT_DECOM)
        .group_by(Server.site_id, Server.status, rank)
    )
    for site_id, status, r, n in health_rows.all():
        summary = out[site_id]
        summary.server_count += n
        summary.health.add(health_from_rank(r), n)
        if status == ServerStatus.MAINTENANCE.value:
            summary.servers_in_maintenance += n

    alert_rows = await session.execute(
        select(Alert.site_id, Alert.state, Alert.severity, Alert.muted, func.count())
        .where(Alert.site_id.in_(ids), Alert.state != AlertState.RESOLVED.value)
        .group_by(Alert.site_id, Alert.state, Alert.severity, Alert.muted)
    )
    for alert_site, state, severity, muted, n in alert_rows.all():
        if alert_site is not None:
            _count_alert(out[alert_site].alerts, state, severity, muted, n)

    live = await session.execute(
        select(
            Server.site_id,
            func.sum(LatestReading.value).filter(LatestReading.metric_code == power_id),
            func.avg(LatestReading.value).filter(LatestReading.metric_code == inlet_id),
            func.max(LatestReading.value).filter(LatestReading.metric_code == inlet_id),
        )
        .join(Server, Server.id == LatestReading.server_id)
        .where(
            Server.site_id.in_(ids),
            _NOT_DECOM,
            LatestReading.component == "",
            LatestReading.metric_code.in_([power_id, inlet_id]),
            LatestReading.time >= cutoff,
        )
        .group_by(Server.site_id)
    )
    for site_id, power, inlet_avg, inlet_max in live.all():
        out[site_id].power_w = _round(power)
        out[site_id].inlet_avg_c = _round(inlet_avg)
        out[site_id].inlet_max_c = _round(inlet_max)

    newest = (
        select(LatestReading.server_id, func.max(LatestReading.time).label("t"))
        .group_by(LatestReading.server_id)
        .subquery("newest")
    )
    fresh = await session.execute(
        select(
            Server.site_id,
            func.max(newest.c.t),
            func.min(newest.c.t),
            func.count().filter(newest.c.t >= cutoff),
            func.count().filter(func.coalesce(newest.c.t < cutoff, True)),
        )
        .outerjoin(newest, newest.c.server_id == Server.id)
        .where(Server.site_id.in_(ids), Server.status == ServerStatus.ACTIVE.value)
        .group_by(Server.site_id)
    )
    for site_id, latest, oldest, reporting, stale in fresh.all():
        out[site_id].freshness = Freshness(
            latest_reading_at=latest,
            oldest_server_reading_at=oldest,
            servers_reporting=reporting,
            servers_stale=stale,
        )

    online = collector_online_expr()
    coll = await session.execute(
        select(Collector.site_id, func.count(), func.count().filter(online))
        .where(Collector.site_id.in_(ids))
        .group_by(Collector.site_id)
    )
    for site_id, total, n_online in coll.all():
        out[site_id].collectors_total = total
        out[site_id].collectors_online = n_online

    for summary in out.values():
        summary.worst_health = summary.health.worst()
    return [out[i] for i in ids]


def _count_alert(counts: AlertCounts, state: str, severity: str, muted: bool, n: int) -> None:
    if muted:
        counts.muted += n
        return
    if state == AlertState.ACKNOWLEDGED.value:
        counts.acknowledged += n
    if severity == Severity.CRITICAL.value:
        counts.critical += n
    elif severity == Severity.WARNING.value:
        counts.warning += n
    else:
        counts.info += n


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


async def overview(session: AsyncSession, principal: Principal) -> OverviewOut:
    sites = list((await session.execute(visible_sites_stmt(principal).order_by(Site.code))).scalars())
    summaries = await site_summaries(session, sites)
    health = HealthCounts()
    alerts = AlertCounts()
    power: float | None = None
    fresh = Freshness()
    for s in summaries:
        for field in ("ok", "warning", "critical", "unknown"):
            setattr(health, field, getattr(health, field) + getattr(s.health, field))
        for field in ("critical", "warning", "info", "acknowledged", "muted"):
            setattr(alerts, field, getattr(alerts, field) + getattr(s.alerts, field))
        if s.power_w is not None:
            power = (power or 0.0) + s.power_w
        f = s.freshness
        fresh.servers_reporting += f.servers_reporting
        fresh.servers_stale += f.servers_stale
        if f.latest_reading_at and (
            fresh.latest_reading_at is None or f.latest_reading_at > fresh.latest_reading_at
        ):
            fresh.latest_reading_at = f.latest_reading_at
        if f.oldest_server_reading_at and (
            fresh.oldest_server_reading_at is None
            or f.oldest_server_reading_at < fresh.oldest_server_reading_at
        ):
            fresh.oldest_server_reading_at = f.oldest_server_reading_at
    totals = OverviewTotals(
        sites=len(summaries),
        server_count=sum(s.server_count for s in summaries),
        health=health,
        worst_health=health.worst(),
        alerts=alerts,
        power_w=_round(power),
        freshness=fresh,
        collectors_online=sum(s.collectors_online for s in summaries),
        collectors_total=sum(s.collectors_total for s in summaries),
    )
    return OverviewOut(generated_at=now_utc(), totals=totals, sites=summaries)


async def site_detail(session: AsyncSession, principal: Principal, site_id: int) -> SiteDetail:
    site = await session.get(Site, site_id)
    if site is None or not principal.can_see_site(site.id):
        raise not_found("Site")
    [summary] = await site_summaries(session, [site])
    detail = SiteDetail(**summary.model_dump())

    rooms = list(
        (await session.execute(select(Room).where(Room.site_id == site.id).order_by(Room.name))).scalars()
    )
    racks = list(
        (
            await session.execute(
                select(Rack)
                .join(Room, Room.id == Rack.room_id)
                .where(Room.site_id == site.id)
                .order_by(Rack.name)
            )
        ).scalars()
    )
    rack_summaries = await rack_summaries_for(session, racks)
    by_room: dict[int, list[RackSummary]] = defaultdict(list)
    for rack in racks:
        by_room[rack.room_id].append(rack_summaries[rack.id])
    for room in rooms:
        room_racks = by_room.get(room.id, [])
        detail.rooms.append(
            RoomWithRacks(
                id=room.id,
                name=room.name,
                floor=room.floor,
                worst_health=Health.worst([r.worst_health for r in room_racks if r.server_count])
                if any(r.server_count for r in room_racks)
                else Health.UNKNOWN,
                racks=room_racks,
            )
        )
    collectors = (
        await session.execute(select(Collector).where(Collector.site_id == site.id).order_by(Collector.name))
    ).scalars()
    detail.collectors = [
        CollectorRef(id=c.id, name=c.name, online=collector_is_online(c)) for c in collectors
    ]
    return detail


async def rack_summaries_for(session: AsyncSession, racks: Sequence[Rack]) -> dict[int, RackSummary]:
    out = {
        r.id: RackSummary(
            id=r.id, name=r.name, row=r.row, height_u=r.height_u, power_capacity_w=r.power_capacity_w
        )
        for r in racks
    }
    ids = list(out)
    if not ids:
        return out
    metrics = await metrics_by_code(session)
    power_id, inlet_id = metrics["power_w"].id, metrics["inlet_temp_c"].id
    cutoff = now_utc() - STALE_AFTER
    wh = worst_health_subquery()
    rank = server_rank(wh)
    rows = await session.execute(
        select(Server.rack_id, rank, func.count(), func.sum(Server.height_u))
        .outerjoin(wh, wh.c.server_id == Server.id)
        .where(Server.rack_id.in_(ids), _NOT_DECOM)
        .group_by(Server.rack_id, rank)
    )
    for rack_id, r, n, used in rows.all():
        if rack_id is None:
            continue
        summary = out[rack_id]
        summary.server_count += n
        summary.used_u += int(used or 0)
        summary.health.add(health_from_rank(r), n)
    alerts = await session.execute(
        select(Server.rack_id, func.count())
        .select_from(Alert)
        .join(Server, Server.id == Alert.server_id)
        .where(Server.rack_id.in_(ids), Alert.state != AlertState.RESOLVED.value, Alert.muted.is_(False))
        .group_by(Server.rack_id)
    )
    for rack_id, n in alerts.all():
        if rack_id is not None:
            out[rack_id].open_alerts = n
    live = await session.execute(
        select(
            Server.rack_id,
            func.sum(LatestReading.value).filter(LatestReading.metric_code == power_id),
            func.max(LatestReading.value).filter(LatestReading.metric_code == inlet_id),
        )
        .join(Server, Server.id == LatestReading.server_id)
        .where(
            Server.rack_id.in_(ids),
            _NOT_DECOM,
            LatestReading.component == "",
            LatestReading.metric_code.in_([power_id, inlet_id]),
            LatestReading.time >= cutoff,
        )
        .group_by(Server.rack_id)
    )
    for rack_id, power, inlet_max in live.all():
        if rack_id is not None:
            out[rack_id].power_w = _round(power)
            out[rack_id].inlet_max_c = _round(inlet_max)
    for summary in out.values():
        summary.worst_health = summary.health.worst()
    return out


async def rack_detail(session: AsyncSession, principal: Principal, rack_id: int) -> RackDetail:
    row = (
        await session.execute(
            select(Rack, Room, Site)
            .join(Room, Room.id == Rack.room_id)
            .join(Site, Site.id == Room.site_id)
            .where(Rack.id == rack_id)
        )
    ).first()
    if row is None or not principal.can_see_site(row[2].id):
        raise not_found("Rack")
    rack, room, site = row
    metrics = await metrics_by_code(session)
    power_id, inlet_id = metrics["power_w"].id, metrics["inlet_temp_c"].id
    wh = worst_health_subquery()
    servers = (
        await session.execute(
            select(Server, server_rank(wh))
            .outerjoin(wh, wh.c.server_id == Server.id)
            .where(Server.rack_id == rack.id, _NOT_DECOM)
            .order_by(Server.position_u.asc().nulls_last(), Server.id)
        )
    ).all()
    ids = [s.id for s, _ in servers]
    readings: dict[tuple[int, int], LatestReading] = {}
    alert_counts: dict[int, tuple[int, str | None]] = {}
    if ids:
        lr = await session.execute(
            select(LatestReading).where(
                LatestReading.server_id.in_(ids),
                LatestReading.component == "",
                LatestReading.metric_code.in_([power_id, inlet_id]),
            )
        )
        for reading in lr.scalars():
            readings[(reading.server_id, reading.metric_code)] = reading
        sev_rank = func.max(
            case(
                (Alert.severity == Severity.CRITICAL.value, 3),
                (Alert.severity == Severity.WARNING.value, 2),
                else_=1,
            )
        )
        ar = await session.execute(
            select(Alert.server_id, func.count(), sev_rank)
            .where(Alert.server_id.in_(ids), Alert.state != AlertState.RESOLVED.value, Alert.muted.is_(False))
            .group_by(Alert.server_id)
        )
        for server_id, n, worst in ar.all():
            alert_counts[server_id] = (n, ["Info", "Warning", "Critical"][worst - 1] if worst else None)
    now = now_utc()
    out: list[RackServer] = []
    used = 0
    power_total: float | None = None
    for server, rank in servers:
        used += server.height_u
        inlet = readings.get((server.id, inlet_id))
        power = readings.get((server.id, power_id))
        if power is not None and power.value is not None and power.time >= now - STALE_AFTER:
            power_total = (power_total or 0.0) + power.value
        n_alerts, worst_sev = alert_counts.get(server.id, (0, None))
        out.append(
            RackServer(
                id=server.id,
                name=display_name(server),
                bmc_host=server.bmc_host,
                vendor=server.vendor,
                model=server.model,
                position_u=server.position_u,
                height_u=server.height_u,
                status=server.status,
                health=health_from_rank(rank),
                inlet_temp=_reading_value(inlet, metrics["inlet_temp_c"].unit),
                power=_reading_value(power, metrics["power_w"].unit),
                open_alerts=n_alerts,
                worst_alert_severity=worst_sev,
            )
        )
    return RackDetail(
        id=rack.id,
        name=rack.name,
        row=rack.row,
        height_u=rack.height_u,
        power_capacity_w=rack.power_capacity_w,
        site=SiteRef(id=site.id, code=site.code, name=site.name),
        room=RoomRef(id=room.id, name=room.name),
        used_u=used,
        free_u=max(0, rack.height_u - used),
        power_w=_round(power_total),
        worst_health=Health.worst([s.health for s in out]) if out else Health.UNKNOWN,
        servers=out,
    )


def _reading_value(reading: LatestReading | None, unit: str) -> ReadingValue | None:
    if reading is None:
        return None
    return ReadingValue(
        value=reading.value, unit=unit, status=reading.status, time=reading.time, age_s=age_s(reading.time)
    )
