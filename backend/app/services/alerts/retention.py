"""Retention cleanup: events, resolved alerts (with their activity) and audit entries older than 3 years.

Readings and rollups are dropped by TimescaleDB retention policies (migrations 0002/0003), not here.
Deletes run in batches so one run never holds long locks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RETENTION = timedelta(days=3 * 365)
BATCH = 5000

_DELETES = {
    "events": "DELETE FROM events WHERE id IN (SELECT id FROM events WHERE time < :cutoff LIMIT :n)",
    "alerts": (
        "DELETE FROM alerts WHERE id IN (SELECT id FROM alerts WHERE state = 'resolved' "
        "AND resolved_at < :cutoff LIMIT :n)"
    ),
    "audit_log": "DELETE FROM audit_log WHERE id IN (SELECT id FROM audit_log WHERE time < :cutoff LIMIT :n)",
}


@dataclass
class RetentionResult:
    events: int = 0
    alerts: int = 0
    audit_log: int = 0


async def cleanup(session: AsyncSession, now: datetime, retention: timedelta = RETENTION) -> RetentionResult:
    cutoff = now - retention
    result = RetentionResult()
    for table, sql in _DELETES.items():
        total = 0
        while True:
            deleted = (await session.execute(text(sql), {"cutoff": cutoff, "n": BATCH})).rowcount  # type: ignore[attr-defined]
            await session.commit()
            total += deleted or 0
            if not deleted or deleted < BATCH:
                break
        setattr(result, table, total)
    return result
