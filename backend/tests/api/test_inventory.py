"""Overview, sites, racks, servers (list, detail, onboarding, edits), parts, events, history, CSV, paging."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Server, readings
from app.services.query.readings import choose_resolution
from tests.api.conftest import TokenFactory, World, problem

pytestmark = pytest.mark.db


async def test_overview(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    body = (await client.get("/api/v1/overview", headers=tokens.headers())).json()
    totals = body["totals"]
    assert totals["sites"] == 2 and totals["server_count"] == 3
    assert totals["health"] == {"ok": 1, "warning": 1, "critical": 1, "unknown": 0}
    assert totals["worst_health"] == "Critical"
    assert totals["alerts"]["critical"] == 2 and totals["alerts"]["warning"] == 1
    assert totals["power_w"] == 1200.0
    assert totals["freshness"]["servers_reporting"] == 3
    assert totals["collectors_online"] == 1 and totals["collectors_total"] == 3
    pnq = next(s for s in body["sites"] if s["code"] == "PNQ1")
    assert pnq["inlet_max_c"] == 24.0 and pnq["rack_count"] == 2 and pnq["room_count"] == 1


async def test_site_detail_colors_racks_by_worst_health(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    body = (await client.get(f"/api/v1/sites/{world.pnq}", headers=tokens.headers())).json()
    [room] = body["rooms"]
    racks = {r["name"]: r for r in room["racks"]}
    assert racks["A01"]["worst_health"] == "Critical"
    assert racks["A01"]["server_count"] == 2 and racks["A01"]["used_u"] == 4
    assert racks["A02"]["server_count"] == 0
    assert room["worst_health"] == "Critical"
    assert {c["name"]: c["online"] for c in body["collectors"]} == {"pnq1-col-a": True, "pnq1-col-b": False}


async def test_rack_detail_lists_servers_in_position_order(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    body = (await client.get(f"/api/v1/racks/{world.pnq_rack}", headers=tokens.headers())).json()
    assert [s["id"] for s in body["servers"]] == [world.s1, world.s2]
    s2 = body["servers"][1]
    assert s2["health"] == "Critical" and s2["open_alerts"] == 1 and s2["worst_alert_severity"] == "Critical"
    assert (
        s2["inlet_temp"]["value"] == 24.0
        and s2["inlet_temp"]["unit"] == "°C"
        and s2["inlet_temp"]["age_s"] >= 0
    )
    assert body["used_u"] == 4 and body["free_u"] == 38 and body["power_w"] == 800.0


async def test_server_list_filters_and_sorts(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    h = tokens.headers()

    async def ids(query: str) -> list[int]:
        resp = await client.get(f"/api/v1/servers?{query}", headers=h)
        assert resp.status_code == 200, resp.text
        return [s["id"] for s in resp.json()["items"]]

    assert await ids("health=Critical") == [world.s2]
    assert await ids("vendor=dell") == [world.s1]
    assert await ids(f"rack_id={world.hyd_rack}") == [world.s3]
    assert await ids(f"room_id={world.pnq_room}&sort=rack") == [world.s1, world.s2]
    assert await ids("q=SN-HYD") == [world.s3]
    assert await ids("q=gcc-00002") == [world.s2]
    assert await ids("sort=health") == [world.s2, world.s3, world.s1]
    assert await ids("sort=-name") == [world.s1, world.s2, world.s3]
    assert await ids("sort=name") == [world.s3, world.s2, world.s1]
    assert await ids("status=decommissioned") == []


async def test_server_detail(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    body = (await client.get(f"/api/v1/servers/{world.s1}", headers=tokens.headers())).json()
    assert (
        body["name"] == "pnq1-a01-r750-01"
        and body["rack"]["name"] == "A01"
        and body["site"]["code"] == "PNQ1"
    )
    assert body["collector"] == {"id": world.pnq_col, "name": "pnq1-col-a", "online": True}
    assert {(p["metric"], p["component"]) for p in body["health_parts"]} == {
        ("system_health", ""),
        ("psu_health", "PSU 1"),
    }
    inlet = next(r for r in body["latest_readings"] if r["metric"] == "inlet_temp_c")
    assert inlet["unit"] == "°C" and inlet["value"] == 24.0
    assert [c["name"] for c in body["components"]] == ["CPU1", "PSU 1"]
    [bios] = body["firmware"]
    assert bios["approved_version"] == "1.15.2" and bios["compliant"] is False
    assert [e["entry_id"] for e in body["recent_events"]] == ["Sel/1", "Sel/0"]
    assert [a["id"] for a in body["active_alerts"]] == [world.a_event]


async def test_events_paginate(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    h = tokens.headers()
    first = (await client.get(f"/api/v1/servers/{world.s1}/events?limit=1", headers=h)).json()
    assert [e["entry_id"] for e in first["items"]] == ["Sel/1"] and first["next_cursor"]
    second = (
        await client.get(
            f"/api/v1/servers/{world.s1}/events?limit=1&cursor={first['next_cursor']}", headers=h
        )
    ).json()
    assert [e["entry_id"] for e in second["items"]] == ["Sel/0"] and second["next_cursor"] is None
    crit = (await client.get(f"/api/v1/servers/{world.s1}/events?severity=Critical", headers=h)).json()
    assert len(crit["items"]) == 1


async def test_cursor_walk_returns_every_row_once(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, db: AsyncSession
) -> None:
    for i in range(20):
        db.add(
            Server(
                site_id=world.pnq,
                rack_id=world.pnq_rack2,
                position_u=1 + i * 2,
                height_u=1,
                bmc_host=f"10.1.0.{i}",
                name="same-name" if i % 3 == 0 else f"srv-{i:02d}",
            )
        )
    await db.commit()
    h = tokens.headers()
    for sort in (
        "name",
        "-name",
        "health",
        "-health",
        "site",
        "rack",
        "vendor",
        "last_seen",
        "-last_seen",
        "id",
    ):
        seen: list[int] = []
        cursor: str | None = None
        while True:
            url = f"/api/v1/servers?limit=3&sort={sort}" + (f"&cursor={cursor}" if cursor else "")
            body = (await client.get(url, headers=h)).json()
            seen += [s["id"] for s in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert len(seen) == 23 and len(set(seen)) == 23, sort
    # A cursor from one sort cannot be used with another.
    body = (await client.get("/api/v1/servers?limit=3&sort=name", headers=h)).json()
    problem(await client.get(f"/api/v1/servers?sort=id&cursor={body['next_cursor']}", headers=h), 422)


async def test_onboarding(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, db: AsyncSession
) -> None:
    h = tokens.headers("engineer")
    body = {
        "bmc_host": "https://idrac-a02-07:443/",
        "rack_id": world.pnq_rack2,
        "position_u": 7,
        "height_u": 2,
        "name": "new-box",
        "asset_tag": "GCC-09999",
    }
    resp = await client.post("/api/v1/servers", headers=h, json=body)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["bmc_host"] == "https://idrac-a02-07:443"
    assert created["site"]["code"] == "PNQ1" and created["position_u"] == 7
    # Least-loaded collector at the site is chosen when none is given.
    assert created["collector_id"] == world.pnq_col2
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "server.create"))).scalar_one()
    assert (
        audit.object_id == str(created["id"])
        and audit.after
        and audit.after["bmc_host"] == str(body["bmc_host"]).rstrip("/")
    )

    # Duplicate BMC address.
    problem(await client.post("/api/v1/servers", headers=h, json=body), 409)
    # Overlap with U7-U8.
    clash = await client.post(
        "/api/v1/servers",
        headers=h,
        json={"bmc_host": "10.2.2.2", "rack_id": world.pnq_rack2, "position_u": 8},
    )
    assert problem(clash, 409)["conflict_server_id"] == created["id"]
    # Beyond the top of a 42U rack.
    problem(
        await client.post(
            "/api/v1/servers",
            headers=h,
            json={"bmc_host": "10.2.2.3", "rack_id": world.pnq_rack2, "position_u": 42, "height_u": 2},
        ),
        422,
    )
    # Collector from another site.
    problem(
        await client.post(
            "/api/v1/servers",
            headers=h,
            json={
                "bmc_host": "10.2.2.4",
                "rack_id": world.pnq_rack2,
                "position_u": 20,
                "collector_id": world.hyd_col,
            },
        ),
        422,
    )
    # Bad BMC address and unknown fields.
    problem(
        await client.post(
            "/api/v1/servers",
            headers=h,
            json={"bmc_host": "not a host!", "rack_id": world.pnq_rack2, "position_u": 20},
        ),
        422,
    )
    problem(
        await client.post(
            "/api/v1/servers",
            headers=h,
            json={"bmc_host": "10.2.2.5", "rack_id": world.pnq_rack2, "position_u": 20, "vendor": "x"},
        ),
        422,
    )


async def test_move_edit_and_decommission(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, db: AsyncSession
) -> None:
    h = tokens.headers("engineer")
    # Into s1's slot → conflict; to HYD1 → site and collector follow the rack.
    problem(await client.patch(f"/api/v1/servers/{world.s2}", headers=h, json={"position_u": 11}), 409)
    resp = await client.patch(
        f"/api/v1/servers/{world.s2}",
        headers=h,
        json={"rack_id": world.hyd_rack, "position_u": 20, "notes": "moved"},
    )
    assert resp.status_code == 200, resp.text
    moved = resp.json()
    assert (
        moved["site"]["code"] == "HYD1"
        and moved["collector_id"] == world.hyd_col
        and moved["notes"] == "moved"
    )
    entry = (await db.execute(select(AuditLog).where(AuditLog.action == "server.update"))).scalar_one()
    assert (
        entry.before
        and entry.before["rack_id"] == world.pnq_rack
        and entry.after
        and entry.after["position_u"] == 20
    )

    assert (await client.delete(f"/api/v1/servers/{world.s2}", headers=h)).status_code == 204
    listed = (await client.get("/api/v1/servers", headers=h)).json()["items"]
    assert world.s2 not in [s["id"] for s in listed]
    detail = (await client.get(f"/api/v1/servers/{world.s2}", headers=h)).json()
    assert detail["status"] == "decommissioned"
    # Its slot is free again.
    resp = await client.post(
        "/api/v1/servers",
        headers=h,
        json={"bmc_host": "10.3.3.3", "rack_id": world.hyd_rack, "position_u": 20},
    )
    assert resp.status_code == 201, resp.text


async def test_components_and_csv(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    h = tokens.headers("analyst")
    body = (await client.get("/api/v1/components?type=cpu", headers=h)).json()
    assert {(c["server_id"], c["name"]) for c in body["items"]} == {(world.s1, "CPU1"), (world.s3, "CPU1")}
    resp = await client.get("/api/v1/components/export.csv?type=psu", headers=h)
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    [row] = list(csv.DictReader(io.StringIO(resp.text)))
    assert row["model"] == "'=HYPERLINK(1)"  # formula injection neutralized
    resp = await client.get("/api/v1/servers/export.csv?sort=name", headers=h)
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert [r["id"] for r in rows] == [str(i) for i in (world.s3, world.s2, world.s1)]
    assert {r["health"] for r in rows} == {"OK", "Warning", "Critical"}


def test_resolution_choice() -> None:
    now = datetime(2026, 10, 22, 12, tzinfo=UTC)
    day = timedelta(days=1)
    assert choose_resolution(now - day, now, 60, None, now) == ("raw", 60, False)
    assert choose_resolution(now - timedelta(hours=26), now, 60, None, now) == ("raw", 120, True)
    assert choose_resolution(now - 3 * day, now, 60, None, now) == ("5m", 300, False)
    assert choose_resolution(now - 7 * day, now, 60, None, now) == ("5m", 600, True)
    assert choose_resolution(now - 30 * day, now, 60, None, now) == ("1h", 3600, False)
    assert choose_resolution(now - 365 * day, now, 60, None, now) == ("1h", 21600, True)
    # Raw data is never read for old ranges, even short ones.
    assert choose_resolution(now - 40 * day, now - 39 * day, 60, None, now)[0] == "5m"
    assert choose_resolution(now - day, now, 60, 900, now) == ("5m", 900, True)


async def test_readings_history(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, db: AsyncSession
) -> None:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    rows = [
        {
            "time": now - timedelta(minutes=i),
            "server_id": world.s1,
            "metric_code": 3,
            "component": comp,
            "value": 50.0 + (i % 10),
            "status": "OK",
        }
        for i in range(0, 3 * 24 * 60, 1)
        for comp in ("CPU1", "CPU2")
    ]
    await db.execute(insert(readings), rows)
    await db.commit()
    h = tokens.headers()
    base = f"/api/v1/servers/{world.s1}/readings?metric=cpu_temp_c"

    day = (await client.get(base, headers=h)).json()
    assert day["resolution"] == "raw" and day["unit"] == "°C"
    assert [s["component"] for s in day["series"]] == ["CPU1", "CPU2"]
    assert 1430 <= len(day["series"][0]["points"]) <= 1500

    frm = (now - timedelta(days=3)).isoformat().replace("+00:00", "Z")
    three = (await client.get(f"{base}&component=CPU1&from={frm}", headers=h)).json()
    assert three["resolution"] == "5m" and three["step_s"] == 300
    [series] = three["series"]
    assert 800 <= len(series["points"]) <= 1500
    point = series["points"][10]
    assert point["min"] <= point["v"] <= point["max"]

    frm = (now - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    month = (await client.get(f"{base}&component=CPU1&from={frm}", headers=h)).json()
    assert month["resolution"] == "1h" and 70 <= len(month["series"][0]["points"]) <= 74

    problem(await client.get(f"{base[:-11]}nope", headers=h), 422)
    problem(await client.get(f"{base}&from=2026-10-22T10:00:00Z&to=2026-10-22T09:00:00Z", headers=h), 422)


async def test_sites_rooms_racks_crud(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, db: AsyncSession
) -> None:
    admin = tokens.headers("admin")
    eng = tokens.headers("engineer")
    resp = await client.post(
        "/api/v1/sites",
        headers=admin,
        json={
            "code": "BLR1",
            "name": "Bengaluru",
            "city": "Bengaluru",
            "country": "India",
            "timezone": "Asia/Kolkata",
        },
    )
    assert resp.status_code == 201, resp.text
    site = resp.json()
    problem(
        await client.post(
            "/api/v1/sites", headers=admin, json={"code": "BLR1", "name": "x", "city": "x", "country": "x"}
        ),
        409,
    )
    problem(
        await client.post(
            "/api/v1/sites",
            headers=admin,
            json={"code": "BLR2", "name": "x", "city": "x", "country": "x", "timezone": "Mars/Base"},
        ),
        422,
    )
    room = (
        await client.post("/api/v1/rooms", headers=admin, json={"site_id": site["id"], "name": "Hall X"})
    ).json()
    rack = await client.post(
        "/api/v1/racks", headers=eng, json={"room_id": room["id"], "name": "X01", "height_u": 24}
    )
    assert rack.status_code == 201, rack.text
    rack_id = rack.json()["id"]
    assert (await client.patch(f"/api/v1/racks/{rack_id}", headers=eng, json={"height_u": 30})).json()[
        "height_u"
    ] == 30
    problem(await client.patch(f"/api/v1/racks/{world.pnq_rack}", headers=eng, json={"height_u": 12}), 409)
    problem(await client.delete(f"/api/v1/sites/{site['id']}", headers=admin), 409)
    problem(await client.delete(f"/api/v1/rooms/{room['id']}", headers=admin), 409)
    assert (await client.delete(f"/api/v1/racks/{rack_id}", headers=eng)).status_code == 204
    assert (await client.delete(f"/api/v1/rooms/{room['id']}", headers=admin)).status_code == 204
    patched = await client.patch(f"/api/v1/sites/{site['id']}", headers=admin, json={"name": "Bengaluru DC3"})
    assert patched.json()["name"] == "Bengaluru DC3"
    assert (await client.delete(f"/api/v1/sites/{site['id']}", headers=admin)).status_code == 204
    actions = [
        a
        for (a,) in (await db.execute(select(AuditLog.action).order_by(AuditLog.id))).all()
        if a != "user.login"
    ]
    assert actions == [
        "site.create",
        "room.create",
        "rack.create",
        "rack.update",
        "rack.delete",
        "room.delete",
        "site.update",
        "site.delete",
    ]
