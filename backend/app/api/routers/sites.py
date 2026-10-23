"""Sites, rooms and racks: views for every role, changes for platform admins (sites, rooms) and DC
engineers (racks)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import delete, func, select

from app.api.deps import PageDep, SessionDep, commit_or_409, flush_or_409
from app.core import audit
from app.core.enums import ServerStatus
from app.core.pagination import AnySelect, SortKey, paginate
from app.core.problems import Problem
from app.core.security import AdminUser, EngineerUser, Principal, ViewerUser, ensure_unrestricted, not_found
from app.models import Collector, Rack, Room, Server, Site
from app.schemas.inventory import (
    RackCreate,
    RackDetail,
    RackOut,
    RackPage,
    RackUpdate,
    RoomCreate,
    RoomOut,
    RoomPage,
    RoomUpdate,
    SiteCreate,
    SiteDetail,
    SiteOut,
    SitePage,
    SiteUpdate,
)
from app.services.query import sites as queries

router = APIRouter(tags=["sites"])

_ACTIVE = Server.status != ServerStatus.DECOMMISSIONED.value


# ---------------------------------------------------------------------------------------------- sites


@router.get("/sites", response_model=SitePage, summary="Sites with server counts and health summary")
async def list_sites(principal: ViewerUser, session: SessionDep, page: PageDep) -> SitePage:
    rows, next_cursor = await paginate(
        session, queries.visible_sites_stmt(principal), [SortKey(Site.code), SortKey(Site.id)], page, "sites"
    )
    return SitePage(
        items=await queries.site_summaries(session, [r[0] for r in rows]), next_cursor=next_cursor
    )


@router.get(
    "/sites/{site_id}", response_model=SiteDetail, summary="Site with rooms → racks colored by worst health"
)
async def get_site(site_id: int, principal: ViewerUser, session: SessionDep) -> SiteDetail:
    return await queries.site_detail(session, principal, site_id)


async def _visible_site(session: SessionDep, principal: Principal, site_id: int) -> Site:
    site = await session.get(Site, site_id)
    if site is None or not principal.can_see_site(site.id):
        raise not_found("Site")
    return site


@router.post("/sites", response_model=SiteOut, status_code=status.HTTP_201_CREATED, summary="Create a site")
async def create_site(
    body: SiteCreate, principal: AdminUser, session: SessionDep, request: Request
) -> SiteOut:
    ensure_unrestricted(principal, "Creating a site")
    site = Site(**body.model_dump())
    session.add(site)
    await flush_or_409(session, f"A site with code {body.code} already exists.")
    audit.record(
        session,
        principal=principal,
        action="site.create",
        object_type="site",
        object_id=site.id,
        after=audit.snapshot(site),
        request=request,
    )
    await session.commit()
    await session.refresh(site)
    return SiteOut.model_validate(site)


@router.patch("/sites/{site_id}", response_model=SiteOut, summary="Update a site")
async def update_site(
    site_id: int, body: SiteUpdate, principal: AdminUser, session: SessionDep, request: Request
) -> SiteOut:
    site = await _visible_site(session, principal, site_id)
    before = audit.snapshot(site)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            raise Problem(422, f"{key} cannot be null.")
        setattr(site, key, value)
    await flush_or_409(session, "The change conflicts with an existing object (duplicate name or code).")
    b, a = audit.changed(before, audit.snapshot(site))
    audit.record(
        session,
        principal=principal,
        action="site.update",
        object_type="site",
        object_id=site.id,
        before=b,
        after=a,
        request=request,
    )
    await commit_or_409(session, "Site update conflicts with another site.")
    await session.refresh(site)
    return SiteOut.model_validate(site)


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an empty site")
async def delete_site(site_id: int, principal: AdminUser, session: SessionDep, request: Request) -> Response:
    ensure_unrestricted(principal, "Deleting a site")
    site = await _visible_site(session, principal, site_id)
    for model, label in ((Room, "rooms"), (Server, "servers"), (Collector, "collectors")):
        n = (
            await session.execute(select(func.count()).select_from(model).where(model.site_id == site.id))
        ).scalar_one()
        if n:
            raise Problem(409, f"The site still has {n} {label}; remove them first.")
    audit.record(
        session,
        principal=principal,
        action="site.delete",
        object_type="site",
        object_id=site.id,
        before=audit.snapshot(site),
        request=request,
    )
    await session.execute(delete(Site).where(Site.id == site.id))
    await commit_or_409(session, "The site is still referenced.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------------------------- rooms


def _rooms_stmt(principal: Principal) -> AnySelect:
    racks = select(Rack.room_id, func.count().label("n")).group_by(Rack.room_id).subquery()
    return (
        select(Room, Site.code, func.coalesce(racks.c.n, 0))
        .join(Site, Site.id == Room.site_id)
        .outerjoin(racks, racks.c.room_id == Room.id)
        .where(principal.site_filter(Room.site_id))
    )


def _room_out(row: Any) -> RoomOut:
    room: Room = row[0]
    return RoomOut(
        id=room.id,
        site_id=room.site_id,
        site_code=row[1],
        name=room.name,
        floor=room.floor,
        rack_count=row[2],
    )


@router.get("/rooms", response_model=RoomPage, summary="Rooms (halls), optionally for one site")
async def list_rooms(
    principal: ViewerUser,
    session: SessionDep,
    page: PageDep,
    site_id: Annotated[int | None, Query()] = None,
) -> RoomPage:
    stmt = _rooms_stmt(principal)
    if site_id is not None:
        stmt = stmt.where(Room.site_id == site_id)
    rows, next_cursor = await paginate(
        session, stmt, [SortKey(Site.code), SortKey(Room.name), SortKey(Room.id)], page, "rooms"
    )
    return RoomPage(items=[_room_out(r) for r in rows], next_cursor=next_cursor)


async def _room_out_by_id(session: SessionDep, principal: Principal, room_id: int) -> RoomOut:
    row = (await session.execute(_rooms_stmt(principal).where(Room.id == room_id))).first()
    if row is None:
        raise not_found("Room")
    return _room_out(row)


@router.get("/rooms/{room_id}", response_model=RoomOut, summary="One room")
async def get_room(room_id: int, principal: ViewerUser, session: SessionDep) -> RoomOut:
    return await _room_out_by_id(session, principal, room_id)


@router.post("/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED, summary="Create a room")
async def create_room(
    body: RoomCreate, principal: AdminUser, session: SessionDep, request: Request
) -> RoomOut:
    await _visible_site(session, principal, body.site_id)
    room = Room(**body.model_dump())
    session.add(room)
    await flush_or_409(session, f"The site already has a room named {body.name}.")
    audit.record(
        session,
        principal=principal,
        action="room.create",
        object_type="room",
        object_id=room.id,
        after=audit.snapshot(room),
        request=request,
    )
    await session.commit()
    return await _room_out_by_id(session, principal, room.id)


async def _visible_room(session: SessionDep, principal: Principal, room_id: int) -> Room:
    room = await session.get(Room, room_id)
    if room is None or not principal.can_see_site(room.site_id):
        raise not_found("Room")
    return room


@router.patch("/rooms/{room_id}", response_model=RoomOut, summary="Rename a room or change its floor")
async def update_room(
    room_id: int, body: RoomUpdate, principal: AdminUser, session: SessionDep, request: Request
) -> RoomOut:
    room = await _visible_room(session, principal, room_id)
    before = audit.snapshot(room)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is None:
        raise Problem(422, "name cannot be null.")
    for key, value in data.items():
        setattr(room, key, value)
    await flush_or_409(session, "The change conflicts with an existing object (duplicate name or code).")
    b, a = audit.changed(before, audit.snapshot(room))
    audit.record(
        session,
        principal=principal,
        action="room.update",
        object_type="room",
        object_id=room.id,
        before=b,
        after=a,
        request=request,
    )
    await commit_or_409(session, "The site already has a room with that name.")
    return await _room_out_by_id(session, principal, room.id)


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an empty room")
async def delete_room(room_id: int, principal: AdminUser, session: SessionDep, request: Request) -> Response:
    room = await _visible_room(session, principal, room_id)
    n = (
        await session.execute(select(func.count()).select_from(Rack).where(Rack.room_id == room.id))
    ).scalar_one()
    if n:
        raise Problem(409, f"The room still has {n} racks; remove them first.")
    audit.record(
        session,
        principal=principal,
        action="room.delete",
        object_type="room",
        object_id=room.id,
        before=audit.snapshot(room),
        request=request,
    )
    await session.execute(delete(Room).where(Room.id == room.id))
    await commit_or_409(session, "The room is still referenced.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------------------------- racks


def _racks_stmt(principal: Principal) -> AnySelect:
    servers = (
        select(Server.rack_id, func.count().label("n"), func.sum(Server.height_u).label("u"))
        .where(_ACTIVE, Server.rack_id.is_not(None))
        .group_by(Server.rack_id)
        .subquery()
    )
    return (
        select(
            Rack, Room.name, Site.id, Site.code, func.coalesce(servers.c.n, 0), func.coalesce(servers.c.u, 0)
        )
        .join(Room, Room.id == Rack.room_id)
        .join(Site, Site.id == Room.site_id)
        .outerjoin(servers, servers.c.rack_id == Rack.id)
        .where(principal.site_filter(Site.id))
    )


def _rack_out(row: Any) -> RackOut:
    rack: Rack = row[0]
    return RackOut(
        id=rack.id,
        room_id=rack.room_id,
        room_name=row[1],
        site_id=row[2],
        site_code=row[3],
        name=rack.name,
        row=rack.row,
        height_u=rack.height_u,
        power_capacity_w=rack.power_capacity_w,
        server_count=int(row[4]),
        used_u=int(row[5]),
    )


@router.get("/racks", response_model=RackPage, summary="Racks, optionally for one site or room")
async def list_racks(
    principal: ViewerUser,
    session: SessionDep,
    page: PageDep,
    site_id: Annotated[int | None, Query()] = None,
    room_id: Annotated[int | None, Query()] = None,
) -> RackPage:
    stmt = _racks_stmt(principal)
    if site_id is not None:
        stmt = stmt.where(Site.id == site_id)
    if room_id is not None:
        stmt = stmt.where(Rack.room_id == room_id)
    rows, next_cursor = await paginate(
        session, stmt, [SortKey(Site.code), SortKey(Rack.name), SortKey(Rack.id)], page, "racks"
    )
    return RackPage(items=[_rack_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/racks/{rack_id}", response_model=RackDetail, summary="Rack with servers in position order")
async def get_rack(rack_id: int, principal: ViewerUser, session: SessionDep) -> RackDetail:
    return await queries.rack_detail(session, principal, rack_id)


async def _rack_out_by_id(session: SessionDep, principal: Principal, rack_id: int) -> RackOut:
    row = (await session.execute(_racks_stmt(principal).where(Rack.id == rack_id))).first()
    if row is None:
        raise not_found("Rack")
    return _rack_out(row)


@router.post("/racks", response_model=RackOut, status_code=status.HTTP_201_CREATED, summary="Create a rack")
async def create_rack(
    body: RackCreate, principal: EngineerUser, session: SessionDep, request: Request
) -> RackOut:
    await _visible_room(session, principal, body.room_id)
    rack = Rack(**body.model_dump())
    session.add(rack)
    await flush_or_409(session, f"The room already has a rack named {body.name}.")
    audit.record(
        session,
        principal=principal,
        action="rack.create",
        object_type="rack",
        object_id=rack.id,
        after=audit.snapshot(rack),
        request=request,
    )
    await session.commit()
    return await _rack_out_by_id(session, principal, rack.id)


async def _visible_rack(session: SessionDep, principal: Principal, rack_id: int) -> tuple[Rack, Room]:
    row = (
        await session.execute(
            select(Rack, Room).join(Room, Room.id == Rack.room_id).where(Rack.id == rack_id)
        )
    ).first()
    if row is None or not principal.can_see_site(row[1].site_id):
        raise not_found("Rack")
    return row[0], row[1]


@router.patch("/racks/{rack_id}", response_model=RackOut, summary="Update a rack (name, row, height, room)")
async def update_rack(
    rack_id: int, body: RackUpdate, principal: EngineerUser, session: SessionDep, request: Request
) -> RackOut:
    rack, room = await _visible_rack(session, principal, rack_id)
    before = audit.snapshot(rack)
    data = body.model_dump(exclude_unset=True)
    for key in ("room_id", "name", "height_u"):
        if key in data and data[key] is None:
            raise Problem(422, f"{key} cannot be null.")
    if "room_id" in data and data["room_id"] != rack.room_id:
        new_room = await _visible_room(session, principal, data["room_id"])
        if new_room.site_id != room.site_id:
            raise Problem(422, "A rack can only move to another room of the same site.")
    if "height_u" in data:
        top = (
            await session.execute(
                select(func.max(Server.position_u + Server.height_u - 1)).where(
                    Server.rack_id == rack.id, _ACTIVE
                )
            )
        ).scalar_one()
        if top is not None and top > data["height_u"]:
            raise Problem(409, f"Servers occupy the rack up to U{top}; it cannot be shorter than that.")
    for key, value in data.items():
        setattr(rack, key, value)
    await flush_or_409(session, "The change conflicts with an existing object (duplicate name or code).")
    b, a = audit.changed(before, audit.snapshot(rack))
    audit.record(
        session,
        principal=principal,
        action="rack.update",
        object_type="rack",
        object_id=rack.id,
        before=b,
        after=a,
        request=request,
    )
    await commit_or_409(session, "The room already has a rack with that name.")
    return await _rack_out_by_id(session, principal, rack.id)


@router.delete(
    "/racks/{rack_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a rack with no servers"
)
async def delete_rack(
    rack_id: int, principal: EngineerUser, session: SessionDep, request: Request
) -> Response:
    rack, _ = await _visible_rack(session, principal, rack_id)
    n = (
        await session.execute(
            select(func.count()).select_from(Server).where(Server.rack_id == rack.id, _ACTIVE)
        )
    ).scalar_one()
    if n:
        raise Problem(409, f"The rack still holds {n} servers; move or decommission them first.")
    audit.record(
        session,
        principal=principal,
        action="rack.delete",
        object_type="rack",
        object_id=rack.id,
        before=audit.snapshot(rack),
        request=request,
    )
    await session.execute(delete(Rack).where(Rack.id == rack.id))
    await commit_or_409(session, "The rack is still referenced.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
