"""Critical escalation (DECISIONS.md D18): a Critical alert still open (not acknowledged) `escalation_after_s`
after it became Critical is sent once to the level-1 routes. Muted alerts never escalate (D16).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertState, Severity
from app.models import Alert, AlertActivity
from app.services.alerts.effects import Effects
from app.services.alerts.store import AlertStore


async def escalate_due(session: AsyncSession, now: datetime, effects: Effects, after_s: int) -> int:
    # When the alert became Critical: its last severity raise to Critical, else when it opened.
    raised = (
        select(func.max(AlertActivity.time))
        .where(
            AlertActivity.alert_id == Alert.id,
            AlertActivity.action == "severity_raised",
            AlertActivity.details["to"].astext == Severity.CRITICAL.value,
        )
        .scalar_subquery()
    )
    critical_since = func.coalesce(raised, Alert.opened_at)
    rows = await session.execute(
        select(Alert)
        .where(
            Alert.state == AlertState.OPEN.value,
            Alert.severity == Severity.CRITICAL.value,
            Alert.muted.is_(False),
            Alert.escalated_at.is_(None),
            critical_since <= now - timedelta(seconds=after_s),
        )
        .with_for_update(skip_locked=True)
    )
    store = AlertStore(session, now, effects)
    count = 0
    for alert in rows.scalars():
        await store.escalate(alert, after_s)
        count += 1
    return count
