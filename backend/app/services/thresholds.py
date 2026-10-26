"""Effective alert limits per server, metric and part (DECISIONS.md D12).

Precedence: server > site > model > global (admin rows in `thresholds`) > the BMC's own limits
(`bmc_thresholds`). The first matching admin row wins as a whole; admin rows apply to every part of the
metric. Directions:

- `above` / `below`: the value is compared with the warning / critical limits.
- `deviation_pct`: percent away from `nominal` (PSU input voltage); without a nominal, 230 V is assumed for
  readings over 160 V and 120 V otherwise.
- `pct_of_capacity`: percent of the server's power capacity, or of its power cap when that is lower.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Severity, ThresholdDirection, ThresholdScope
from app.models import BmcThreshold, Server, Threshold

BmcMode = Literal["upper", "lower"]

_SCOPE_ORDER = {
    ThresholdScope.SERVER.value: 0,
    ThresholdScope.SITE.value: 1,
    ThresholdScope.MODEL.value: 2,
    ThresholdScope.GLOBAL.value: 3,
}


class Level(IntEnum):
    OK = 0
    WARNING = 1
    CRITICAL = 2

    @property
    def severity(self) -> Severity:
        return Severity.CRITICAL if self is Level.CRITICAL else Severity.WARNING


def infer_nominal_voltage(value: float) -> float:
    return 230.0 if value > 160.0 else 120.0


@dataclass(frozen=True)
class Limit:
    direction: str
    warning: float | None
    critical: float | None
    nominal: float | None = None
    source: str = "global"

    def measure(self, value: float, capacity: float | None = None) -> float | None:
        """The quantity compared with the limits: the value, a deviation or a percentage."""
        if self.direction == ThresholdDirection.DEVIATION_PCT.value:
            nominal = self.nominal or infer_nominal_voltage(value)
            return abs(value - nominal) / nominal * 100.0
        if self.direction == ThresholdDirection.PCT_OF_CAPACITY.value:
            if not capacity or capacity <= 0:
                return None
            return value / capacity * 100.0
        return value

    def level(self, value: float | None, capacity: float | None = None) -> Level | None:
        """None when the value cannot be judged (no value, unknown capacity)."""
        if value is None:
            return None
        measured = self.measure(value, capacity)
        if measured is None:
            return None
        if self.direction == ThresholdDirection.BELOW.value:
            if self.critical is not None and measured < self.critical:
                return Level.CRITICAL
            if self.warning is not None and measured < self.warning:
                return Level.WARNING
            return Level.OK
        if self.critical is not None and measured > self.critical:
            return Level.CRITICAL
        if self.warning is not None and measured > self.warning:
            return Level.WARNING
        return Level.OK

    def limit_for(self, level: Level) -> float | None:
        return self.critical if level is Level.CRITICAL else self.warning


class ThresholdResolver:
    """All limits that can apply to one server, loaded once per evaluation."""

    def __init__(self, server: Server, admin: list[Threshold], bmc: list[BmcThreshold]) -> None:
        self.server = server
        self._admin: dict[int, list[Threshold]] = {}
        for row in sorted(admin, key=lambda t: _SCOPE_ORDER.get(t.scope, 9)):
            if self._applies(row):
                self._admin.setdefault(row.metric_code, []).append(row)
        self._bmc = {(b.metric_code, b.component): b for b in bmc}

    @classmethod
    async def load(cls, session: AsyncSession, server: Server) -> ThresholdResolver:
        admin = (
            await session.execute(
                select(Threshold).where(
                    or_(
                        Threshold.scope == ThresholdScope.GLOBAL.value,
                        Threshold.server_id == server.id,
                        Threshold.site_id == server.site_id,
                        Threshold.model == server.model,
                    )
                )
            )
        ).scalars()
        bmc = (
            await session.execute(select(BmcThreshold).where(BmcThreshold.server_id == server.id))
        ).scalars()
        return cls(server, list(admin), list(bmc))

    def _applies(self, row: Threshold) -> bool:
        s = self.server
        match row.scope:
            case ThresholdScope.SERVER.value:
                return row.server_id == s.id
            case ThresholdScope.SITE.value:
                return row.site_id == s.site_id
            case ThresholdScope.MODEL.value:
                return (
                    s.model is not None
                    and row.model == s.model
                    and (row.vendor is None or row.vendor == s.vendor)
                )
            case ThresholdScope.GLOBAL.value:
                return True
        return False

    def effective(self, metric_id: int, component: str, bmc_mode: BmcMode | None = None) -> Limit | None:
        rows = self._admin.get(metric_id)
        if rows:
            row = rows[0]
            return Limit(row.direction, row.warning, row.critical, row.nominal, row.scope)
        bmc = self._bmc.get((metric_id, component))
        if bmc is None:
            return None
        upper = Limit(ThresholdDirection.ABOVE.value, bmc.upper_warning, bmc.upper_critical, source="bmc")
        lower = Limit(ThresholdDirection.BELOW.value, bmc.lower_warning, bmc.lower_critical, source="bmc")
        has_upper = bmc.upper_warning is not None or bmc.upper_critical is not None
        has_lower = bmc.lower_warning is not None or bmc.lower_critical is not None
        if bmc_mode == "upper":
            return upper if has_upper else None
        if bmc_mode == "lower":
            return lower if has_lower else None
        if has_upper:
            return upper
        return lower if has_lower else None
