"""Servers (Inventory, Server detail, onboarding) and their parts, events, history and CSV exports."""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import PageDep, SessionDep, flush_or_409
from app.core import audit
from app.core.db import get_sessionmaker
from app.core.enums import ComponentType, Health, ServerStatus
from app.core.pagination import AnyRow, AnySelect, PageParams, SortKey, paginate
from app.core.problems import Problem
from app.core.security import EngineerUser, Principal, ViewerUser
from app.models import Collector, Rack, Room, Server
from app.schemas.servers import (
    ComponentPage,
    EventOut,
    EventPage,
    ReadingsOut,
    ServerCreate,
    ServerDetail,
    ServerPage,
    ServerUpdate,
)
from app.services.query import servers as queries
from app.services.query.common import metric_or_422
from app.services.query.readings import reading_history

router = APIRouter(tags=["servers"])

_CSV_CHUNK = 1000
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def server_filters(
    site_id: Annotated[int | None, Query()] = None,
    room_id: Annotated[int | None, Query()] = None,
    rack_id: Annotated[int | None, Query()] = None,
    collector_id: Annotated[int | None, Query()] = None,
    vendor: Annotated[str | None, Query(max_length=64)] = None,
    model: Annotated[str | None, Query(max_length=128)] = None,
    health: Annotated[Health | None, Query()] = None,
    status_: Annotated[
        ServerStatus | None, Query(alias="status", description="Default: everything except decommissioned.")
    ] = None,
    q: Annotated[
        str | None, Query(max_length=100, description="Name, serial, BMC address, asset tag")
    ] = None,
) -> queries.ServerFilters:
    return queries.ServerFilters(
        site_id=site_id,
        room_id=room_id,
        rack_id=rack_id,
        collector_id=collector_id,
        vendor=vendor,
        model=model,
        health=health,
        status=status_,
        q=q,
    )


def component_filters(
    site_id: Annotated[int | None, Query()] = None,
    server_id: Annotated[int | None, Query()] = None,
    type_: Annotated[ComponentType | None, Query(alias="type")] = None,
    model: Annotated[str | None, Query(max_length=128)] = None,
    manufacturer: Annotated[str | None, Query(max_length=128)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    include_removed: Annotated[bool, Query()] = False,
) -> queries.ComponentFilters:
    return queries.ComponentFilters(
        site_id=site_id,
        server_id=server_id,
        type=type_.value if type_ else None,
        model=model,
        manufacturer=manufacturer,
        q=q,
        include_removed=include_removed,
    )


ServerFiltersDep = Annotated[queries.ServerFilters, Depends(server_filters)]
ComponentFiltersDep = Annotated[queries.ComponentFilters, Depends(component_filters)]
SortDep = Annotated[queries.ServerSort, Query(description="Sort order; prefix `-` reverses.")]


# ------------------------------------------------------------------------------------------ CSV export


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
        # Keep spreadsheets from treating cell text as a formula.
        return "'" + value
    return value


def _csv_response(
    filename: str,
    header: list[str],
    stmt: AnySelect,
    keys: Sequence[SortKey],
    tag: str,
    row_fn: Callable[[AnyRow], list[Any]],
) -> StreamingResponse:
    async def generate() -> AsyncIterator[str]:
        buf = io.StringIO()
        csv.writer(buf).writerow(header)
        yield buf.getvalue()
        cursor: str | None = None
        async with get_sessionmaker()() as session:
            while True:
                rows, cursor = await paginate(session, stmt, keys, PageParams(_CSV_CHUNK, cursor), tag)
                buf = io.StringIO()
                writer = csv.writer(buf)
                for row in rows:
                    writer.writerow([_cell(v) for v in row_fn(row)])
                yield buf.getvalue()
                if cursor is None:
                    break

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}-{stamp}.csv"'},
    )


_SERVER_CSV = [
    "id", "name", "site", "room", "rack", "position_u", "height_u", "vendor", "model", "serial", "asset_tag",
    "bmc_host", "status", "health", "collector", "open_alerts", "last_seen_at",
]  # fmt: skip


def _server_csv_row(row: AnyRow) -> list[Any]:
    item = queries.server_item_from_row(row)
    return [
        item.id, item.name, item.site.code, item.room.name if item.room else None,
        item.rack.name if item.rack else None, item.position_u, item.height_u, item.vendor, item.model,
        item.serial, item.asset_tag, item.bmc_host, item.status, item.health.value, item.collector_name,
        item.open_alerts, item.last_seen_at,
    ]  # fmt: skip


_COMPONENT_CSV = [
    "server_id", "server_name", "site", "type", "name", "model", "manufacturer", "serial", "capacity",
    "capacity_unit", "firmware_version", "location", "first_seen_at", "last_seen_at", "removed_at",
]  # fmt: skip


def _component_csv_row(row: AnyRow) -> list[Any]:
    c = queries.component_item_from_row(row)
    return [
        c.server_id, c.server_name, c.site_code, c.type, c.name, c.model, c.manufacturer, c.serial,
        c.capacity, c.capacity_unit, c.firmware_version, c.location, c.first_seen_at, c.last_seen_at,
        c.removed_at,
    ]  # fmt: skip


_CSV_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"content": {"text/csv": {}}, "description": "CSV file"}
}


@router.get(
    "/servers/export.csv",
    response_class=StreamingResponse,
    responses=_CSV_RESPONSES,
    summary="Server inventory as CSV (same filters as the list, streamed, site scoped)",
)
async def export_servers(
    principal: ViewerUser, filters: ServerFiltersDep, sort: SortDep = "name"
) -> StreamingResponse:
    stmt, keys = queries.server_list_select(principal, filters, sort)
    return _csv_response("servers", _SERVER_CSV, stmt, keys, f"servers:{sort}", _server_csv_row)


@router.get(
    "/components/export.csv",
    response_class=StreamingResponse,
    responses=_CSV_RESPONSES,
    summary="Parts inventory as CSV (same filters as the list, streamed, site scoped)",
)
async def export_components(principal: ViewerUser, filters: ComponentFiltersDep) -> StreamingResponse:
    stmt, keys = queries.components_select(principal, filters)
    return _csv_response("components", _COMPONENT_CSV, stmt, keys, "components", _component_csv_row)


# ---------------------------------------------------------------------------------------------- lists


@router.get("/servers", response_model=ServerPage, summary="Server list with filters (Inventory)")
async def list_servers(
    principal: ViewerUser,
    session: SessionDep,
    page: PageDep,
    filters: ServerFiltersDep,
    sort: SortDep = "name",
) -> ServerPage:
    stmt, keys = queries.server_list_select(principal, filters, sort)
    rows, next_cursor = await paginate(session, stmt, keys, page, f"servers:{sort}")
    return ServerPage(items=[queries.server_item_from_row(r) for r in rows], next_cursor=next_cursor)


@router.get("/components", response_model=ComponentPage, summary="Parts inventory (CPUs, DIMMs, drives, …)")
async def list_components(
    principal: ViewerUser, session: SessionDep, page: PageDep, filters: ComponentFiltersDep
) -> ComponentPage:
    stmt, keys = queries.components_select(principal, filters)
    rows, next_cursor = await paginate(session, stmt, keys, page, "components")
    return ComponentPage(items=[queries.component_item_from_row(r) for r in rows], next_cursor=next_cursor)


# --------------------------------------------------------------------------------------------- detail


@router.get("/servers/{server_id}", response_model=ServerDetail, summary="Server detail")
async def get_server(server_id: int, principal: ViewerUser, session: SessionDep) -> ServerDetail:
    return await queries.server_detail(session, principal, server_id)


@router.get(
    "/servers/{server_id}/readings",
    response_model=ReadingsOut,
    summary="History of one metric (raw, 5-minute or hourly data chosen by range; ≤ ~1500 points)",
)
async def server_readings(
    server_id: int,
    principal: ViewerUser,
    session: SessionDep,
    metric: Annotated[str, Query(max_length=48, description="Metric code, e.g. inlet_temp_c")],
    component: Annotated[str | None, Query(max_length=128, description="One part; default all")] = None,
    start: Annotated[datetime | None, Query(alias="from", description="Default: 24 h before `to`")] = None,
    end: Annotated[datetime | None, Query(alias="to", description="Default: now")] = None,
    step: Annotated[int | None, Query(ge=1, le=14 * 86400, description="Minimum seconds per point")] = None,
) -> ReadingsOut:
    await queries.get_visible_server(session, principal, server_id)
    info = await metric_or_422(session, metric)
    return await reading_history(session, server_id, info, component, start, end, step)


@router.get("/servers/{server_id}/events", response_model=EventPage, summary="System event log entries")
async def server_events(
    server_id: int,
    principal: ViewerUser,
    session: SessionDep,
    page: PageDep,
    severity: Annotated[str | None, Query(pattern="^(OK|Warning|Critical)$")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> EventPage:
    await queries.get_visible_server(session, principal, server_id)
    stmt, keys = queries.events_select(server_id, severity, q)
    rows, next_cursor = await paginate(session, stmt, keys, page, "events")
    return EventPage(items=[EventOut.model_validate(r[0]) for r in rows], next_cursor=next_cursor)


# ------------------------------------------------------------------------------------ onboarding/edit


async def _rack_and_site(session: SessionDep, principal: Principal, rack_id: int) -> tuple[Rack, int]:
    row = (
        await session.execute(
            select(Rack, Room.site_id).join(Room, Room.id == Rack.room_id).where(Rack.id == rack_id)
        )
    ).first()
    if row is None or not principal.can_see_site(row[1]):
        raise Problem(
            422,
            "Unknown rack.",
            errors=[{"loc": ["body", "rack_id"], "msg": "rack not found", "type": "value_error"}],
        )
    return row[0], int(row[1])


async def _check_position(
    session: SessionDep, rack: Rack, position_u: int, height_u: int, exclude_id: int | None
) -> None:
    top = position_u + height_u - 1
    if top > rack.height_u:
        raise Problem(
            422,
            f"U{position_u}-U{top} does not fit in rack {rack.name} ({rack.height_u}U).",
            errors=[{"loc": ["body", "position_u"], "msg": "outside the rack", "type": "value_error"}],
        )
    stmt = select(Server).where(
        Server.rack_id == rack.id,
        Server.status != ServerStatus.DECOMMISSIONED.value,
        Server.position_u.is_not(None),
        Server.position_u <= top,
        Server.position_u + Server.height_u - 1 >= position_u,
    )
    if exclude_id is not None:
        stmt = stmt.where(Server.id != exclude_id)
    clash = (await session.execute(stmt.limit(1))).scalar_one_or_none()
    if clash is not None:
        raise Problem(
            409,
            f"U{position_u}-U{top} overlaps {clash.name or clash.bmc_host} at U{clash.position_u} "
            f"({clash.height_u}U) in rack {rack.name}.",
            conflict_server_id=clash.id,
        )


async def _collector_for(session: SessionDep, site_id: int, collector_id: int | None) -> int | None:
    if collector_id is not None:
        collector = await session.get(Collector, collector_id)
        if collector is None or collector.site_id != site_id:
            raise Problem(
                422,
                "The collector must exist and belong to the server's site.",
                errors=[
                    {
                        "loc": ["body", "collector_id"],
                        "msg": "wrong or unknown collector",
                        "type": "value_error",
                    }
                ],
            )
        return collector.id
    # Least-loaded enabled collector at the site; the ingest side rebalances on failover (D9).
    load = (
        select(Server.collector_id, func.count().label("n"))
        .where(Server.status != ServerStatus.DECOMMISSIONED.value)
        .group_by(Server.collector_id)
        .subquery()
    )
    row = (
        await session.execute(
            select(Collector.id)
            .outerjoin(load, load.c.collector_id == Collector.id)
            .where(Collector.site_id == site_id, Collector.enabled.is_(True))
            .order_by(func.coalesce(load.c.n, 0), Collector.name)
            .limit(1)
        )
    ).first()
    return int(row[0]) if row else None


@router.post(
    "/servers",
    response_model=ServerDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Onboard a server (BMC address, rack, position, collector)",
)
async def onboard_server(
    body: ServerCreate, principal: EngineerUser, session: SessionDep, request: Request
) -> ServerDetail:
    existing = (
        await session.execute(select(Server).where(Server.bmc_host == body.bmc_host))
    ).scalar_one_or_none()
    if existing is not None:
        hint = (
            " (decommissioned; change its status to bring it back)"
            if existing.status == "decommissioned"
            else ""
        )
        raise Problem(
            409,
            f"A server with BMC address {body.bmc_host} is already onboarded{hint}.",
            server_id=existing.id,
        )
    rack, site_id = await _rack_and_site(session, principal, body.rack_id)
    await _check_position(session, rack, body.position_u, body.height_u, None)
    server = Server(
        site_id=site_id,
        rack_id=rack.id,
        position_u=body.position_u,
        height_u=body.height_u,
        bmc_host=body.bmc_host,
        collector_id=await _collector_for(session, site_id, body.collector_id),
        name=body.name,
        asset_tag=body.asset_tag,
        notes=body.notes,
        status=body.status,
    )
    session.add(server)
    await flush_or_409(session, f"A server with BMC address {body.bmc_host} is already onboarded.")
    audit.record(
        session,
        principal=principal,
        action="server.create",
        object_type="server",
        object_id=server.id,
        after=audit.snapshot(server),
        request=request,
    )
    await session.commit()
    return await queries.server_detail(session, principal, server.id)


@router.patch("/servers/{server_id}", response_model=ServerDetail, summary="Move or edit a server")
async def update_server(
    server_id: int, body: ServerUpdate, principal: EngineerUser, session: SessionDep, request: Request
) -> ServerDetail:
    server = await queries.get_visible_server(session, principal, server_id)
    before = audit.snapshot(server)
    fields = body.model_fields_set
    if "status" in fields and body.status is None:
        raise Problem(422, "status cannot be null.")
    if "height_u" in fields and body.height_u is None:
        raise Problem(422, "height_u cannot be null.")

    rack_id = body.rack_id if "rack_id" in fields else server.rack_id
    position = body.position_u if "position_u" in fields else server.position_u
    height = body.height_u if body.height_u is not None else server.height_u
    new_status = body.status.value if body.status is not None else server.status
    if rack_id is None:
        server.rack_id = None
        server.position_u = None
    else:
        rack, site_id = await _rack_and_site(session, principal, rack_id)
        if position is None:
            raise Problem(
                422,
                "A racked server needs a position.",
                errors=[
                    {"loc": ["body", "position_u"], "msg": "required with a rack", "type": "value_error"}
                ],
            )
        if new_status != ServerStatus.DECOMMISSIONED.value:
            await _check_position(session, rack, position, height, server.id)
        if site_id != server.site_id:
            server.site_id = site_id
            if "collector_id" not in fields:
                server.collector_id = await _collector_for(session, site_id, None)
        server.rack_id = rack.id
        server.position_u = position
    server.height_u = height
    server.status = new_status
    if "collector_id" in fields:
        server.collector_id = (
            await _collector_for(session, server.site_id, body.collector_id)
            if body.collector_id is not None
            else None
        )
    for key in ("name", "asset_tag", "notes"):
        if key in fields:
            setattr(server, key, getattr(body, key))
    await flush_or_409(session, "The change conflicts with another server.")
    b, a = audit.changed(before, audit.snapshot(server))
    action = (
        "server.decommission" if a.get("status") == ServerStatus.DECOMMISSIONED.value else "server.update"
    )
    audit.record(
        session,
        principal=principal,
        action=action,
        object_type="server",
        object_id=server.id,
        before=b,
        after=a,
        request=request,
    )
    await session.commit()
    return await queries.server_detail(session, principal, server.id)


@router.delete(
    "/servers/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Decommission a server (kept for history; no longer polled or listed by default)",
)
async def decommission_server(
    server_id: int, principal: EngineerUser, session: SessionDep, request: Request
) -> Response:
    server = await queries.get_visible_server(session, principal, server_id)
    if server.status == ServerStatus.DECOMMISSIONED.value:
        raise Problem(409, "The server is already decommissioned.")
    before = {"status": server.status, "rack_id": server.rack_id, "position_u": server.position_u}
    server.status = ServerStatus.DECOMMISSIONED.value
    audit.record(
        session,
        principal=principal,
        action="server.decommission",
        object_type="server",
        object_id=server.id,
        before=before,
        after={"status": server.status},
        request=request,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
