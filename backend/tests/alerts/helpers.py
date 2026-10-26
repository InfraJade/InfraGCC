"""Helpers for alert tests: run the engine as gcc_app and read results with the owner session."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.services.alerts.effects import Effects
from app.services.alerts.evaluate import evaluate_server


async def in_app_tx(
    app_engine: AsyncEngine, fn: Callable[[AsyncSession, Effects], Awaitable[Any]]
) -> tuple[Any, Effects]:
    effects = Effects()
    async with AsyncSession(app_engine, expire_on_commit=False) as s, s.begin():
        result = await fn(s, effects)
    return result, effects


async def evaluate(app_engine: AsyncEngine, server_id: int, now: datetime) -> Effects:
    _, effects = await in_app_tx(app_engine, lambda s, e: evaluate_server(s, server_id, now, e))
    return effects


async def alerts(session: AsyncSession, where: str = "true", **params: Any) -> list[Any]:
    await session.rollback()
    rows = await session.execute(
        text(
            "SELECT a.id, r.name AS rule, a.state, a.severity, a.component, a.muted, a.occurrences, a.value, "
            "a.threshold, a.dedupe_key, a.title, a.message, a.server_id, a.collector_id, a.escalated_at "
            f"FROM alerts a JOIN alert_rules r ON r.id = a.rule_id WHERE {where} ORDER BY a.id"
        ),
        params,
    )
    return list(rows.all())


async def activity(session: AsyncSession, alert_id: int) -> list[str]:
    await session.rollback()
    rows = await session.execute(
        text("SELECT action FROM alert_activity WHERE alert_id = :a ORDER BY id"), {"a": alert_id}
    )
    return [r[0] for r in rows]


def kinds(effects: Effects) -> list[tuple[str, int]]:
    return [(n.kind, n.level) for n in effects.notifications]


def changes(effects: Effects) -> list[str]:
    return [m.change for m in effects.messages]
