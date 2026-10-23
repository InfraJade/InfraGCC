"""Effective alert limits for one server, for display (D12: server > site > model > global > BMC).

The alert worker has its own resolver (`app.services.thresholds`); this read-only copy only explains to
people which limit applies to each sensor and where it comes from.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BmcThreshold, LatestReading, Server, Threshold
from app.schemas.admin import BmcLimitOut, EffectiveLimit
from app.services.query.common import metrics_by_id

_PRECEDENCE = {"server": 0, "site": 1, "model": 2, "global": 3}


async def bmc_limits(session: AsyncSession, server_id: int) -> list[BmcLimitOut]:
    metrics = await metrics_by_id(session)
    rows = (
        await session.execute(
            select(BmcThreshold)
            .where(BmcThreshold.server_id == server_id)
            .order_by(BmcThreshold.metric_code, BmcThreshold.component)
        )
    ).scalars()
    return [
        BmcLimitOut(
            metric=metrics[b.metric_code].code,
            component=b.component,
            lower_critical=b.lower_critical,
            lower_warning=b.lower_warning,
            upper_warning=b.upper_warning,
            upper_critical=b.upper_critical,
            updated_at=b.updated_at,
        )
        for b in rows
        if b.metric_code in metrics
    ]


async def effective_limits(session: AsyncSession, server: Server) -> list[EffectiveLimit]:
    """One entry per (metric, component) the server reports or has BMC limits for, gauges only."""
    metrics = await metrics_by_id(session)
    candidates = (
        await session.execute(
            select(Threshold).where(
                or_(
                    Threshold.scope == "global",
                    (Threshold.scope == "site") & (Threshold.site_id == server.site_id),
                    (Threshold.scope == "server") & (Threshold.server_id == server.id),
                    (Threshold.scope == "model")
                    & (Threshold.model == server.model)
                    & (Threshold.vendor.is_(None) | (Threshold.vendor == server.vendor)),
                )
            )
        )
    ).scalars()
    best: dict[int, Threshold] = {}
    for t in candidates:
        current = best.get(t.metric_code)
        if current is None or _PRECEDENCE[t.scope] < _PRECEDENCE[current.scope]:
            best[t.metric_code] = t
    bmc = {
        (b.metric_code, b.component): b
        for b in (
            await session.execute(select(BmcThreshold).where(BmcThreshold.server_id == server.id))
        ).scalars()
    }
    sensors = {
        (r.metric_code, r.component)
        for r in (
            await session.execute(
                select(LatestReading.metric_code, LatestReading.component).where(
                    LatestReading.server_id == server.id
                )
            )
        ).all()
    }
    keys = sorted(
        {k for k in sensors | set(bmc) if k[0] in metrics and metrics[k[0]].type == "gauge"},
        key=lambda k: (k[0], k[1]),
    )
    out: list[EffectiveLimit] = []
    for metric_id, component in keys:
        code = metrics[metric_id].code
        admin = best.get(metric_id)
        limit = bmc.get((metric_id, component))
        if admin is not None:
            out.append(
                EffectiveLimit(
                    metric=code,
                    component=component,
                    source=admin.scope,  # type: ignore[arg-type]
                    threshold_id=admin.id,
                    direction=admin.direction,
                    warning=admin.warning,
                    critical=admin.critical,
                    nominal=admin.nominal,
                )
            )
        elif limit is not None:
            out.append(
                EffectiveLimit(
                    metric=code,
                    component=component,
                    source="bmc",
                    threshold_id=None,
                    direction="above",
                    warning=limit.upper_warning,
                    critical=limit.upper_critical,
                    lower_warning=limit.lower_warning,
                    lower_critical=limit.lower_critical,
                )
            )
    return out
