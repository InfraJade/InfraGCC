"""In-process cache of metric definitions (reference data written by migration 0004)."""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MetricDefinition

_TTL_S = 300.0


@dataclass(frozen=True)
class Metric:
    id: int
    code: str
    type: str
    interval_s: int


class MetricCatalog:
    def __init__(self, metrics: list[Metric]) -> None:
        self.by_code = {m.code: m for m in metrics}
        self.by_id = {m.id: m for m in metrics}

    def get(self, code: str) -> Metric | None:
        return self.by_code.get(code)


_cache: tuple[float, MetricCatalog] | None = None


async def load_catalog(session: AsyncSession) -> MetricCatalog:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _TTL_S:
        return _cache[1]
    rows = await session.execute(select(MetricDefinition))
    catalog = MetricCatalog([Metric(m.id, m.code, m.type, m.interval_s) for m in rows.scalars()])
    _cache = (now, catalog)
    return catalog


def clear_catalog_cache() -> None:
    global _cache
    _cache = None
