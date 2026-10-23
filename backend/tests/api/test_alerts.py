"""Alert list, detail, and the acknowledge / comment / resolve flow (activity, audit, live message)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import fakeredis
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.live import LIVE_CHANNEL
from app.models import Alert, AlertActivity, AuditLog
from tests.api.conftest import TokenFactory, World, problem

pytestmark = pytest.mark.db


async def test_alert_filters(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    h = tokens.headers()

    async def ids(query: str) -> list[int]:
        resp = await client.get(f"/api/v1/alerts?{query}", headers=h)
        assert resp.status_code == 200, resp.text
        return [a["id"] for a in resp.json()["items"]]

    assert await ids("") == [world.a_event, world.a_hyd, world.a_pnq]  # newest first
    assert await ids("severity=Critical") == [world.a_event, world.a_pnq]
    assert await ids("severity=Warning&severity=Info") == [world.a_hyd]
    assert await ids(f"site_id={world.hyd}") == [world.a_hyd]
    assert await ids(f"server_id={world.s2}") == [world.a_pnq]
    assert await ids("state=resolved") == []
    assert await ids("q=event") == [world.a_event]
    frm = (datetime.now(UTC) - timedelta(minutes=7)).isoformat().replace("+00:00", "Z")
    assert await ids(f"from={frm}") == [world.a_event, world.a_hyd]
    walk = (await client.get("/api/v1/alerts?limit=2", headers=h)).json()
    rest = (await client.get(f"/api/v1/alerts?limit=2&cursor={walk['next_cursor']}", headers=h)).json()
    assert [a["id"] for a in walk["items"] + rest["items"]] == [world.a_event, world.a_hyd, world.a_pnq]
    item = (await client.get(f"/api/v1/alerts/{world.a_pnq}", headers=h)).json()
    assert item["rule"]["rule_type"] == "threshold" and item["metric"] == "inlet_temp_c"
    assert item["server"]["id"] == world.s2 and item["site"]["code"] == "PNQ1"
    assert item["manually_resolvable"] is False and item["activity"] == []


async def test_ack_and_comment_write_activity_audit_and_publish(
    client: httpx.AsyncClient,
    tokens: TokenFactory,
    world: World,
    db: AsyncSession,
    fake_redis: fakeredis.FakeAsyncRedis,
) -> None:
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe(LIVE_CHANNEL)
    await pubsub.get_message(timeout=1)  # subscribe confirmation
    h = tokens.headers("noc")

    resp = await client.post(f"/api/v1/alerts/{world.a_pnq}/ack", headers=h, json={"note": "on it"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "acknowledged" and body["acked_by"] == "Noc" and body["acked_at"]
    [act] = body["activity"]
    assert (act["action"], act["from_state"], act["to_state"], act["note"], act["actor"]) == (
        "acknowledged",
        "open",
        "acknowledged",
        "on it",
        "Noc",
    )
    message = await asyncio.wait_for(_next_message(pubsub), 2)
    assert message["type"] == "alert" and message["alert_id"] == world.a_pnq
    assert message["change"] == "acknowledged" and message["site_id"] == world.pnq

    problem(await client.post(f"/api/v1/alerts/{world.a_pnq}/ack", headers=h, json={}), 409)
    resp = await client.post(
        f"/api/v1/alerts/{world.a_pnq}/comments", headers=h, json={"note": "fan replaced"}
    )
    assert [a["action"] for a in resp.json()["activity"]] == ["acknowledged", "comment"]
    problem(await client.post(f"/api/v1/alerts/{world.a_pnq}/comments", headers=h, json={"note": ""}), 422)

    acts = (
        (await db.execute(select(AlertActivity).where(AlertActivity.alert_id == world.a_pnq))).scalars().all()
    )
    assert [(a.action, a.actor_sub) for a in acts] == [("acknowledged", "sub-noc"), ("comment", "sub-noc")]
    audits = (
        (await db.execute(select(AuditLog).where(AuditLog.object_type == "alert").order_by(AuditLog.id)))
        .scalars()
        .all()
    )
    assert [(a.action, a.object_id) for a in audits] == [
        ("alert.ack", str(world.a_pnq)),
        ("alert.comment", str(world.a_pnq)),
    ]
    assert audits[0].before == {"state": "open"} and audits[0].request_id
    await pubsub.aclose()  # type: ignore[no-untyped-call]


async def _next_message(pubsub: object) -> dict[str, object]:
    while True:
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)  # type: ignore[attr-defined]
        if msg is not None:
            data: dict[str, object] = json.loads(msg["data"])
            return data


async def test_ack_works_without_redis(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    from redis.asyncio import Redis

    from app.core import redis as redis_module

    original = redis_module.get_redis()
    redis_module.set_redis(Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2))
    try:
        resp = await client.post(f"/api/v1/alerts/{world.a_hyd}/ack", headers=tokens.headers("noc"), json={})
        assert resp.status_code == 200, resp.text
    finally:
        redis_module.set_redis(original)


async def test_manual_resolve_only_for_event_and_compliance(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, db: AsyncSession
) -> None:
    h = tokens.headers("noc-pune")
    problem(await client.post(f"/api/v1/alerts/{world.a_pnq}/resolve", headers=h, json={}), 409)
    resp = await client.post(
        f"/api/v1/alerts/{world.a_event}/resolve", headers=h, json={"note": "SEL cleared"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "resolved" and body["resolved_by"] == "Noc Pune"
    assert body["activity"][-1]["action"] == "resolved"
    problem(await client.post(f"/api/v1/alerts/{world.a_event}/resolve", headers=h, json={}), 409)
    problem(await client.post(f"/api/v1/alerts/{world.a_event}/ack", headers=h, json={}), 409)
    alert = await db.get(Alert, world.a_event)
    assert alert is not None
    await db.refresh(alert)
    assert alert.state == "resolved" and alert.resolved_at is not None
