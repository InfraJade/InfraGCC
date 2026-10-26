"""Notifications: routing (D18), email and Teams payloads, activity rows, muted alerts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import get_settings
from app.core.crypto import encrypt, mask_target
from app.models import AlertRoute
from app.services.notify.routing import route_matches
from app.services.notify.service import notify_alert
from tests.alerts.helpers import alerts, evaluate, in_app_tx
from tests.ingest.fixtures import World, add_readings

pytestmark = pytest.mark.db

TEAMS_URL = "http://teams.test/webhooks/pnq1"


@pytest.fixture
def sent_mail(monkeypatch: pytest.MonkeyPatch) -> list[tuple[EmailMessage, dict[str, Any]]]:
    sent: list[tuple[EmailMessage, dict[str, Any]]] = []

    async def fake_send(message: EmailMessage, **kwargs: Any) -> None:
        sent.append((message, kwargs))

    monkeypatch.setattr("aiosmtplib.send", fake_send)
    return sent


async def _routes(session: AsyncSession, world: World) -> None:
    pnq1, hyd1 = world.sites["PNQ1"].id, world.sites["HYD1"].id
    rows = [
        ("NOC all critical", "*", None, "Critical", 0, "email", "noc@gcc.example, duty@gcc.example"),
        ("Hardware warning+", "hardware", None, "Warning", 0, "email", "hw@gcc.example"),
        ("Facilities", "facilities", None, "Warning", 0, "email", "fac@gcc.example"),
        ("PNQ1 Teams", "*", pnq1, "Warning", 0, "teams", TEAMS_URL),
        ("HYD1 Teams", "*", hyd1, "Warning", 0, "teams", "http://teams.test/webhooks/hyd1"),
        ("Escalation", "*", None, "Critical", 1, "email", "manager@gcc.example"),
    ]
    for name, route, site, sev, level, channel, target in rows:
        session.add(
            AlertRoute(
                name=name,
                route=route,
                site_id=site,
                min_severity=sev,
                escalation_level=level,
                channel=channel,
                target_encrypted=encrypt(target),
                target_hint=mask_target(channel, target),
            )
        )
    await session.commit()


async def _critical_alert(world: World, session: AsyncSession, app_engine: AsyncEngine) -> int:
    now = datetime.now(UTC)
    sid = world.server(0).id
    await add_readings(session, sid, "bmc_reachable", [(120, 0.0), (60, 0.0), (0, 0.0)], now)
    await evaluate(app_engine, sid, now)
    [alert] = await alerts(session)
    return int(alert.id)


def test_route_matching() -> None:
    r = AlertRoute(route="hardware", site_id=1, min_severity="Warning", escalation_level=0, enabled=True)
    assert route_matches(r, route_key="hardware", site_id=1, severity="Critical", level=0)
    assert not route_matches(r, route_key="platform", site_id=1, severity="Critical", level=0)
    assert not route_matches(r, route_key="hardware", site_id=2, severity="Critical", level=0)
    assert not route_matches(r, route_key="hardware", site_id=1, severity="Info", level=0)
    assert not route_matches(r, route_key="hardware", site_id=1, severity="Critical", level=1)
    r.enabled = False
    assert not route_matches(r, route_key="hardware", site_id=1, severity="Critical", level=0)


@respx.mock
async def test_email_and_teams_payloads_and_activity(
    world: World,
    session: AsyncSession,
    app_engine: AsyncEngine,
    sent_mail: list[tuple[EmailMessage, dict[str, Any]]],
) -> None:
    await _routes(session, world)
    alert_id = await _critical_alert(world, session, app_engine)
    teams = respx.post(TEAMS_URL).mock(return_value=httpx.Response(200))
    settings = get_settings()

    results, _ = await in_app_tx(
        app_engine, lambda s, e: notify_alert(s, alert_id, "opened", 0, settings, datetime.now(UTC))
    )
    # "BMC unreachable" routes to `platform`: NOC (*, Critical) + PNQ1 Teams; not hardware/facilities/HYD1/escalation.
    assert sorted((r.channel, r.ok) for r in results) == [("email", True), ("teams", True)]

    [(msg, kwargs)] = sent_mail
    assert msg["To"] == "noc@gcc.example, duty@gcc.example"
    assert msg["Subject"].startswith("[GCC Critical] BMC unreachable: srv-01") and msg["Subject"].endswith(
        "[PNQ1]"
    )
    assert kwargs["hostname"] == settings.smtp_host and kwargs["port"] == settings.smtp_port
    plain = msg.get_body(("plain",))
    html = msg.get_body(("html",))
    assert plain is not None and html is not None
    link = f"{settings.public_app_url.rstrip('/')}/alerts/{alert_id}"
    assert link in plain.get_content() and f'href="{link}"' in html.get_content()
    assert "Location: Hall A / rack A01" in plain.get_content()

    card = json.loads(teams.calls.last.request.content)
    assert card["type"] == "message"
    content = card["attachments"][0]["content"]
    assert card["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert content["type"] == "AdaptiveCard" and content["actions"][0]["url"] == link
    assert content["body"][0]["color"] == "Attention"
    facts = {f["title"]: f["value"] for f in content["body"][3]["facts"]}
    assert facts["Severity"] == "Critical" and facts["Site"].startswith("PNQ1")

    await session.rollback()
    rows = (
        await session.execute(
            text("SELECT details FROM alert_activity WHERE alert_id = :a AND action = 'notified'"),
            {"a": alert_id},
        )
    ).all()
    assert sorted(r[0]["channel"] for r in rows) == ["email", "teams"]
    assert all(r[0]["ok"] for r in rows) and all("@" in r[0]["target"] or "…" in r[0]["target"] for r in rows)
    notified = (
        await session.execute(text("SELECT notified_at FROM alerts WHERE id = :a"), {"a": alert_id})
    ).scalar()
    assert notified is not None


@respx.mock
async def test_failed_send_is_recorded(
    world: World,
    session: AsyncSession,
    app_engine: AsyncEngine,
    sent_mail: list[tuple[EmailMessage, dict[str, Any]]],
) -> None:
    await _routes(session, world)
    alert_id = await _critical_alert(world, session, app_engine)
    respx.post(TEAMS_URL).mock(return_value=httpx.Response(500))
    results, _ = await in_app_tx(
        app_engine, lambda s, e: notify_alert(s, alert_id, "opened", 0, get_settings(), datetime.now(UTC))
    )
    assert sorted((r.channel, r.ok) for r in results) == [("email", True), ("teams", False)]
    await session.rollback()
    failed = (
        await session.execute(
            text(
                "SELECT note, details->>'error' FROM alert_activity WHERE alert_id = :a AND action = 'notified' "
                "AND (details->>'ok')::boolean = false"
            ),
            {"a": alert_id},
        )
    ).one()
    assert "failed" in failed[0] and "500" in failed[1]


async def test_escalation_goes_to_level_one_and_muted_is_silent(
    world: World,
    session: AsyncSession,
    app_engine: AsyncEngine,
    sent_mail: list[tuple[EmailMessage, dict[str, Any]]],
) -> None:
    await _routes(session, world)
    alert_id = await _critical_alert(world, session, app_engine)
    now = datetime.now(UTC)
    results, _ = await in_app_tx(
        app_engine, lambda s, e: notify_alert(s, alert_id, "escalated", 1, get_settings(), now)
    )
    assert [r.channel for r in results] == ["email"]
    assert sent_mail[-1][0]["To"] == "manager@gcc.example"
    assert sent_mail[-1][0]["Subject"].startswith("[GCC ESCALATED]")

    await session.execute(text("UPDATE alerts SET muted = true WHERE id = :a"), {"a": alert_id})
    await session.commit()
    before = len(sent_mail)
    results, _ = await in_app_tx(
        app_engine, lambda s, e: notify_alert(s, alert_id, "opened", 0, get_settings(), now)
    )
    assert results == [] and len(sent_mail) == before

    # A stale "opened" job for an alert that has resolved is dropped.
    await session.execute(
        text("UPDATE alerts SET muted = false, state = 'resolved' WHERE id = :a"), {"a": alert_id}
    )
    await session.commit()
    results, _ = await in_app_tx(
        app_engine, lambda s, e: notify_alert(s, alert_id, "opened", 0, get_settings(), now)
    )
    assert results == []
