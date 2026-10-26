"""Ingest authentication (token and mTLS-header modes), /config with HA takeover, and heartbeats."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.ingest.auth import normalize_fingerprint, peer_is_trusted
from app.models import Collector, Server
from tests.ingest.fixtures import TOKEN, World, headers

pytestmark = pytest.mark.db


async def test_missing_or_bad_token_is_401_problem(ingest_client: httpx.AsyncClient) -> None:
    r = await ingest_client.get("/ingest/v1/config", headers={"X-Collector-Name": "pnq1-col-a"})
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 401
    r = await ingest_client.get("/ingest/v1/config", headers=headers(token="nope"))
    assert r.status_code == 401
    r = await ingest_client.get("/ingest/v1/config", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 401


async def test_unknown_or_disabled_collector_is_401(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    r = await ingest_client.get("/ingest/v1/config", headers=headers("ghost"))
    assert r.status_code == 401
    await session.execute(update(Collector).where(Collector.name == "pnq1-col-b").values(enabled=False))
    await session.commit()
    r = await ingest_client.get("/ingest/v1/config", headers=headers("pnq1-col-b"))
    assert r.status_code == 401


async def test_mtls_mode_trusts_fingerprint_only_from_proxies(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "ingest_auth_mode", "mtls")
    monkeypatch.setattr(settings, "ingest_trusted_proxies", ["127.0.0.0/8"])
    await session.execute(
        update(Collector).where(Collector.name == "pnq1-col-a").values(cert_fingerprint="AB:CD:EF:01:23")
    )
    await session.commit()

    fp = {"X-Client-Cert-Fingerprint": "sha256:abcdef0123", "X-Client-Cert-Subject": "CN=pnq1-col-a"}
    r = await ingest_client.get("/ingest/v1/config", headers=fp)
    assert r.status_code == 200, r.text
    assert r.json()["collector"]["name"] == "pnq1-col-a"

    # A shared token is not enough in mTLS mode.
    r = await ingest_client.get("/ingest/v1/config", headers=headers())
    assert r.status_code == 401
    # Unknown certificate.
    r = await ingest_client.get("/ingest/v1/config", headers={"X-Client-Cert-Fingerprint": "ffff"})
    assert r.status_code == 401
    # The same header from a peer that is not a trusted proxy is ignored.
    from app.ingest.main import app

    transport = httpx.ASGITransport(app=app, client=("10.9.9.9", 4000))
    async with httpx.AsyncClient(transport=transport, base_url="http://ingest") as outsider:
        r = await outsider.get("/ingest/v1/config", headers=fp)
    assert r.status_code == 401


def test_fingerprint_and_proxy_helpers() -> None:
    assert normalize_fingerprint("SHA256:AB:cd:EF") == normalize_fingerprint("abcdef") == "abcdef"
    assert peer_is_trusted("10.1.2.3", ["10.0.0.0/8"])
    assert peer_is_trusted("127.0.0.1", ["127.0.0.1"])
    assert not peer_is_trusted("192.168.1.1", ["10.0.0.0/8", "not-an-ip"])
    assert not peer_is_trusted(None, ["127.0.0.1"])


async def test_config_lists_own_servers_and_settings(ingest_client: httpx.AsyncClient, world: World) -> None:
    r = await ingest_client.get("/ingest/v1/config", headers=headers("pnq1-col-a"))
    assert r.status_code == 200
    body = r.json()
    assert body["collector"]["site_code"] == "PNQ1"
    ids = [s["id"] for s in body["servers"]]
    assert ids == [s.id for s in world.servers[:4]]
    assert all(not s["takeover"] and s["credential_ref"] == "default" for s in body["servers"])
    assert body["settings"]["sensor_interval_s"] == 60
    assert body["settings"]["config_refresh_s"] == 60
    assert len(body["config_version"]) == 12


async def test_ha_takeover_splits_offline_collectors_servers(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    site = world.sites["PNQ1"]
    # A third collector at PNQ1 so the split is visible.
    session.add(Collector(site_id=site.id, name="pnq1-col-c", last_heartbeat=datetime.now(UTC)))
    await session.commit()
    before = (await ingest_client.get("/ingest/v1/config", headers=headers("pnq1-col-a"))).json()

    stale = datetime.now(UTC) - timedelta(seconds=get_settings().collector_offline_after_s + 5)
    await session.execute(
        update(Collector).where(Collector.name == "pnq1-col-b").values(last_heartbeat=stale)
    )
    await session.commit()

    a = (await ingest_client.get("/ingest/v1/config", headers=headers("pnq1-col-a"))).json()
    c = (await ingest_client.get("/ingest/v1/config", headers=headers("pnq1-col-c"))).json()
    b_servers = {s.id for s in world.servers[4:8]}
    a_take = {s["id"] for s in a["servers"] if s["takeover"]}
    c_take = {s["id"] for s in c["servers"] if s["takeover"]}
    assert a_take | c_take == b_servers and not a_take & c_take
    live = sorted([world.collectors["pnq1-col-a"].id, (await _collector_id(session, "pnq1-col-c"))])
    for sid in b_servers:
        owner = live[sid % 2]
        assert (sid in a_take) == (owner == world.collectors["pnq1-col-a"].id)
    assert a["config_version"] != before["config_version"]
    # HYD1 servers are never taken over by PNQ1 collectors.
    assert not {s.id for s in world.servers[8:]} & (a_take | c_take)

    # The preferred collector comes back: takeover reverses.
    await session.execute(
        update(Collector).where(Collector.name == "pnq1-col-b").values(last_heartbeat=datetime.now(UTC))
    )
    await session.commit()
    again = (await ingest_client.get("/ingest/v1/config", headers=headers("pnq1-col-a"))).json()
    assert not any(s["takeover"] for s in again["servers"])


async def test_decommissioned_servers_are_not_polled(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    await session.execute(
        update(Server).where(Server.id == world.servers[0].id).values(status="decommissioned")
    )
    await session.commit()
    body = (await ingest_client.get("/ingest/v1/config", headers=headers("pnq1-col-a"))).json()
    assert world.servers[0].id not in [s["id"] for s in body["servers"]]


async def test_heartbeat_updates_collector_and_returns_config_version(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    payload = {
        "collector": "pnq1-col-a",
        "version": "1.0.0",
        "hostname": "collector-pnq1-a",
        "sent_at": "2026-10-22T10:00:30Z",
        "config_version": "old",
        "stats": {
            "servers_assigned": 4,
            "servers_ok": 4,
            "polls_ok_1m": 8,
            "polls_failed_1m": 0,
            "cycles_skipped_1m": 0,
            "buffer_batches": 0,
            "buffer_bytes": 0,
            "last_batch_at": "2026-10-22T10:00:24Z",
            "errors_by_vendor": {"Dell": 0},
        },
    }
    r = await ingest_client.post("/ingest/v1/heartbeat", json=payload, headers=headers())
    assert r.status_code == 200, r.text
    config = (await ingest_client.get("/ingest/v1/config", headers=headers())).json()
    assert r.json() == {"ok": True, "config_version": config["config_version"]}
    row = (
        await session.execute(
            text(
                "SELECT version, hostname, stats, now() - last_heartbeat FROM collectors WHERE name = 'pnq1-col-a'"
            )
        )
    ).one()
    assert row[0] == "1.0.0" and row[1] == "collector-pnq1-a"
    assert row[2]["servers_ok"] == 4 and row[2]["config_version"] == "old"
    assert row[3] < timedelta(seconds=5)

    # Another collector's name in the body is refused; unknown fields are rejected.
    r = await ingest_client.post(
        "/ingest/v1/heartbeat", json={**payload, "collector": "pnq1-col-b"}, headers=headers()
    )
    assert r.status_code == 403
    r = await ingest_client.post("/ingest/v1/heartbeat", json={**payload, "surprise": 1}, headers=headers())
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


async def _collector_id(session: AsyncSession, name: str) -> int:
    return int(
        (await session.execute(text("SELECT id FROM collectors WHERE name = :n"), {"n": name})).scalar_one()
    )
