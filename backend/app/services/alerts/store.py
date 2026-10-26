"""Open, update and resolve alerts with dedupe, activity logging and side effects (D15, D16).

At most one non-resolved alert exists per dedupe key (partial unique index `uq_alerts_active_dedupe`).
Every state, severity and mute change writes an `alert_activity` row and queues an `AlertMessage`; changes
that people should hear about queue a notification unless the alert is muted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertState, Severity
from app.models import Alert, AlertActivity, AlertRule
from app.services.alerts.effects import Effects

SYSTEM = "system"


def server_key(server_id: int, metric_id: int, component: str) -> str:
    return f"srv:{server_id}:m{metric_id}:{component}"[:255]


def nodata_key(server_id: int) -> str:
    return f"srv:{server_id}:nodata"


def collector_key(collector_id: int) -> str:
    return f"col:{collector_id}:heartbeat"


@dataclass
class Firing:
    rule: AlertRule
    key: str
    severity: Severity
    title: str
    message: str
    site_id: int | None
    server_id: int | None = None
    collector_id: int | None = None
    metric_code: int | None = None
    component: str = ""
    value: float | None = None
    threshold: float | None = None
    muted: bool = False
    seen_at: datetime | None = None
    # Event alerts count occurrences themselves; others count distinct bad samples.
    occurrences: int | None = None


class AlertStore:
    def __init__(self, session: AsyncSession, now: datetime, effects: Effects) -> None:
        self.session = session
        self.now = now
        self.effects = effects

    async def active(self, key: str) -> Alert | None:
        return (
            await self.session.execute(
                select(Alert).where(Alert.dedupe_key == key, Alert.state != AlertState.RESOLVED.value)
            )
        ).scalar_one_or_none()

    def _log(
        self,
        alert: Alert,
        action: str,
        *,
        from_state: str | None = None,
        to_state: str | None = None,
        note: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            AlertActivity(
                alert_id=alert.id,
                time=self.now,
                actor=SYSTEM,
                action=action,
                from_state=from_state,
                to_state=to_state,
                note=note,
                details=details or {},
            )
        )

    async def fire(self, f: Firing, existing: Alert | None = None) -> Alert:
        alert = existing if existing is not None else await self.active(f.key)
        if alert is None:
            created = await self._insert(f)
            if created is not None:
                return created
            alert = await self.active(f.key)  # lost a race with another worker
            assert alert is not None
        await self._update(alert, f)
        return alert

    async def _insert(self, f: Firing) -> Alert | None:
        seen = f.seen_at or self.now
        alert = Alert(
            rule_id=f.rule.id,
            server_id=f.server_id,
            collector_id=f.collector_id,
            site_id=f.site_id,
            metric_code=f.metric_code,
            component=f.component,
            dedupe_key=f.key,
            state=AlertState.OPEN.value,
            severity=f.severity.value,
            title=f.title[:255],
            message=f.message,
            value=f.value,
            threshold=f.threshold,
            muted=f.muted,
            occurrences=f.occurrences or 1,
            opened_at=self.now,
            last_seen_at=seen,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(alert)
                await self.session.flush()
        except IntegrityError:
            return None
        self._log(
            alert,
            "opened",
            to_state=AlertState.OPEN.value,
            note=f.message,
            details={
                "severity": f.severity.value,
                "value": f.value,
                "threshold": f.threshold,
                "muted": f.muted,
            },
        )
        self.effects.message(alert, "opened")
        if not f.muted:
            self.effects.notify(alert, "opened")
        return alert

    async def _update(self, alert: Alert, f: Firing) -> None:
        changed = False
        current = Severity(alert.severity)
        if f.severity.rank > current.rank:
            alert.severity = f.severity.value
            self._log(alert, "severity_raised", details={"from": current.value, "to": f.severity.value})
            changed = True
            if not f.muted:
                self.effects.notify(alert, "severity")
        if f.muted != alert.muted:
            alert.muted = f.muted
            self._log(alert, "muted" if f.muted else "unmuted", note="Maintenance window")
            changed = True
            if not f.muted and alert.notified_at is None:
                self.effects.notify(alert, "opened")
        if f.occurrences is not None:
            if f.occurrences != alert.occurrences:
                alert.occurrences = f.occurrences
                changed = True
        elif f.seen_at is not None and f.seen_at > alert.last_seen_at:
            alert.occurrences += 1
            changed = True
        if f.seen_at is not None and f.seen_at > alert.last_seen_at:
            alert.last_seen_at = f.seen_at
        alert.value = f.value
        alert.threshold = f.threshold
        alert.message = f.message
        if changed:
            self.effects.message(alert, "updated")

    async def resolve(self, alert: Alert, note: str) -> None:
        previous = alert.state
        alert.state = AlertState.RESOLVED.value
        alert.resolved_at = self.now
        alert.resolved_by = SYSTEM
        self._log(alert, "resolved", from_state=previous, to_state=AlertState.RESOLVED.value, note=note)
        self.effects.message(alert, "resolved")
        if alert.notified_at is not None and not alert.muted:
            self.effects.notify(alert, "resolved")

    async def escalate(self, alert: Alert, after_s: int) -> None:
        alert.escalated_at = self.now
        self._log(alert, "escalated", note=f"Critical and not acknowledged for {after_s // 60} minutes")
        self.effects.message(alert, "escalated")
        self.effects.notify(alert, "escalated", level=1)
