"""Weekly summary email to `REPORT_RECIPIENTS`: alert volume, response times and what is open right now."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings


@dataclass
class WeeklySummary:
    start: datetime
    end: datetime
    by_site: list[tuple[str, str, int]] = field(default_factory=list)  # site, severity, count
    top_rules: list[tuple[str, int]] = field(default_factory=list)
    open_now: int = 0
    critical_open: int = 0
    mtta_min: float | None = None
    mttr_min: float | None = None
    unhealthy_servers: int = 0
    off_baseline_servers: int = 0


async def build_summary(session: AsyncSession, now: datetime) -> WeeklySummary:
    start = now - timedelta(days=7)
    params = {"start": start, "end": now}
    s = WeeklySummary(start=start, end=now)
    s.by_site = [
        (r[0], r[1], int(r[2]))
        for r in await session.execute(
            text(
                "SELECT COALESCE(st.code, '—'), a.severity, count(*) FROM alerts a "
                "LEFT JOIN sites st ON st.id = a.site_id WHERE a.opened_at >= :start AND a.opened_at < :end "
                "GROUP BY 1, 2 ORDER BY 1, 2"
            ),
            params,
        )
    ]
    s.top_rules = [
        (r[0], int(r[1]))
        for r in await session.execute(
            text(
                "SELECT ar.name, count(*) FROM alerts a JOIN alert_rules ar ON ar.id = a.rule_id "
                "WHERE a.opened_at >= :start AND a.opened_at < :end GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5"
            ),
            params,
        )
    ]
    row = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE state <> 'resolved'),"
                " count(*) FILTER (WHERE state <> 'resolved' AND severity = 'Critical'),"
                " avg(EXTRACT(EPOCH FROM acked_at - opened_at)) FILTER (WHERE opened_at >= :start) / 60,"
                " avg(EXTRACT(EPOCH FROM resolved_at - opened_at)) FILTER (WHERE resolved_at >= :start) / 60"
                " FROM alerts"
            ),
            params,
        )
    ).one()
    s.open_now, s.critical_open = int(row[0]), int(row[1])
    s.mtta_min = float(row[2]) if row[2] is not None else None
    s.mttr_min = float(row[3]) if row[3] is not None else None
    s.unhealthy_servers = int(
        (
            await session.execute(
                text(
                    "SELECT count(DISTINCT server_id) FROM health_status "
                    "WHERE health IN ('Warning', 'Critical')"
                )
            )
        ).scalar_one()
    )
    s.off_baseline_servers = int(
        (
            await session.execute(
                text(
                    "SELECT count(DISTINCT f.server_id) FROM firmware_inventory f "
                    "JOIN servers sv ON sv.id = f.server_id "
                    "JOIN firmware_baselines b ON b.vendor = sv.vendor AND b.model = sv.model "
                    "AND b.component = f.component_key WHERE b.version <> f.version"
                )
            )
        ).scalar_one()
    )
    return s


def _minutes(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f} min"


def render_summary(s: WeeklySummary, settings: Settings, recipients: list[str]) -> EmailMessage:
    period = f"{s.start:%d %b} to {s.end:%d %b %Y}"
    lines = [
        f"Jade GCC weekly summary, {period}",
        "",
        f"Open alerts now: {s.open_now} ({s.critical_open} Critical)",
        f"Mean time to acknowledge: {_minutes(s.mtta_min)}; mean time to resolve: {_minutes(s.mttr_min)}",
        f"Servers not healthy now: {s.unhealthy_servers}; "
        f"servers off firmware baseline: {s.off_baseline_servers}",
        "",
        "Alerts opened by site and severity:",
        *(f"  {site} {sev}: {n}" for site, sev, n in s.by_site),
        "" if s.by_site else "  none",
        "Most frequent rules:",
        *(f"  {name}: {n}" for name, n in s.top_rules),
        "",
        f"Dashboards: {settings.public_app_url.rstrip('/')}/analytics",
    ]
    msg = EmailMessage()
    msg["Subject"] = f"[GCC] Weekly summary {period}"
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(recipients)
    msg.set_content("\n".join(lines))
    body = "<br>".join(html.escape(line).replace("  ", "&nbsp;&nbsp;") for line in lines)
    msg.add_alternative(
        f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px">{body}</div>', subtype="html"
    )
    return msg
