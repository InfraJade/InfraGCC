"""Enabled alert rules with their metric definitions, and helpers to read rule conditions.

Built-in rule conditions (migration 0004):
- threshold: `{}` or `{"bmc_limits": "upper" | "lower"}`
- state: `{"match": "health", "levels": [...]}` or `{"match": "value", "equals": n}` with optional
  `expected_only`, `outside_maintenance_only`, `consecutive`
- missing_data: `{"target": "server", "polls": n}` or `{"target": "collector", "after_s": n}`
- event: `{"severities": [...]}`
- compliance: `{}`
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RuleType, Severity
from app.models import AlertRule, MetricDefinition


@dataclass(frozen=True)
class LoadedRule:
    rule: AlertRule
    metric: MetricDefinition | None

    @property
    def id(self) -> int:
        return self.rule.id

    @property
    def type(self) -> str:
        return self.rule.rule_type

    @property
    def condition(self) -> dict[str, Any]:
        return self.rule.condition or {}

    @property
    def severity(self) -> Severity:
        return Severity(self.rule.severity)

    def cond_int(self, key: str, default: int = 0) -> int:
        value = self.condition.get(key, default)
        return int(value) if isinstance(value, int | float) else default

    def cond_bool(self, key: str) -> bool:
        return bool(self.condition.get(key, False))


async def load_rules(session: AsyncSession, *types: RuleType) -> list[LoadedRule]:
    query = (
        select(AlertRule, MetricDefinition)
        .outerjoin(MetricDefinition, MetricDefinition.id == AlertRule.metric_code)
        .where(AlertRule.enabled.is_(True))
        .order_by(AlertRule.id)
    )
    if types:
        query = query.where(AlertRule.rule_type.in_([t.value for t in types]))
    rows = await session.execute(query)
    return [LoadedRule(rule, metric) for rule, metric in rows]
