"""Maintenance windows, collectors, firmware baselines and compliance."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.orm import aliased

from app.api.deps import PageDep, SessionDep, flush_or_409
from app.core import audit
from app.core.enums import MaintenanceScope, ServerStatus
from app.core.pagination import AnySelect, SortKey, paginate
from app.core.problems import Problem
from app.core.security import AdminUser, EngineerUser, Principal, ViewerUser, ensure_unrestricted, not_found
from app.models import Collector, FirmwareBaseline, MaintenanceWindow, Rack, Room, Server, Site
from app.schemas.admin import (
    BaselineCreate,
    BaselineOut,
    BaselinePage,
    BaselineUpdate,
    CollectorCreate,
    CollectorOut,
    CollectorPage,
    CollectorUpdate,
    ComplianceOut,
    MaintenanceCreate,
    MaintenanceOut,
    MaintenancePage,
    MaintenanceUpdate,
)
from app.services.query.common import age_s, collector_is_online, now_utc
from app.services.query.firmware import ComplianceFilters, compliance

router = APIRouter(tags=["operations"])


# -------------------------------------------------------------------------------- maintenance windows

_mw_room = aliased(Room)
_mw_rack = aliased(Rack)
_mw_server = aliased(Server)
_mw_site = aliased(Site)
_mw_target_site: ColumnElement[int] = func.coalesce(
    MaintenanceWindow.site_id, _mw_room.site_id, _mw_server.site_id
)


def _mw_stmt(principal: Principal) -> AnySelect:
    return (
        select(
            MaintenanceWindow,
            _mw_target_site.label("target_site_id"),
            _mw_site.code,
            _mw_rack.name,
            func.coalesce(_mw_server.name, _mw_server.bmc_host),
        )
        .outerjoin(_mw_rack, _mw_rack.id == MaintenanceWindow.rack_id)
        .outerjoin(_mw_room, _mw_room.id == _mw_rack.room_id)
        .outerjoin(_mw_server, _mw_server.id == MaintenanceWindow.server_id)
        .outerjoin(_mw_site, _mw_site.id == _mw_target_site)
        .where(principal.site_filter(_mw_target_site))
    )


def _mw_out(row: Any) -> MaintenanceOut:
    mw: MaintenanceWindow = row[0]
    names = {"site": row[2], "rack": f"{row[2]} / {row[3]}", "server": row[4]}
    now = now_utc()
    return MaintenanceOut(
        id=mw.id,
        scope=mw.scope,
        site_id=mw.site_id,
        rack_id=mw.rack_id,
        server_id=mw.server_id,
        target_site_id=row[1],
        target_name=str(names.get(mw.scope) or ""),
        starts_at=mw.starts_at,
        ends_at=mw.ends_at,
        reason=mw.reason,
        created_by=mw.created_by,
        created_at=mw.created_at,
        active=mw.starts_at <= now < mw.ends_at,
    )


async def _mw_by_id(
    session: SessionDep, principal: Principal, mw_id: int
) -> tuple[MaintenanceWindow, MaintenanceOut]:
    row = (await session.execute(_mw_stmt(principal).where(MaintenanceWindow.id == mw_id))).first()
    if row is None:
        raise not_found("Maintenance window")
    return row[0], _mw_out(row)


@router.get("/maintenance-windows", response_model=MaintenancePage, summary="Maintenance windows")
async def list_maintenance(
    principal: ViewerUser,
    session: SessionDep,
    page: PageDep,
    when: Annotated[Literal["active", "upcoming", "past", "current_and_upcoming"] | None, Query()] = None,
    site_id: Annotated[int | None, Query()] = None,
    scope: Annotated[MaintenanceScope | None, Query()] = None,
    server_id: Annotated[int | None, Query()] = None,
) -> MaintenancePage:
    now = now_utc()
    stmt = _mw_stmt(principal)
    if when == "active":
        stmt = stmt.where(MaintenanceWindow.starts_at <= now, MaintenanceWindow.ends_at > now)
    elif when == "upcoming":
        stmt = stmt.where(MaintenanceWindow.starts_at > now)
    elif when == "past":
        stmt = stmt.where(MaintenanceWindow.ends_at <= now)
    elif when == "current_and_upcoming":
        stmt = stmt.where(MaintenanceWindow.ends_at > now)
    if site_id is not None:
        stmt = stmt.where(_mw_target_site == site_id)
    if scope is not None:
        stmt = stmt.where(MaintenanceWindow.scope == scope.value)
    if server_id is not None:
        stmt = stmt.where(MaintenanceWindow.server_id == server_id)
    rows, next_cursor = await paginate(
        session,
        stmt,
        [SortKey(MaintenanceWindow.starts_at, True), SortKey(MaintenanceWindow.id, True)],
        page,
        "mw",
    )
    return MaintenancePage(items=[_mw_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/maintenance-windows/{mw_id}", response_model=MaintenanceOut, summary="One maintenance window")
async def get_maintenance(mw_id: int, principal: ViewerUser, session: SessionDep) -> MaintenanceOut:
    return (await _mw_by_id(session, principal, mw_id))[1]


async def _target_site(session: SessionDep, body: MaintenanceCreate) -> int | None:
    if body.scope == MaintenanceScope.SITE:
        site = await session.get(Site, body.site_id)
        return site.id if site else None
    if body.scope == MaintenanceScope.RACK:
        row = (
            await session.execute(
                select(Room.site_id).join(Rack, Rack.room_id == Room.id).where(Rack.id == body.rack_id)
            )
        ).first()
        return int(row[0]) if row else None
    server = await session.get(Server, body.server_id)
    return server.site_id if server and server.status != ServerStatus.DECOMMISSIONED.value else None


@router.post(
    "/maintenance-windows",
    response_model=MaintenanceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a maintenance window (mutes alerts for the site, rack or server)",
)
async def create_maintenance(
    body: MaintenanceCreate, principal: EngineerUser, session: SessionDep, request: Request
) -> MaintenanceOut:
    site_id = await _target_site(session, body)
    if site_id is None or not principal.can_see_site(site_id):
        raise Problem(422, f"Unknown {body.scope.value}.")
    mw = MaintenanceWindow(
        scope=body.scope.value,
        site_id=body.site_id,
        rack_id=body.rack_id,
        server_id=body.server_id,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        reason=body.reason,
        created_by=principal.display_name,
    )
    session.add(mw)
    await flush_or_409(session, "The maintenance window conflicts with existing data.")
    audit.record(
        session,
        principal=principal,
        action="maintenance.create",
        object_type="maintenance_window",
        object_id=mw.id,
        after=audit.snapshot(mw),
        request=request,
    )
    await session.commit()
    return (await _mw_by_id(session, principal, mw.id))[1]


@router.patch("/maintenance-windows/{mw_id}", response_model=MaintenanceOut, summary="Change times or reason")
async def update_maintenance(
    mw_id: int, body: MaintenanceUpdate, principal: EngineerUser, session: SessionDep, request: Request
) -> MaintenanceOut:
    mw, _ = await _mw_by_id(session, principal, mw_id)
    before = audit.snapshot(mw)
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        if value is None:
            raise Problem(422, f"{key} cannot be null.")
        if isinstance(value, datetime) and value.tzinfo is None:
            raise Problem(422, f"{key} needs a UTC offset.")
        setattr(mw, key, value)
    if mw.ends_at <= mw.starts_at:
        raise Problem(422, "ends_at must be after starts_at.")
    await flush_or_409(session, "The maintenance window conflicts with existing data.")
    b, a = audit.changed(before, audit.snapshot(mw))
    audit.record(
        session,
        principal=principal,
        action="maintenance.update",
        object_type="maintenance_window",
        object_id=mw.id,
        before=b,
        after=a,
        request=request,
    )
    await session.commit()
    return (await _mw_by_id(session, principal, mw.id))[1]


@router.delete(
    "/maintenance-windows/{mw_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Cancel a window"
)
async def delete_maintenance(
    mw_id: int, principal: EngineerUser, session: SessionDep, request: Request
) -> Response:
    mw, _ = await _mw_by_id(session, principal, mw_id)
    audit.record(
        session,
        principal=principal,
        action="maintenance.delete",
        object_type="maintenance_window",
        object_id=mw.id,
        before=audit.snapshot(mw),
        request=request,
    )
    await session.execute(delete(MaintenanceWindow).where(MaintenanceWindow.id == mw.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------------------------------ collectors


def _collector_stmt(principal: Principal) -> AnySelect:
    servers = (
        select(Server.collector_id, func.count().label("n"))
        .where(Server.status != ServerStatus.DECOMMISSIONED.value)
        .group_by(Server.collector_id)
        .subquery()
    )
    return (
        select(Collector, Site.code, func.coalesce(servers.c.n, 0))
        .join(Site, Site.id == Collector.site_id)
        .outerjoin(servers, servers.c.collector_id == Collector.id)
        .where(principal.site_filter(Collector.site_id))
    )


def _collector_out(row: Any) -> CollectorOut:
    c: Collector = row[0]
    return CollectorOut(
        id=c.id,
        site_id=c.site_id,
        site_code=row[1],
        name=c.name,
        version=c.version,
        hostname=c.hostname,
        enabled=c.enabled,
        online=collector_is_online(c),
        last_heartbeat=c.last_heartbeat,
        heartbeat_age_s=age_s(c.last_heartbeat) if c.last_heartbeat else None,
        cert_fingerprint=c.cert_fingerprint,
        servers_preferred=int(row[2]),
        stats=c.stats or {},
        created_at=c.created_at,
    )


async def _collector_by_id(
    session: SessionDep, principal: Principal, collector_id: int
) -> tuple[Collector, CollectorOut]:
    row = (await session.execute(_collector_stmt(principal).where(Collector.id == collector_id))).first()
    if row is None:
        raise not_found("Collector")
    return row[0], _collector_out(row)


@router.get("/collectors", response_model=CollectorPage, summary="Collectors with online status and stats")
async def list_collectors(
    principal: ViewerUser,
    session: SessionDep,
    page: PageDep,
    site_id: Annotated[int | None, Query()] = None,
) -> CollectorPage:
    stmt = _collector_stmt(principal)
    if site_id is not None:
        stmt = stmt.where(Collector.site_id == site_id)
    rows, next_cursor = await paginate(
        session,
        stmt,
        [SortKey(Site.code), SortKey(Collector.name), SortKey(Collector.id)],
        page,
        "collectors",
    )
    return CollectorPage(items=[_collector_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/collectors/{collector_id}", response_model=CollectorOut, summary="One collector")
async def get_collector(collector_id: int, principal: ViewerUser, session: SessionDep) -> CollectorOut:
    return (await _collector_by_id(session, principal, collector_id))[1]


@router.post(
    "/collectors",
    response_model=CollectorOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a collector",
)
async def create_collector(
    body: CollectorCreate, principal: AdminUser, session: SessionDep, request: Request
) -> CollectorOut:
    site = await session.get(Site, body.site_id)
    if site is None or not principal.can_see_site(site.id):
        raise Problem(422, "Unknown site.")
    collector = Collector(**body.model_dump())
    session.add(collector)
    await flush_or_409(session, "A collector with that name or certificate already exists.")
    audit.record(
        session,
        principal=principal,
        action="collector.create",
        object_type="collector",
        object_id=collector.id,
        after=audit.snapshot(collector),
        request=request,
    )
    await session.commit()
    return (await _collector_by_id(session, principal, collector.id))[1]


@router.patch(
    "/collectors/{collector_id}", response_model=CollectorOut, summary="Enable/disable or set the certificate"
)
async def update_collector(
    collector_id: int, body: CollectorUpdate, principal: AdminUser, session: SessionDep, request: Request
) -> CollectorOut:
    collector, _ = await _collector_by_id(session, principal, collector_id)
    before = audit.snapshot(collector, exclude={"stats", "last_heartbeat"})
    data = body.model_dump(exclude_unset=True)
    if "enabled" in data and data["enabled"] is None:
        raise Problem(422, "enabled cannot be null.")
    for key, value in data.items():
        setattr(collector, key, value)
    await flush_or_409(session, "Another collector already uses that certificate.")
    b, a = audit.changed(before, audit.snapshot(collector, exclude={"stats", "last_heartbeat"}))
    audit.record(
        session,
        principal=principal,
        action="collector.update",
        object_type="collector",
        object_id=collector.id,
        before=b,
        after=a,
        request=request,
    )
    await session.commit()
    return (await _collector_by_id(session, principal, collector.id))[1]


# ------------------------------------------------------------------------------------------- firmware


@router.get(
    "/firmware/baselines", response_model=BaselinePage, summary="Approved firmware per vendor and model"
)
async def list_baselines(
    principal: ViewerUser,
    session: SessionDep,
    page: PageDep,
    vendor: Annotated[str | None, Query(max_length=32)] = None,
    model: Annotated[str | None, Query(max_length=128)] = None,
    component: Annotated[str | None, Query(max_length=160)] = None,
) -> BaselinePage:
    stmt = select(FirmwareBaseline)
    if vendor:
        stmt = stmt.where(FirmwareBaseline.vendor == vendor)
    if model:
        stmt = stmt.where(FirmwareBaseline.model == model)
    if component:
        stmt = stmt.where(FirmwareBaseline.component == component)
    keys = [
        SortKey(FirmwareBaseline.vendor),
        SortKey(FirmwareBaseline.model),
        SortKey(FirmwareBaseline.component),
        SortKey(FirmwareBaseline.id),
    ]
    rows, next_cursor = await paginate(session, stmt, keys, page, "baselines")
    return BaselinePage(items=[BaselineOut.model_validate(r[0]) for r in rows], next_cursor=next_cursor)


@router.post(
    "/firmware/baselines",
    response_model=BaselineOut,
    status_code=status.HTTP_201_CREATED,
    summary="Approve a version",
)
async def create_baseline(
    body: BaselineCreate, principal: EngineerUser, session: SessionDep, request: Request
) -> BaselineOut:
    ensure_unrestricted(principal, "A firmware baseline")
    baseline = FirmwareBaseline(**body.model_dump(), updated_by=principal.display_name)
    session.add(baseline)
    await flush_or_409(session, "A baseline for that vendor, model and component already exists.")
    audit.record(
        session,
        principal=principal,
        action="baseline.create",
        object_type="firmware_baseline",
        object_id=baseline.id,
        after=audit.snapshot(baseline),
        request=request,
    )
    await session.commit()
    await session.refresh(baseline)
    return BaselineOut.model_validate(baseline)


async def _baseline(session: SessionDep, baseline_id: int) -> FirmwareBaseline:
    baseline = await session.get(FirmwareBaseline, baseline_id)
    if baseline is None:
        raise not_found("Baseline")
    return baseline


@router.put(
    "/firmware/baselines/{baseline_id}", response_model=BaselineOut, summary="Change an approved version"
)
async def update_baseline(
    baseline_id: int, body: BaselineUpdate, principal: EngineerUser, session: SessionDep, request: Request
) -> BaselineOut:
    ensure_unrestricted(principal, "A firmware baseline")
    baseline = await _baseline(session, baseline_id)
    before = audit.snapshot(baseline)
    data = body.model_dump(exclude_unset=True)
    if "version" in data and data["version"] is None:
        raise Problem(422, "version cannot be null.")
    for key, value in data.items():
        setattr(baseline, key, value)
    baseline.updated_by = principal.display_name
    await flush_or_409(session, "Baseline update conflicts with another row.")
    b, a = audit.changed(before, audit.snapshot(baseline))
    audit.record(
        session,
        principal=principal,
        action="baseline.update",
        object_type="firmware_baseline",
        object_id=baseline.id,
        before=b,
        after=a,
        request=request,
    )
    await session.commit()
    await session.refresh(baseline)
    return BaselineOut.model_validate(baseline)


@router.delete(
    "/firmware/baselines/{baseline_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a baseline"
)
async def delete_baseline(
    baseline_id: int, principal: EngineerUser, session: SessionDep, request: Request
) -> Response:
    ensure_unrestricted(principal, "A firmware baseline")
    baseline = await _baseline(session, baseline_id)
    audit.record(
        session,
        principal=principal,
        action="baseline.delete",
        object_type="firmware_baseline",
        object_id=baseline.id,
        before=audit.snapshot(baseline),
        request=request,
    )
    await session.execute(delete(FirmwareBaseline).where(FirmwareBaseline.id == baseline.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/firmware/compliance",
    response_model=ComplianceOut,
    summary="Servers whose firmware differs from the baseline",
)
async def firmware_compliance(
    principal: ViewerUser,
    session: SessionDep,
    page: PageDep,
    site_id: Annotated[int | None, Query()] = None,
    vendor: Annotated[str | None, Query(max_length=32)] = None,
    model: Annotated[str | None, Query(max_length=128)] = None,
    component: Annotated[str | None, Query(max_length=160, description="Firmware key, e.g. BIOS")] = None,
) -> ComplianceOut:
    filters = ComplianceFilters(site_id=site_id, vendor=vendor, model=model, component=component)
    return await compliance(session, principal, filters, page)
