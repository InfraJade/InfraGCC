"""Side effects of alert changes, applied only after the database transaction commits.

The engine records what should happen (live `AlertMessage`s, notification jobs) in an `Effects` object;
`flush_effects` publishes and enqueues them. Neither Redis nor the broker being down fails the evaluation:
the alert rows are already committed and every change is in `alert_activity`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from redis.asyncio import Redis

from app.core.live import AlertMessage, publish
from app.models import Alert

log = logging.getLogger("gcc.alerts.effects")

# opened | updated | acknowledged | resolved | escalated (app.core.live.AlertMessage.change)
Change = Literal["opened", "updated", "acknowledged", "resolved", "escalated"]
# What a notification is about.
NotifyKind = Literal["opened", "severity", "resolved", "escalated"]


@dataclass(frozen=True)
class NotifyRequest:
    alert_id: int
    kind: NotifyKind
    level: int = 0


@dataclass
class Effects:
    messages: list[AlertMessage] = field(default_factory=list)
    notifications: list[NotifyRequest] = field(default_factory=list)

    def message(self, alert: Alert, change: Change) -> None:
        self.messages.append(
            AlertMessage(
                alert_id=alert.id,
                server_id=alert.server_id,
                site_id=alert.site_id,
                state=alert.state,
                severity=alert.severity,
                title=alert.title,
                change=change,
            )
        )

    def notify(self, alert: Alert, kind: NotifyKind, level: int = 0) -> None:
        self.notifications.append(NotifyRequest(alert.id, kind, level))

    def extend(self, other: Effects) -> None:
        self.messages.extend(other.messages)
        self.notifications.extend(other.notifications)


NotifySender = Callable[[NotifyRequest], None]


async def flush_effects(effects: Effects, redis: Redis | None, send: NotifySender | None) -> None:
    if redis is not None:
        for msg in effects.messages:
            try:
                await publish(redis, msg)
            except Exception:
                log.warning("could not publish alert %s change to Redis", msg.alert_id, exc_info=True)
                break
    if send is not None:
        for req in effects.notifications:
            try:
                send(req)
            except Exception:
                log.exception("could not enqueue notification for alert %s", req.alert_id)
    effects.messages.clear()
    effects.notifications.clear()
