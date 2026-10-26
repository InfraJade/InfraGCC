"""Notification content: one `AlertContext`, rendered as an email (plain text + HTML) or a Teams card."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, AlertRule, Collector, MetricDefinition, Rack, Room, Server, Site

_HEADINGS = {
    "opened": "{severity} alert",
    "severity": "Alert raised to {severity}",
    "resolved": "Resolved",
    "escalated": "ESCALATION: Critical alert not acknowledged",
}
_TEAMS_COLOR = {"Critical": "Attention", "Warning": "Warning", "Info": "Accent"}


@dataclass(frozen=True)
class AlertContext:
    alert_id: int
    kind: str
    title: str
    message: str
    severity: str
    state: str
    rule_name: str
    route_key: str
    site_id: int | None
    site: str
    target: str
    location: str
    metric: str
    component: str
    value: str
    opened_at: datetime
    occurrences: int
    muted: bool
    url: str

    @property
    def heading(self) -> str:
        return _HEADINGS.get(self.kind, "{severity} alert").format(severity=self.severity)

    def facts(self) -> list[tuple[str, str]]:
        rows = [
            ("Severity", self.severity),
            ("State", self.state),
            ("Site", self.site),
            ("Server" if self.location or self.target else "Target", self.target),
            ("Location", self.location),
            ("Metric", f"{self.metric} {self.component}".strip()),
            ("Value", self.value),
            ("Rule", self.rule_name),
            ("Opened", self.opened_at.strftime("%Y-%m-%d %H:%M UTC")),
            ("Occurrences", str(self.occurrences)),
        ]
        return [(k, v) for k, v in rows if v]


async def build_context(session: AsyncSession, alert: Alert, kind: str, public_url: str) -> AlertContext:
    rule = await session.get(AlertRule, alert.rule_id)
    assert rule is not None
    site = await session.get(Site, alert.site_id) if alert.site_id is not None else None
    target = location = ""
    if alert.server_id is not None:
        server = await session.get(Server, alert.server_id)
        if server is not None:
            target = server.display_name
            if server.rack_id is not None:
                row = (
                    await session.execute(
                        select(Room.name, Rack.name)
                        .join(Rack, Rack.room_id == Room.id)
                        .where(Rack.id == server.rack_id)
                    )
                ).first()
                if row is not None:
                    location = f"{row[0]} / rack {row[1]}" + (
                        f" / U{server.position_u}" if server.position_u else ""
                    )
    elif alert.collector_id is not None:
        collector = await session.get(Collector, alert.collector_id)
        target = f"collector {collector.name}" if collector else ""
    metric = await session.get(MetricDefinition, alert.metric_code) if alert.metric_code is not None else None
    value = ""
    if alert.value is not None:
        unit = f" {metric.unit}" if metric is not None and metric.unit else ""
        value = f"{alert.value:g}{unit}"
        if alert.threshold is not None:
            value += f" (limit {alert.threshold:g})"
    return AlertContext(
        alert_id=alert.id,
        kind=kind,
        title=alert.title,
        message=alert.message,
        severity=alert.severity,
        state=alert.state,
        rule_name=rule.name,
        route_key=rule.route,
        site_id=alert.site_id,
        site=f"{site.code} ({site.name})" if site else "",
        target=target,
        location=location,
        metric=metric.name if metric else "",
        component=alert.component,
        value=value,
        opened_at=alert.opened_at,
        occurrences=alert.occurrences,
        muted=alert.muted,
        url=f"{public_url.rstrip('/')}/alerts/{alert.id}",
    )


def subject(ctx: AlertContext) -> str:
    tag = {"resolved": "Resolved", "escalated": "ESCALATED", "severity": f"{ctx.severity} ↑"}.get(
        ctx.kind, ctx.severity
    )
    site = ctx.site.split(" ")[0] if ctx.site else ""
    return f"[GCC {tag}] {ctx.title}" + (f" [{site}]" if site else "")


def render_email(ctx: AlertContext, sender: str, recipients: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject(ctx)
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["X-GCC-Alert-Id"] = str(ctx.alert_id)
    facts = ctx.facts()
    plain = "\n".join(
        [
            ctx.heading,
            "",
            ctx.title,
            ctx.message,
            "",
            *(f"{k}: {v}" for k, v in facts),
            "",
            f"Open: {ctx.url}",
        ]
    )
    msg.set_content(plain)
    color = {"Critical": "#c62828", "Warning": "#ef6c00"}.get(ctx.severity, "#1565c0")
    if ctx.kind == "resolved":
        color = "#2e7d32"
    rows = "".join(
        f'<tr><td style="padding:2px 12px 2px 0;color:#555">{html.escape(k)}</td>'
        f"<td>{html.escape(v)}</td></tr>"
        for k, v in facts
    )
    body = (
        '<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px">'
        f'<div style="border-left:4px solid {color};padding-left:12px">'
        f'<div style="color:{color};font-weight:600">{html.escape(ctx.heading)}</div>'
        f'<h2 style="margin:4px 0">{html.escape(ctx.title)}</h2>'
        f"<p>{html.escape(ctx.message)}</p></div>"
        f'<table style="margin:12px 0;border-collapse:collapse">{rows}</table>'
        f'<p><a href="{html.escape(ctx.url)}">Open the alert in Jade GCC</a></p></div>'
    )
    msg.add_alternative(body, subtype="html")
    return msg


def render_teams(ctx: AlertContext) -> dict[str, Any]:
    """An Adaptive Card wrapped as a Teams message (Workflows / incoming webhook format)."""
    color = "Good" if ctx.kind == "resolved" else _TEAMS_COLOR.get(ctx.severity, "Default")
    card: dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "msteams": {"width": "Full"},
        "body": [
            {"type": "TextBlock", "text": ctx.heading, "color": color, "weight": "Bolder", "size": "Small"},
            {"type": "TextBlock", "text": ctx.title, "weight": "Bolder", "size": "Medium", "wrap": True},
            {"type": "TextBlock", "text": ctx.message, "wrap": True},
            {"type": "FactSet", "facts": [{"title": k, "value": v} for k, v in ctx.facts()]},
        ],
        "actions": [{"type": "Action.OpenUrl", "title": "Open alert", "url": ctx.url}],
    }
    return {
        "type": "message",
        "summary": subject(ctx),
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}
        ],
    }
