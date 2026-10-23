"""Building blocks shared by the read queries: health ranks, metric lookups, collector liveness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Subquery, and_, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import AlertState, Health
from app.core.problems import Problem
from app.models import Alert, Collector, HealthStatus, MetricDefinition, Server

# Same order as Health.rank: OK < Unknown < Warning < Critical.
HEALTH_RANK: dict[Health, int] = {Health.OK: 0, Health.UNKNOWN: 1, Health.WARNING: 2, Health.CRITICAL: 3}
RANK_HEALTH: dict[int, Health] = {v: k for k, v in HEALTH_RANK.items()}
UNKNOWN_RANK = HEALTH_RANK[Health.UNKNOWN]

# A server is "reporting" if its newest reading is younger than this.
STALE_AFTER = timedelta(minutes=5)


def health_rank_expr(column: Any) -> ColumnElement[int]:
    return case(
        (column == Health.OK.value, 0),
        (column == Health.UNKNOWN.value, 1),
        (column == Health.WARNING.value, 2),
        else_=3,
    )


def health_from_rank(rank: int | None) -> Health:
    return RANK_HEALTH.get(int(rank), Health.UNKNOWN) if rank is not None else Health.UNKNOWN


def worst_health_subquery() -> Subquery:
    """(server_id, rank): worst health rank across every part of each server."""
    return (
        select(HealthStatus.server_id, func.max(health_rank_expr(HealthStatus.health)).label("rank"))
        .group_by(HealthStatus.server_id)
        .subquery("worst_health")
    )


def server_rank(sq: Subquery) -> ColumnElement[int]:
    """A server's worst health rank; servers without health rows are Unknown."""
    return func.coalesce(sq.c.rank, literal(UNKNOWN_RANK))


def open_alerts_subquery() -> Subquery:
    """(server_id, n): unresolved, unmuted alerts per server."""
    return (
        select(Alert.server_id, func.count().label("n"))
        .where(Alert.state != AlertState.RESOLVED.value, Alert.server_id.is_not(None), Alert.muted.is_(False))
        .group_by(Alert.server_id)
        .subquery("open_alerts")
    )


@dataclass(frozen=True)
class MetricInfo:
    id: int
    code: str
    name: str
    unit: str
    type: str
    category: str
    interval_s: int


_metrics: dict[str, MetricInfo] | None = None


async def metrics_by_code(session: AsyncSession) -> dict[str, MetricInfo]:
    """Metric definitions (reference data from migrations), cached per process."""
    global _metrics
    if _metrics is None:
        rows = (await session.execute(select(MetricDefinition))).scalars()
        _metrics = {
            m.code: MetricInfo(m.id, m.code, m.name, m.unit, m.type, m.category, m.interval_s) for m in rows
        }
    return _metrics


async def metrics_by_id(session: AsyncSession) -> dict[int, MetricInfo]:
    return {m.id: m for m in (await metrics_by_code(session)).values()}


async def metric_or_422(session: AsyncSession, code: str, field: str = "metric") -> MetricInfo:
    info = (await metrics_by_code(session)).get(code)
    if info is None:
        raise Problem(
            422,
            f"Unknown metric {code!r}.",
            errors=[{"loc": ["query", field], "msg": "unknown metric code", "type": "value_error"}],
        )
    return info


def now_utc() -> datetime:
    return datetime.now(UTC)


def collector_online_expr() -> ColumnElement[bool]:
    cutoff = now_utc() - timedelta(seconds=get_settings().collector_offline_after_s)
    return and_(
        Collector.enabled.is_(True),
        Collector.last_heartbeat.is_not(None),
        Collector.last_heartbeat >= cutoff,
    )


def collector_is_online(collector: Collector) -> bool:
    if not collector.enabled or collector.last_heartbeat is None:
        return False
    return collector.last_heartbeat >= now_utc() - timedelta(seconds=get_settings().collector_offline_after_s)


def display_name(server: Server) -> str:
    return server.name or server.bmc_host


def age_s(time: datetime, now: datetime | None = None) -> int:
    return max(0, int(((now or now_utc()) - time).total_seconds()))


def like_pattern(q: str) -> str:
    """ILIKE pattern for a user's search text (wildcards in the text are matched literally)."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
