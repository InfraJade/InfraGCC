"""Current user, global overview, search and metric definitions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import SessionDep
from app.core.security import CurrentUser, ViewerUser, capabilities
from app.models import MetricDefinition, Site
from app.schemas.admin import MetricOut
from app.schemas.common import SiteRef
from app.schemas.inventory import OverviewOut
from app.schemas.misc import MeOut, SearchOut
from app.services.query import servers as server_queries
from app.services.query import sites as site_queries

router = APIRouter(tags=["general"])


@router.get("/me", response_model=MeOut, summary="The signed-in user, roles, sites and capabilities")
async def me(principal: CurrentUser, session: SessionDep) -> MeOut:
    sites: list[SiteRef] | None = None
    if principal.site_ids is not None:
        rows = await session.execute(
            select(Site).where(Site.id.in_(sorted(principal.site_ids))).order_by(Site.code)
        )
        sites = [SiteRef(id=s.id, code=s.code, name=s.name) for s in rows.scalars()]
    primary = principal.primary_role
    return MeOut(
        sub=principal.sub,
        username=principal.username,
        name=principal.display_name,
        email=principal.email,
        roles=sorted(r.value for r in principal.roles),
        primary_role=primary.value if primary else None,
        site_limited=principal.restricted,
        sites=sites,
        capabilities=capabilities(principal),
        token_expires_at=principal.expires_at,
    )


@router.get(
    "/overview",
    response_model=OverviewOut,
    summary="Global overview / NOC wall: per-site health, open alerts, power draw and data freshness",
)
async def overview(principal: ViewerUser, session: SessionDep) -> OverviewOut:
    return await site_queries.overview(session, principal)


@router.get(
    "/search", response_model=SearchOut, summary="Find servers (name, serial, BMC, asset tag), racks, sites"
)
async def search(
    principal: ViewerUser,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> SearchOut:
    return await server_queries.search(session, principal, q, limit)


@router.get("/metrics", response_model=list[MetricOut], summary="Metric definitions (the 20 parameters)")
async def metrics(principal: ViewerUser, session: SessionDep) -> list[MetricOut]:
    rows = await session.execute(
        select(MetricDefinition).order_by(MetricDefinition.parameter_no, MetricDefinition.id)
    )
    return [MetricOut.model_validate(m) for m in rows.scalars()]
