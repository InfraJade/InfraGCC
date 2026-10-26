"""POST /ingest/v1/batches: gzip round trip into every table as gcc_ingest, dedupe, validation, health
derivation, inventory snapshots, live publishing and alert enqueueing — plus the contract fixture (D7)."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis
import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import get_settings
from app.core.live import LIVE_CHANNEL
from app.core.redis import set_redis
from app.ingest.schemas import BatchIn
from app.worker import names
from tests.ingest.fixtures import (
    CONTRACT_EXAMPLE,
    TaskRecorder,
    World,
    batch,
    headers,
    iso,
    post_batch,
    reading,
)

pytestmark = pytest.mark.db


async def rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    await session.rollback()  # fresh snapshot
    return list((await session.execute(text(sql), params)).all())


def full_payload(server_id: int, now: datetime) -> dict[str, Any]:
    return {
        "server_id": server_id,
        "polled_at": iso(now),
        "readings": [
            reading(now - timedelta(seconds=60), "inlet_temp_c", 22.0, status="OK"),
            reading(now, "inlet_temp_c", 22.5, status="OK"),
            reading(now, "cpu_temp_c", 61.0, "CPU1", "OK"),
            reading(now, "power_w", 412.0),
            reading(now, "power_state", 1, status="On"),
            reading(now, "system_health", 0, status="OK"),
            reading(now, "psu_health", 1, "PSU 2", "Warning"),
            reading(now, "nic_link", 1, "NIC 1", "Up"),
            reading(now, "nic_link", 0, "NIC 2", "Down"),
            reading(now, "bmc_reachable", 1, status="Reachable"),
        ],
        "bmc_limits": [
            {
                "metric": "cpu_temp_c",
                "component": "CPU1",
                "lower_critical": None,
                "lower_warning": None,
                "upper_warning": 85.0,
                "upper_critical": 95.0,
            }
        ],
        "events": [
            {
                "entry_id": "Sel/7",
                "time": iso(now - timedelta(minutes=5)),
                "severity": "Critical",
                "message": "PSU 2 lost input.",
                "message_id": "PSU0003",
            }
        ],
        "identity": {
            "vendor": "Dell",
            "model": "PowerEdge R750",
            "serial": "7XK2M93",
            "sku": "R750",
            "hostname": "host-from-bmc",
            "uuid": "4c4c4544-0058-4b10-8032-b7c04f4d3933",
            "asset_tag": None,
            "bmc_model": "iDRAC9",
            "bmc_firmware": "7.10.70.00",
            "bmc_mac": "D0:8E:79:00:00:10",
            "system_path": "/redfish/v1/Systems/System.Embedded.1",
            "host_ips": ["10.20.1.11"],
        },
        "components": [
            {
                "type": "cpu",
                "name": "CPU1",
                "model": "Xeon",
                "manufacturer": "Intel",
                "serial": None,
                "capacity": 32,
                "capacity_unit": "cores",
                "firmware_version": None,
                "location": "CPU.Socket.1",
                "link_up": None,
                "extra": {},
            },
            {
                "type": "nic",
                "name": "NIC 1",
                "model": "BCM57414",
                "manufacturer": "Broadcom",
                "serial": None,
                "capacity": 25000,
                "capacity_unit": "Mbps",
                "firmware_version": None,
                "location": "NIC.Integrated.1-1-1",
                "link_up": True,
                "extra": {"mac": "D0:8E:79:00:00:11"},
            },
            {
                "type": "nic",
                "name": "NIC 2",
                "model": "BCM57414",
                "manufacturer": "Broadcom",
                "serial": None,
                "capacity": 25000,
                "capacity_unit": "Mbps",
                "firmware_version": None,
                "location": "NIC.Integrated.1-2-1",
                "link_up": False,
                "extra": {},
            },
        ],
        "firmware": [
            {"component": "BIOS", "component_key": "BIOS", "component_type": "bios", "version": "1.15.2"},
            {"component": "iDRAC", "component_key": "BMC", "component_type": "bmc", "version": "7.10.70.00"},
        ],
    }


async def test_gzip_batch_lands_in_every_table_as_ingest_role(
    ingest_client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    fake_redis: fakeredis.FakeAsyncRedis,
    tasks: TaskRecorder,
) -> None:
    server = world.server(0)
    now = datetime.now(UTC).replace(microsecond=0)
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe(LIVE_CHANNEL)
    doc = batch("pnq1-col-a", [full_payload(server.id, now)])

    r = await post_batch(ingest_client, doc)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "batch_id": doc["batch_id"],
        "duplicate": False,
        "servers": 1,
        "readings": 10,
        "events": 1,
    }

    sid = server.id
    assert (await rows(session, "SELECT count(*) FROM readings WHERE server_id = :s", s=sid))[0][0] == 10
    latest = await rows(
        session,
        "SELECT m.code, l.component, l.value FROM latest_readings l JOIN metric_definitions m ON m.id = l.metric_code "
        "WHERE server_id = :s ORDER BY 1, 2",
        s=sid,
    )
    assert ("inlet_temp_c", "", 22.5) in [tuple(x) for x in latest] and len(latest) == 9
    health = {
        (x[0], x[1]): x[2]
        for x in await rows(
            session,
            "SELECT m.code, h.component, h.health FROM health_status h "
            "JOIN metric_definitions m ON m.id = h.metric_code WHERE server_id = :s",
            s=sid,
        )
    }
    assert health == {
        ("power_state", ""): "OK",
        ("system_health", ""): "OK",
        ("psu_health", "PSU 2"): "Warning",
        ("nic_link", "NIC 1"): "OK",
        ("nic_link", "NIC 2"): "OK",  # down, but it was down when first inventoried: not expected (D19)
        ("bmc_reachable", ""): "OK",
    }
    limits = await rows(
        session,
        "SELECT component, upper_warning, upper_critical FROM bmc_thresholds WHERE server_id = :s",
        s=sid,
    )
    assert [tuple(x) for x in limits] == [("CPU1", 85.0, 95.0)]
    events = await rows(
        session, "SELECT entry_id, severity, message_id FROM events WHERE server_id = :s", s=sid
    )
    assert [tuple(x) for x in events] == [("Sel/7", "Critical", "PSU0003")]
    comps = {
        x[0]: (x[1], x[2])
        for x in await rows(
            session, "SELECT name, expected_link_up, removed_at FROM components WHERE server_id = :s", s=sid
        )
    }
    assert comps == {"CPU1": (None, None), "NIC 1": (True, None), "NIC 2": (False, None)}
    fw = await rows(
        session,
        "SELECT component_key, version FROM firmware_inventory WHERE server_id = :s ORDER BY 1",
        s=sid,
    )
    assert [tuple(x) for x in fw] == [("BIOS", "1.15.2"), ("BMC", "7.10.70.00")]
    srv = (
        await rows(
            session,
            "SELECT vendor, model, serial, bmc_model, bmc_mac, system_path, host_ips, name, discovered_at, "
            "last_seen_at, rack_id FROM servers WHERE id = :s",
            s=sid,
        )
    )[0]
    assert srv[:7] == ("Dell", "PowerEdge R750", "7XK2M93", "iDRAC9", "D0:8E:79:00:00:10",
                       "/redfish/v1/Systems/System.Embedded.1", ["10.20.1.11"])  # fmt: skip
    assert srv[7] == "srv-01"  # an admin-given name is kept
    assert srv[8] == now and srv[9] == now and srv[10] == server.rack_id

    # Live updates were published and alert evaluation was queued for the server.
    messages = []
    for _ in range(10):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg is not None:
            messages.append(json.loads(msg["data"]))
    assert {m["type"] for m in messages} == {"readings", "health"}
    readings_msg = next(m for m in messages if m["type"] == "readings")
    assert readings_msg["server_id"] == sid and readings_msg["site_id"] == world.sites["PNQ1"].id
    health_msg = next(m for m in messages if m["type"] == "health")
    assert health_msg["server_health"] == "Warning"
    assert tasks.calls == [(names.EVALUATE_SERVERS, {"args": [[sid]], "queue": "alerts", "retry": False})]
    await pubsub.aclose()  # type: ignore[no-untyped-call]


async def test_all_writes_run_as_gcc_ingest(ingest_engine: AsyncEngine) -> None:
    async with ingest_engine.connect() as conn:
        assert (await conn.execute(text("SELECT current_user"))).scalar_one() == "gcc_ingest"


async def test_duplicate_batch_is_acknowledged_and_ignored(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    doc = batch("pnq1-col-a", [{"server_id": world.server(1).id, "polled_at": iso(now),
                                "readings": [reading(now, "inlet_temp_c", 21.0)]}])  # fmt: skip
    first = await post_batch(ingest_client, doc)
    second = await post_batch(ingest_client, doc, compress=False)
    assert first.json()["duplicate"] is False and first.json()["readings"] == 1
    assert second.status_code == 200 and second.json()["duplicate"] is True
    count = await rows(session, "SELECT count(*) FROM readings WHERE server_id = :s", s=world.server(1).id)
    assert count[0][0] == 1


async def test_in_flight_duplicate_gets_503(
    ingest_client: httpx.AsyncClient, world: World, fake_redis: fakeredis.FakeAsyncRedis
) -> None:
    doc = batch("pnq1-col-a", [], batch_id="in-flight-1")
    await fake_redis.set("gcc:ingest:batch:in-flight-1", "pending")
    r = await post_batch(ingest_client, doc)
    assert r.status_code == 503 and r.headers["retry-after"] == "5"


async def test_servers_not_assigned_to_the_collector_are_dropped(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    mine, theirs = world.server(0).id, world.server(5).id  # server 5 belongs to pnq1-col-b
    doc = batch(
        "pnq1-col-a",
        [
            {"server_id": mine, "polled_at": iso(now), "readings": [reading(now, "inlet_temp_c", 21.0)]},
            {"server_id": theirs, "polled_at": iso(now), "readings": [reading(now, "inlet_temp_c", 99.0)]},
        ],
    )
    r = await post_batch(ingest_client, doc)
    assert r.status_code == 200 and r.json()["servers"] == 1 and r.json()["readings"] == 1
    assert (await rows(session, "SELECT count(*) FROM readings WHERE server_id = :s", s=theirs))[0][0] == 0


async def test_batch_for_another_collector_name_is_403(
    ingest_client: httpx.AsyncClient, world: World
) -> None:
    r = await post_batch(ingest_client, batch("pnq1-col-b", []), collector="pnq1-col-a")
    assert r.status_code == 403


async def test_validation_errors_are_problem_json(ingest_client: httpx.AsyncClient, world: World) -> None:
    now = datetime.now(UTC)
    doc = batch("pnq1-col-a", [{"server_id": world.server(0).id, "polled_at": iso(now), "surprise": True}])
    r = await post_batch(ingest_client, doc)
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert any(e["type"] == "extra_forbidden" for e in r.json()["errors"])

    bad_schema = {**batch("pnq1-col-a", []), "schema": 2}
    assert (await post_batch(ingest_client, bad_schema)).status_code == 422
    naive_time = batch("pnq1-col-a", [{"server_id": 1, "polled_at": "2026-10-22T10:00:00"}])
    assert (await post_batch(ingest_client, naive_time)).status_code == 422


async def test_bad_gzip_and_oversized_bodies(
    ingest_client: httpx.AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = await ingest_client.post(
        "/ingest/v1/batches", content=b"\x1f\x8bnot gzip", headers=headers(gzip_body=True)
    )
    assert r.status_code == 400
    r = await ingest_client.post(
        "/ingest/v1/batches", content=b"{}", headers={**headers(), "Content-Encoding": "br"}
    )
    assert r.status_code == 415
    monkeypatch.setattr(get_settings(), "ingest_max_body_bytes", 2000)
    big = batch("pnq1-col-a", [{"server_id": world.server(0).id, "polled_at": iso(datetime.now(UTC)),
                                "readings": [reading(datetime.now(UTC), "inlet_temp_c", 20.0)] * 50}])  # fmt: skip
    r = await post_batch(ingest_client, big)  # small when compressed, too large once inflated
    assert r.status_code == 413
    r = await post_batch(ingest_client, big, compress=False)
    assert r.status_code == 413


async def test_unknown_metrics_are_skipped_not_fatal(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    doc = batch("pnq1-col-a", [{"server_id": world.server(0).id, "polled_at": iso(now), "readings": [
        reading(now, "inlet_temp_c", 20.0), reading(now, "quantum_flux", 1.0), reading(now, "sel_event", 1.0)]}])  # fmt: skip
    r = await post_batch(ingest_client, doc)
    assert r.status_code == 200 and r.json()["readings"] == 1


async def test_health_derivation_and_since(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    sid = world.server(0).id
    t0 = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)
    first = full_payload(sid, t0)
    assert (await post_batch(ingest_client, batch("pnq1-col-a", [first]))).status_code == 200

    t1 = t0 + timedelta(minutes=5)
    second = {"server_id": sid, "polled_at": iso(t1), "readings": [
        reading(t1, "nic_link", 0, "NIC 1", "Down"),      # expected link down -> Warning
        reading(t1, "power_state", 0, status="Off"),        # Off -> Warning
        reading(t1, "bmc_reachable", 0, status="Unreachable"),  # -> Critical
        reading(t1, "psu_health", 1, "PSU 2", "Warning"),   # unchanged -> since kept
        reading(t1, "fan_health", None, "Fan 1", "Unknown"),
    ]}  # fmt: skip
    assert (await post_batch(ingest_client, batch("pnq1-col-a", [second]))).status_code == 200
    health = {
        (x[0], x[1]): (x[2], x[3])
        for x in await rows(
            session,
            "SELECT m.code, h.component, h.health, h.since FROM health_status h "
            "JOIN metric_definitions m ON m.id = h.metric_code WHERE server_id = :s",
            s=sid,
        )
    }
    assert health[("nic_link", "NIC 1")] == ("Warning", t1)
    assert health[("power_state", "")] == ("Warning", t1)
    assert health[("bmc_reachable", "")] == ("Critical", t1)
    assert health[("psu_health", "PSU 2")] == ("Warning", t0)
    assert health[("fan_health", "Fan 1")][0] == "Unknown"

    # An older replay does not overwrite newer health or latest values.
    replay = {
        "server_id": sid,
        "polled_at": iso(t0),
        "readings": [reading(t0, "power_state", 1, status="On")],
    }
    assert (await post_batch(ingest_client, batch("pnq1-col-a", [replay]))).status_code == 200
    state = await rows(
        session,
        "SELECT h.health, l.value FROM health_status h JOIN latest_readings l USING (server_id, metric_code, component) "
        "WHERE h.server_id = :s AND h.metric_code = 15",
        s=sid,
    )
    assert tuple(state[0]) == ("Warning", 0.0)


async def test_inventory_snapshots_mark_removed_parts_and_keep_expected_links(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    sid = world.server(0).id
    t0 = datetime.now(UTC).replace(microsecond=0)
    assert (await post_batch(ingest_client, batch("pnq1-col-a", [full_payload(sid, t0)]))).status_code == 200
    t1 = t0 + timedelta(days=1)
    nic1 = copy.deepcopy(full_payload(sid, t0)["components"][1])
    nic1["link_up"] = False  # the link went down later: still expected up (first sighting wins, D19)
    snap = {"server_id": sid, "polled_at": iso(t1), "components": [nic1],
            "firmware": [{"component": "BIOS", "component_key": "BIOS", "component_type": "bios", "version": "1.16.0"}]}  # fmt: skip
    assert (await post_batch(ingest_client, batch("pnq1-col-a", [snap]))).status_code == 200
    comps = {
        x[0]: (x[1], x[2])
        for x in await rows(
            session, "SELECT name, expected_link_up, removed_at FROM components WHERE server_id = :s", s=sid
        )
    }
    assert comps == {"CPU1": (None, t1), "NIC 1": (True, None), "NIC 2": (False, t1)}
    fw = await rows(session, "SELECT component, version FROM firmware_inventory WHERE server_id = :s", s=sid)
    assert [tuple(x) for x in fw] == [("BIOS", "1.16.0")]

    # A part that comes back is no longer removed.
    t2 = t1 + timedelta(days=1)
    back = {"server_id": sid, "polled_at": iso(t2), "components": full_payload(sid, t0)["components"]}
    assert (await post_batch(ingest_client, batch("pnq1-col-a", [back]))).status_code == 200
    removed = await rows(
        session, "SELECT count(*) FROM components WHERE server_id = :s AND removed_at IS NOT NULL", s=sid
    )
    assert removed[0][0] == 0


async def test_redis_and_broker_outages_do_not_fail_the_batch(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession, tasks: TaskRecorder
) -> None:
    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2, decode_responses=True)
    set_redis(dead)
    tasks.fail = True
    now = datetime.now(UTC)
    doc = batch("pnq1-col-a", [{"server_id": world.server(2).id, "polled_at": iso(now),
                                "readings": [reading(now, "inlet_temp_c", 20.0)]}])  # fmt: skip
    r = await post_batch(ingest_client, doc)
    assert r.status_code == 200 and r.json()["readings"] == 1
    await dead.aclose()


async def test_contract_example_is_valid_and_ingests(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    """D7: the collector-generated example parses with extra="forbid" and lands in the database."""
    doc = json.loads(CONTRACT_EXAMPLE.read_text(encoding="utf-8"))
    parsed = BatchIn.model_validate(doc)
    assert parsed.collector == "pnq1-col-a" and parsed.servers
    # Point the example's servers at this test database's servers owned by the same collector.
    own = [s.id for s in world.servers[:4]]
    mapping = {p.server_id: own[i] for i, p in enumerate(parsed.servers)}
    for payload in doc["servers"]:
        payload["server_id"] = mapping[payload["server_id"]]
    r = await post_batch(ingest_client, doc)
    assert r.status_code == 200, r.text
    expected_readings = sum(len(p.readings or ()) for p in parsed.servers)
    assert r.json()["readings"] == expected_readings and r.json()["servers"] == len(parsed.servers)
    sid = mapping[parsed.servers[0].server_id]
    count = await rows(session, "SELECT count(*) FROM readings WHERE server_id = :s", s=sid)
    assert count[0][0] == len(parsed.servers[0].readings or ())


async def test_concurrent_batches_for_different_servers(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    docs = [
        batch("pnq1-col-a", [{"server_id": s.id, "polled_at": iso(now),
                              "readings": [reading(now - timedelta(seconds=k), "inlet_temp_c", 20.0 + k) for k in range(30)]}])
        for s in world.servers[:4]
    ]  # fmt: skip
    results = await asyncio.gather(*(post_batch(ingest_client, d) for d in docs))
    assert all(r.status_code == 200 for r in results)
    total = await rows(session, "SELECT count(*) FROM readings")
    assert total[0][0] == 120


async def test_collector_realities_large_batches_resent_events_and_free_form_extra(
    ingest_client: httpx.AsyncClient, world: World, session: AsyncSession
) -> None:
    """Collectors resend every log entry after a restart, send float capacities, free-form `extra`, null gauge
    status, and up to 200 servers per batch (here: 200 payloads over the collector's 4 servers)."""
    now = datetime.now(UTC)
    own = [s.id for s in world.servers[:4]]
    event = {
        "entry_id": "Sel/1",
        "time": iso(now),
        "severity": "Critical",
        "message": "x",
        "message_id": "M1",
    }
    comp = {"type": "storage_controller", "name": "RAID.SL.3-1", "model": "PERC H755", "manufacturer": "Dell",
            "serial": None, "capacity": 1.5, "capacity_unit": "GB", "firmware_version": "52.26", "location": None,
            "link_up": None, "extra": {"controller": "x", "raid": ["RAID1"], "threads": 64, "max_speed_mhz": 3200.0,
                                       "speed_mhz": None, "media": "SSD", "protocol": "SATA", "mac": "aa", "type": "t"}}  # fmt: skip
    payloads = [
        {"server_id": own[i % 4], "polled_at": iso(now), "events": [event, event],
         "readings": [reading(now - timedelta(seconds=i), "fan_rpm", 7000.0 + i, "Fan 1", None)],
         **({"components": [comp]} if i < 4 else {})}
        for i in range(200)
    ]  # fmt: skip
    r = await post_batch(ingest_client, batch("pnq1-col-a", payloads))
    assert r.status_code == 200, r.text
    assert r.json()["servers"] == 200 and r.json()["readings"] == 200
    again = await post_batch(ingest_client, batch("pnq1-col-a", payloads[:4]))  # restart: same entries again
    assert again.status_code == 200
    events = await rows(session, "SELECT count(*) FROM events")
    assert events[0][0] == 4
    extra = await rows(session, "SELECT extra, capacity FROM components WHERE server_id = :s", s=own[0])
    assert extra[0][0]["threads"] == 64 and extra[0][1] == 1.5


async def test_transient_database_failure_is_503(
    ingest_client: httpx.AsyncClient,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: fakeredis.FakeAsyncRedis,
) -> None:
    async def broken(*_: Any, **__: Any) -> None:
        raise OSError("connection reset")

    monkeypatch.setattr("app.ingest.routes.write_batch", broken)
    doc = batch("pnq1-col-a", [], batch_id="transient-1")
    r = await post_batch(ingest_client, doc)
    assert r.status_code == 503 and r.headers["content-type"].startswith("application/problem+json")
    assert (
        await fake_redis.get("gcc:ingest:batch:transient-1") is None
    )  # claim released: the retry is processed
