"""Send one alert notification to every matching route and record a `notified` activity row per send.

Muted alerts are never notified (D16). Stale jobs are dropped: an "opened"/"severity" job for an alert that
has since resolved, or an escalation for an alert someone acknowledged in the meantime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import decrypt
from app.core.enums import AlertState, RouteChannel
from app.models import Alert, AlertActivity
from app.services.notify.messages import build_context, render_email, render_teams
from app.services.notify.routing import select_routes
from app.services.notify.senders import post_teams, send_email, split_recipients

log = logging.getLogger("gcc.notify")


@dataclass(frozen=True)
class SendResult:
    route_id: int
    channel: str
    ok: bool
    error: str | None = None


async def notify_alert(
    session: AsyncSession,
    alert_id: int,
    kind: str,
    level: int,
    settings: Settings,
    now: datetime,
    http: httpx.AsyncClient | None = None,
) -> list[SendResult]:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        return []
    if alert.muted:
        log.info("alert %s is muted; %s notification skipped", alert_id, kind)
        return []
    if kind in ("opened", "severity") and alert.state == AlertState.RESOLVED.value:
        return []
    if kind == "escalated" and alert.state != AlertState.OPEN.value:
        return []
    ctx = await build_context(session, alert, kind, settings.public_app_url)
    routes = await select_routes(
        session, route_key=ctx.route_key, site_id=alert.site_id, severity=alert.severity, level=level
    )
    results: list[SendResult] = []
    for route in routes:
        error: str | None = None
        try:
            target = decrypt(route.target_encrypted)
            if route.channel == RouteChannel.EMAIL.value:
                recipients = split_recipients(target)
                if not recipients:
                    raise ValueError("route has no email recipients")
                await send_email(render_email(ctx, settings.smtp_from, recipients), settings)
            elif route.channel == RouteChannel.TEAMS.value:
                await post_teams(target, render_teams(ctx), http)
            else:
                raise ValueError(f"unknown channel {route.channel!r}")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:500]
            log.warning("notification for alert %s via route %s failed: %s", alert_id, route.id, error)
        ok = error is None
        results.append(SendResult(route.id, route.channel, ok, error))
        session.add(
            AlertActivity(
                alert_id=alert.id,
                time=now,
                actor="system",
                action="notified",
                note=f"{route.channel} via {route.name}" + ("" if ok else " (failed)"),
                details={
                    "kind": kind,
                    "level": level,
                    "route_id": route.id,
                    "route": route.name,
                    "channel": route.channel,
                    "target": route.target_hint,
                    "ok": ok,
                    "error": error,
                },
            )
        )
    if any(r.ok for r in results):
        alert.notified_at = now
    return results
