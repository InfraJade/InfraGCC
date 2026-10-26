"""Which routes an alert goes to (DECISIONS.md D18).

A route matches when it is enabled, its route key is the rule's team key or `*`, its site is the alert's site
or unset (all sites), the alert's severity is at least its minimum severity, and its escalation level is the
level being notified (0 normally, 1 for the 15-minute Critical escalation).
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Severity
from app.models import AlertRoute


def route_matches(
    route: AlertRoute, *, route_key: str, site_id: int | None, severity: str, level: int
) -> bool:
    if not route.enabled or route.escalation_level != level:
        return False
    if route.route not in ("*", route_key):
        return False
    if route.site_id is not None and route.site_id != site_id:
        return False
    return Severity(severity).rank >= Severity(route.min_severity).rank


async def select_routes(
    session: AsyncSession, *, route_key: str, site_id: int | None, severity: str, level: int
) -> list[AlertRoute]:
    rows = await session.execute(
        select(AlertRoute)
        .where(
            AlertRoute.enabled.is_(True),
            AlertRoute.escalation_level == level,
            AlertRoute.route.in_(["*", route_key]),
            or_(AlertRoute.site_id.is_(None), AlertRoute.site_id == site_id),
        )
        .order_by(AlertRoute.id)
    )
    return [
        r
        for r in rows.scalars()
        if route_matches(r, route_key=route_key, site_id=site_id, severity=severity, level=level)
    ]
