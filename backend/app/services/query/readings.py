"""Reading history for charts, choosing raw readings or a rollup by the requested range.

At most ~1500 points per series. The step is the larger of the caller's `step` and range / 1500, rounded
up to a round interval. Then:

- raw `readings` for ranges up to 26 hours (bucketed if the step is above the metric's poll interval),
- `readings_5m` for ranges up to 8 days (13-month retention),
- `readings_1h` beyond that (3-year retention),

re-bucketing a rollup with `time_bucket` when the step is coarser than its grain. Long-range charts never
read raw data, as the design asks.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Float, Integer, Text, column, func, select, table
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import AnySelect
from app.core.problems import Problem
from app.models import readings
from app.schemas.servers import ReadingPoint, ReadingSeries, ReadingsOut
from app.services.query.common import MetricInfo, now_utc

MAX_POINTS = 1500
RAW_MAX_SPAN = timedelta(hours=26)
RAW_RETENTION = timedelta(days=30)
ROLLUP_5M_RETENTION = timedelta(days=395)
ROLLUP_5M_MAX_SPAN = timedelta(days=8)
MAX_SPAN = timedelta(days=1100)
NICE_STEPS = [
    60,
    120,
    300,
    600,
    900,
    1800,
    3600,
    7200,
    10800,
    21600,
    43200,
    86400,
    2 * 86400,
    7 * 86400,
    14 * 86400,
]

Resolution = Literal["raw", "5m", "1h"]


def _rollup(name: str) -> Any:
    return table(
        name,
        column("bucket", TIMESTAMP(timezone=True)),
        column("server_id", Integer),
        column("metric_code", Integer),
        column("component", Text),
        column("avg_value", Float),
        column("min_value", Float),
        column("max_value", Float),
        column("samples", Integer),
    )


readings_5m = _rollup("readings_5m")
readings_1h = _rollup("readings_1h")


def _nice(seconds: float) -> int:
    for step in NICE_STEPS:
        if step >= seconds:
            return step
    return int(math.ceil(seconds / 86400) * 86400)


def choose_resolution(
    start: datetime, end: datetime, interval_s: int, step: int | None, now: datetime
) -> tuple[Resolution, int, bool]:
    """(source, step seconds, bucketed?) for a range."""
    span = (end - start).total_seconds()
    want = max(step or 0, math.ceil(span / MAX_POINTS))
    raw_ok = end - start <= RAW_MAX_SPAN and start >= now - RAW_RETENTION
    if raw_ok and want <= interval_s:
        return "raw", interval_s, False
    if raw_ok and want < 300:
        return "raw", _nice(want), True
    if want < 3600 and end - start <= ROLLUP_5M_MAX_SPAN and start >= now - ROLLUP_5M_RETENTION:
        chosen = max(300, _nice(want))
        return "5m", chosen, chosen > 300
    chosen = max(3600, _nice(want))
    return "1h", chosen, chosen > 3600


async def reading_history(
    session: AsyncSession,
    server_id: int,
    metric: MetricInfo,
    component: str | None,
    start: datetime | None,
    end: datetime | None,
    step: int | None,
) -> ReadingsOut:
    now = now_utc()
    end = end or now
    start = start or end - timedelta(hours=24)
    if start.tzinfo is None or end.tzinfo is None:
        raise Problem(422, "`from` and `to` need a UTC offset, e.g. 2026-10-22T10:00:00Z.")
    if end <= start:
        raise Problem(422, "`to` must be after `from`.")
    if end - start > MAX_SPAN:
        raise Problem(422, "The range can be at most 3 years.")
    resolution, step_s, bucketed = choose_resolution(start, end, metric.interval_s, step, now)
    series: dict[str, list[ReadingPoint]] = defaultdict(list)
    stmt: AnySelect

    if resolution == "raw" and not bucketed:
        stmt = select(readings.c.component, readings.c.time, readings.c.value).where(
            readings.c.server_id == server_id,
            readings.c.metric_code == metric.id,
            readings.c.time >= start,
            readings.c.time < end,
        )
        if component is not None:
            stmt = stmt.where(readings.c.component == component)
        for comp, t, v in (await session.execute(stmt.order_by(readings.c.component, readings.c.time))).all():
            series[comp].append(ReadingPoint(t=t, v=v, min=v, max=v))
    elif resolution == "raw":
        bucket = func.time_bucket(timedelta(seconds=step_s), readings.c.time).label("b")
        stmt = (
            select(
                readings.c.component,
                bucket,
                func.avg(readings.c.value),
                func.min(readings.c.value),
                func.max(readings.c.value),
            )
            .where(
                readings.c.server_id == server_id,
                readings.c.metric_code == metric.id,
                readings.c.time >= start,
                readings.c.time < end,
            )
            .group_by(readings.c.component, bucket)
        )
        if component is not None:
            stmt = stmt.where(readings.c.component == component)
        for comp, t, v, lo, hi in (await session.execute(stmt.order_by(readings.c.component, bucket))).all():
            series[comp].append(ReadingPoint(t=t, v=v, min=lo, max=hi))
    else:
        src = readings_5m if resolution == "5m" else readings_1h
        where = [
            src.c.server_id == server_id,
            src.c.metric_code == metric.id,
            src.c.bucket >= start,
            src.c.bucket < end,
        ]
        if component is not None:
            where.append(src.c.component == component)
        if bucketed:
            bucket = func.time_bucket(timedelta(seconds=step_s), src.c.bucket).label("b")
            weighted = func.sum(src.c.avg_value * src.c.samples) / func.nullif(func.sum(src.c.samples), 0)
            stmt = (
                select(
                    src.c.component, bucket, weighted, func.min(src.c.min_value), func.max(src.c.max_value)
                )
                .where(*where)
                .group_by(src.c.component, bucket)
                .order_by(src.c.component, bucket)
            )
        else:
            stmt = (
                select(src.c.component, src.c.bucket, src.c.avg_value, src.c.min_value, src.c.max_value)
                .where(*where)
                .order_by(src.c.component, src.c.bucket)
            )
        for comp, t, v, lo, hi in (await session.execute(stmt)).all():
            series[comp].append(ReadingPoint(t=t, v=v, min=lo, max=hi))

    return ReadingsOut(
        server_id=server_id,
        metric=metric.code,
        metric_name=metric.name,
        unit=metric.unit,
        type=metric.type,
        start=start,
        end=end,
        resolution=resolution,
        step_s=step_s,
        series=[ReadingSeries(component=c, points=series[c]) for c in sorted(series)],
    )
