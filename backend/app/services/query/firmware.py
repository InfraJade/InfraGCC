"""Firmware compliance: installed firmware against the approved baseline per vendor + model."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, distinct, exists, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ServerStatus
from app.core.pagination import AnySelect, PageParams, SortKey, paginate
from app.core.security import Principal
from app.models import FirmwareBaseline, FirmwareInventory, Rack, Server, Site
from app.schemas.admin import ComplianceDiff, ComplianceOut, ComplianceServer, ComplianceSummary


@dataclass(frozen=True)
class ComplianceFilters:
    site_id: int | None = None
    vendor: str | None = None
    model: str | None = None
    component: str | None = None


def _baseline_join() -> ColumnElement[bool]:
    return and_(
        FirmwareBaseline.vendor == Server.vendor,
        FirmwareBaseline.model == Server.model,
        FirmwareBaseline.component == FirmwareInventory.component_key,
    )


def _scoped(principal: Principal, f: ComplianceFilters, stmt: AnySelect) -> AnySelect:
    stmt = stmt.where(
        principal.site_filter(Server.site_id), Server.status != ServerStatus.DECOMMISSIONED.value
    )
    if f.site_id is not None:
        stmt = stmt.where(Server.site_id == f.site_id)
    if f.vendor:
        stmt = stmt.where(Server.vendor == f.vendor)
    if f.model:
        stmt = stmt.where(Server.model == f.model)
    if f.component:
        stmt = stmt.where(FirmwareInventory.component_key == f.component)
    return stmt


_DIFF = FirmwareBaseline.version != FirmwareInventory.version


async def compliance(
    session: AsyncSession, principal: Principal, f: ComplianceFilters, page: PageParams
) -> ComplianceOut:
    joined = (
        select(FirmwareInventory.server_id)
        .join(Server, Server.id == FirmwareInventory.server_id)
        .outerjoin(FirmwareBaseline, _baseline_join())
    )
    counts = (
        await session.execute(
            _scoped(
                principal,
                f,
                joined.with_only_columns(
                    func.count(distinct(FirmwareInventory.server_id)),
                    func.count(distinct(FirmwareInventory.server_id)).filter(
                        FirmwareBaseline.id.is_not(None)
                    ),
                    func.count(distinct(FirmwareInventory.server_id)).filter(_DIFF),
                    func.count().filter(_DIFF),
                ),
            )
        )
    ).one()
    no_baseline = (
        await session.execute(
            _scoped(
                principal,
                f,
                select(func.count(distinct(tuple_(Server.vendor, Server.model))))
                .select_from(FirmwareInventory)
                .join(Server, Server.id == FirmwareInventory.server_id)
                .where(
                    ~exists().where(
                        FirmwareBaseline.vendor == Server.vendor, FirmwareBaseline.model == Server.model
                    )
                ),
            )
        )
    ).scalar_one()
    with_fw, checked, off, components_off = counts
    summary = ComplianceSummary(
        servers_with_firmware=with_fw,
        servers_checked=checked,
        servers_compliant=checked - off,
        servers_off_baseline=off,
        components_off_baseline=components_off,
        models_without_baseline=no_baseline,
    )

    off_servers = _scoped(principal, f, joined.where(_DIFF)).distinct()
    stmt = (
        select(Server, Site.code, Rack.name)
        .join(Site, Site.id == Server.site_id)
        .outerjoin(Rack, Rack.id == Server.rack_id)
        .where(Server.id.in_(off_servers))
    )
    rows, next_cursor = await paginate(
        session, stmt, [SortKey(Site.code), SortKey(Server.id)], page, "fw-compliance"
    )
    ids = [r[0].id for r in rows]
    diffs: dict[int, list[ComplianceDiff]] = defaultdict(list)
    if ids:
        diff_rows = await session.execute(
            _scoped(
                principal,
                f,
                select(FirmwareInventory, FirmwareBaseline.version)
                .join(Server, Server.id == FirmwareInventory.server_id)
                .join(FirmwareBaseline, _baseline_join())
                .where(FirmwareInventory.server_id.in_(ids), _DIFF)
                .order_by(
                    FirmwareInventory.server_id, FirmwareInventory.component_type, FirmwareInventory.component
                ),
            )
        )
        for fw, approved in diff_rows.all():
            diffs[fw.server_id].append(
                ComplianceDiff(
                    component=fw.component,
                    component_key=fw.component_key,
                    component_type=fw.component_type,
                    installed_version=fw.version,
                    approved_version=approved,
                    collected_at=fw.collected_at,
                )
            )
    items = [
        ComplianceServer(
            server_id=server.id,
            server_name=server.name or server.bmc_host,
            site_id=server.site_id,
            site_code=code,
            rack_name=rack_name,
            vendor=server.vendor,
            model=server.model,
            differences=diffs[server.id],
        )
        for server, code, rack_name, *_ in rows
    ]
    return ComplianceOut(items=items, next_cursor=next_cursor, summary=summary)
