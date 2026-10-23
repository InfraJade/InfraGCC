"""Server list (Inventory), server detail, parts, events and global search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.enums import AlertState, Health, ServerStatus
from app.core.pagination import AnyRow, AnySelect, SortKey
from app.core.security import Principal, not_found
from app.models import (
    Alert,
    Collector,
    Component,
    Event,
    FirmwareBaseline,
    FirmwareInventory,
    HealthStatus,
    LatestReading,
    MetricDefinition,
    Rack,
    Room,
    Server,
    Site,
)
from app.schemas.common import CollectorRef, RackRef, RoomRef, SiteRef
from app.schemas.misc import SearchOut, SearchRack, SearchServer, SearchSite
from app.schemas.servers import (
    ComponentListItem,
    ComponentOut,
    EventOut,
    FirmwareItem,
    HealthPart,
    LatestReadingOut,
    ServerDetail,
    ServerListItem,
)
from app.services.query.alerts import alert_select, alerts_from_rows
from app.services.query.common import (
    HEALTH_RANK,
    UNKNOWN_RANK,
    age_s,
    collector_is_online,
    display_name,
    health_from_rank,
    like_pattern,
    now_utc,
    open_alerts_subquery,
    worst_health_subquery,
)

ServerSort = Literal[
    "name", "-name", "health", "-health", "site", "rack", "vendor", "model", "last_seen", "-last_seen", "id"
]


@dataclass(frozen=True)
class ServerFilters:
    site_id: int | None = None
    room_id: int | None = None
    rack_id: int | None = None
    collector_id: int | None = None
    vendor: str | None = None
    model: str | None = None
    health: Health | None = None
    status: ServerStatus | None = None
    q: str | None = None
    include_decommissioned: bool = False


def server_list_select(
    principal: Principal, f: ServerFilters, sort: ServerSort
) -> tuple[AnySelect, list[SortKey]]:
    """SELECT for server list rows (server, site, room, rack, collector name, health rank, open alerts)."""
    wh = worst_health_subquery()
    oa = open_alerts_subquery()
    rank = func.coalesce(wh.c.rank, literal(UNKNOWN_RANK))
    stmt = (
        select(
            Server,
            Site,
            Room,
            Rack,
            Collector.name.label("collector_name"),
            rank.label("health_rank"),
            func.coalesce(oa.c.n, 0).label("open_alerts"),
        )
        .join(Site, Site.id == Server.site_id)
        .outerjoin(Rack, Rack.id == Server.rack_id)
        .outerjoin(Room, Room.id == Rack.room_id)
        .outerjoin(Collector, Collector.id == Server.collector_id)
        .outerjoin(wh, wh.c.server_id == Server.id)
        .outerjoin(oa, oa.c.server_id == Server.id)
        .where(principal.site_filter(Server.site_id))
    )
    if f.site_id is not None:
        stmt = stmt.where(Server.site_id == f.site_id)
    if f.room_id is not None:
        stmt = stmt.where(Rack.room_id == f.room_id)
    if f.rack_id is not None:
        stmt = stmt.where(Server.rack_id == f.rack_id)
    if f.collector_id is not None:
        stmt = stmt.where(Server.collector_id == f.collector_id)
    if f.vendor:
        stmt = stmt.where(func.lower(Server.vendor) == f.vendor.lower())
    if f.model:
        stmt = stmt.where(func.lower(Server.model) == f.model.lower())
    if f.health is not None:
        stmt = stmt.where(rank == HEALTH_RANK[f.health])
    if f.status is not None:
        stmt = stmt.where(Server.status == f.status.value)
    elif not f.include_decommissioned:
        stmt = stmt.where(Server.status != ServerStatus.DECOMMISSIONED.value)
    if f.q:
        pattern = like_pattern(f.q.strip())
        stmt = stmt.where(
            or_(
                Server.name.ilike(pattern),
                Server.serial.ilike(pattern),
                Server.bmc_host.ilike(pattern),
                Server.asset_tag.ilike(pattern),
                Server.model.ilike(pattern),
            )
        )
    name = func.coalesce(Server.name, Server.bmc_host)
    keys: dict[str, list[SortKey]] = {
        "name": [SortKey(name)],
        "-name": [SortKey(name, True)],
        "health": [SortKey(rank, True), SortKey(name)],
        "-health": [SortKey(rank), SortKey(name)],
        "site": [
            SortKey(Site.code),
            SortKey(func.coalesce(Rack.name, "")),
            SortKey(func.coalesce(Server.position_u, 0)),
        ],
        "rack": [SortKey(func.coalesce(Rack.name, "")), SortKey(func.coalesce(Server.position_u, 0))],
        "vendor": [
            SortKey(func.coalesce(Server.vendor, "")),
            SortKey(func.coalesce(Server.model, "")),
            SortKey(name),
        ],
        "model": [SortKey(func.coalesce(Server.model, "")), SortKey(name)],
        "last_seen": [SortKey(func.coalesce(Server.last_seen_at, func.to_timestamp(0)))],
        "-last_seen": [SortKey(func.coalesce(Server.last_seen_at, func.to_timestamp(0)), True)],
        "id": [],
    }
    return stmt, [*keys[sort], SortKey(Server.id)]


def server_item_from_row(row: AnyRow) -> ServerListItem:
    server: Server = row[0]
    site: Site = row[1]
    room: Room | None = row[2]
    rack: Rack | None = row[3]
    m = row._mapping
    return ServerListItem(
        id=server.id,
        name=display_name(server),
        hostname=server.name,
        bmc_host=server.bmc_host,
        vendor=server.vendor,
        model=server.model,
        serial=server.serial,
        asset_tag=server.asset_tag,
        status=server.status,
        health=health_from_rank(m["health_rank"]),
        site=SiteRef(id=site.id, code=site.code, name=site.name),
        room=RoomRef(id=room.id, name=room.name) if room else None,
        rack=RackRef(id=rack.id, name=rack.name) if rack else None,
        position_u=server.position_u,
        height_u=server.height_u,
        collector_id=server.collector_id,
        collector_name=m["collector_name"],
        last_seen_at=server.last_seen_at,
        open_alerts=int(m["open_alerts"]),
    )


async def get_visible_server(session: AsyncSession, principal: Principal, server_id: int) -> Server:
    server = await session.get(Server, server_id)
    if server is None or not principal.can_see_site(server.site_id):
        raise not_found("Server")
    return server


async def server_detail(session: AsyncSession, principal: Principal, server_id: int) -> ServerDetail:
    stmt, _ = server_list_select(principal, ServerFilters(include_decommissioned=True), "id")
    row = (await session.execute(stmt.where(Server.id == server_id))).first()
    if row is None:
        raise not_found("Server")
    item = server_item_from_row(row)
    server: Server = row[0]
    rack: Rack | None = row[3]
    now = now_utc()

    health = await session.execute(
        select(HealthStatus, MetricDefinition)
        .join(MetricDefinition, MetricDefinition.id == HealthStatus.metric_code)
        .where(HealthStatus.server_id == server.id)
        .order_by(MetricDefinition.parameter_no, MetricDefinition.id, HealthStatus.component)
    )
    parts = [
        HealthPart(
            metric=md.code,
            metric_name=md.name,
            category=md.category,
            component=h.component,
            health=Health(h.health),
            state=h.state,
            since=h.since,
            updated_at=h.updated_at,
        )
        for h, md in health.all()
    ]
    latest = await session.execute(
        select(LatestReading, MetricDefinition)
        .join(MetricDefinition, MetricDefinition.id == LatestReading.metric_code)
        .where(LatestReading.server_id == server.id)
        .order_by(MetricDefinition.parameter_no, MetricDefinition.id, LatestReading.component)
    )
    readings = [
        LatestReadingOut(
            metric=md.code,
            metric_name=md.name,
            unit=md.unit,
            type=md.type,
            category=md.category,
            component=lr.component,
            value=lr.value,
            status=lr.status,
            time=lr.time,
            age_s=age_s(lr.time, now),
        )
        for lr, md in latest.all()
    ]
    components = [
        ComponentOut.model_validate(c)
        for c in (
            await session.execute(
                select(Component)
                .where(Component.server_id == server.id, Component.removed_at.is_(None))
                .order_by(Component.type, Component.name)
            )
        ).scalars()
    ]
    firmware = await firmware_for(session, server)
    events = [
        EventOut.model_validate(e)
        for e in (
            await session.execute(
                select(Event)
                .where(Event.server_id == server.id)
                .order_by(Event.time.desc(), Event.id.desc())
                .limit(20)
            )
        ).scalars()
    ]
    alert_rows = (
        await session.execute(
            alert_select()
            .where(Alert.server_id == server.id, Alert.state != AlertState.RESOLVED.value)
            .order_by(Alert.opened_at.desc(), Alert.id.desc())
        )
    ).all()
    collector = None
    if server.collector_id is not None:
        c = await session.get(Collector, server.collector_id)
        if c is not None:
            collector = CollectorRef(id=c.id, name=c.name, online=collector_is_online(c))
    return ServerDetail(
        **item.model_dump(),
        bmc_mac=server.bmc_mac,
        bmc_model=server.bmc_model,
        host_ips=list(server.host_ips or []),
        system_path=server.system_path,
        notes=server.notes,
        discovered_at=server.discovered_at,
        created_at=server.created_at,
        updated_at=server.updated_at,
        collector=collector,
        rack_height_u=rack.height_u if rack else None,
        health_parts=parts,
        latest_readings=readings,
        components=components,
        firmware=firmware,
        recent_events=events,
        active_alerts=alerts_from_rows(alert_rows),
    )


async def firmware_for(session: AsyncSession, server: Server) -> list[FirmwareItem]:
    rows = await session.execute(
        select(FirmwareInventory, FirmwareBaseline.version)
        .outerjoin(
            FirmwareBaseline,
            (FirmwareBaseline.vendor == server.vendor)
            & (FirmwareBaseline.model == server.model)
            & (FirmwareBaseline.component == FirmwareInventory.component_key),
        )
        .where(FirmwareInventory.server_id == server.id)
        .order_by(FirmwareInventory.component_type, FirmwareInventory.component)
    )
    return [
        FirmwareItem(
            component=f.component,
            component_key=f.component_key,
            component_type=f.component_type,
            version=f.version,
            approved_version=approved,
            compliant=None if approved is None else approved == f.version,
            collected_at=f.collected_at,
        )
        for f, approved in rows.all()
    ]


def events_select(server_id: int, severity: str | None, q: str | None) -> tuple[AnySelect, list[SortKey]]:
    stmt = select(Event).where(Event.server_id == server_id)
    if severity:
        stmt = stmt.where(Event.severity == severity)
    if q:
        pattern = like_pattern(q)
        stmt = stmt.where(or_(Event.message.ilike(pattern), Event.message_id.ilike(pattern)))
    return stmt, [SortKey(Event.time, True), SortKey(Event.id, True)]


@dataclass(frozen=True)
class ComponentFilters:
    site_id: int | None = None
    server_id: int | None = None
    type: str | None = None
    model: str | None = None
    manufacturer: str | None = None
    q: str | None = None
    include_removed: bool = False


def components_select(principal: Principal, f: ComponentFilters) -> tuple[AnySelect, list[SortKey]]:
    stmt = (
        select(Component, Server.name, Server.bmc_host, Server.site_id, Site.code)
        .join(Server, Server.id == Component.server_id)
        .join(Site, Site.id == Server.site_id)
        .where(principal.site_filter(Server.site_id), Server.status != ServerStatus.DECOMMISSIONED.value)
    )
    if not f.include_removed:
        stmt = stmt.where(Component.removed_at.is_(None))
    if f.site_id is not None:
        stmt = stmt.where(Server.site_id == f.site_id)
    if f.server_id is not None:
        stmt = stmt.where(Component.server_id == f.server_id)
    if f.type:
        stmt = stmt.where(Component.type == f.type)
    if f.model:
        stmt = stmt.where(func.lower(Component.model) == f.model.lower())
    if f.manufacturer:
        stmt = stmt.where(func.lower(Component.manufacturer) == f.manufacturer.lower())
    if f.q:
        pattern = like_pattern(f.q.strip())
        stmt = stmt.where(
            or_(
                Component.name.ilike(pattern),
                Component.model.ilike(pattern),
                Component.serial.ilike(pattern),
                Component.manufacturer.ilike(pattern),
            )
        )
    return stmt, [
        SortKey(Component.server_id),
        SortKey(Component.type),
        SortKey(Component.name),
        SortKey(Component.id),
    ]


def component_item_from_row(row: AnyRow) -> ComponentListItem:
    component: Component = row[0]
    base = ComponentOut.model_validate(component).model_dump()
    return ComponentListItem(**base, server_name=row[1] or row[2], site_id=row[3], site_code=row[4])


async def search(session: AsyncSession, principal: Principal, q: str, limit: int) -> SearchOut:
    pattern = like_pattern(q.strip())
    wh = worst_health_subquery()
    rack = aliased(Rack)
    servers = await session.execute(
        select(Server, Site.code, rack.name, func.coalesce(wh.c.rank, literal(UNKNOWN_RANK)))
        .join(Site, Site.id == Server.site_id)
        .outerjoin(rack, rack.id == Server.rack_id)
        .outerjoin(wh, wh.c.server_id == Server.id)
        .where(
            principal.site_filter(Server.site_id),
            Server.status != ServerStatus.DECOMMISSIONED.value,
            or_(
                Server.name.ilike(pattern),
                Server.serial.ilike(pattern),
                Server.bmc_host.ilike(pattern),
                Server.asset_tag.ilike(pattern),
            ),
        )
        .order_by(func.coalesce(Server.name, Server.bmc_host), Server.id)
        .limit(limit)
    )
    racks = await session.execute(
        select(Rack, Room.name, Site.id, Site.code)
        .join(Room, Room.id == Rack.room_id)
        .join(Site, Site.id == Room.site_id)
        .where(principal.site_filter(Site.id), Rack.name.ilike(pattern))
        .order_by(Site.code, Rack.name, Rack.id)
        .limit(limit)
    )
    sites = await session.execute(
        select(Site)
        .where(
            principal.site_filter(Site.id),
            or_(Site.code.ilike(pattern), Site.name.ilike(pattern), Site.city.ilike(pattern)),
        )
        .order_by(Site.code)
        .limit(limit)
    )
    return SearchOut(
        query=q,
        servers=[
            SearchServer(
                id=s.id,
                name=display_name(s),
                bmc_host=s.bmc_host,
                serial=s.serial,
                asset_tag=s.asset_tag,
                model=s.model,
                site_code=code,
                rack_name=rack_name,
                position_u=s.position_u,
                health=health_from_rank(rank),
            )
            for s, code, rack_name, rank in servers.all()
        ],
        racks=[
            SearchRack(id=r.id, name=r.name, room_name=room_name, site_id=site_id, site_code=code)
            for r, room_name, site_id, code in racks.all()
        ],
        sites=[SearchSite(id=s.id, code=s.code, name=s.name, city=s.city) for s in sites.scalars()],
    )
