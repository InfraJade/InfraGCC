"""Site scope: a site-limited user never sees another site's rows and gets 404 on direct access."""

from __future__ import annotations

import csv
import io

import httpx
import pytest

from tests.api.conftest import TokenFactory, World, problem

pytestmark = pytest.mark.db


async def test_lists_only_show_the_users_sites(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    h = tokens.headers("noc-pune")
    sites = (await client.get("/api/v1/sites", headers=h)).json()["items"]
    assert [s["code"] for s in sites] == ["PNQ1"]
    servers = (await client.get("/api/v1/servers", headers=h)).json()["items"]
    assert {s["id"] for s in servers} == {world.s1, world.s2}
    assert {s["site"]["code"] for s in servers} == {"PNQ1"}
    # Filtering by another site returns nothing rather than leaking it.
    assert (await client.get(f"/api/v1/servers?site_id={world.hyd}", headers=h)).json()["items"] == []
    alerts = (await client.get("/api/v1/alerts", headers=h)).json()["items"]
    assert {a["id"] for a in alerts} == {world.a_pnq, world.a_event}
    rooms = (await client.get("/api/v1/rooms", headers=h)).json()["items"]
    assert {r["site_code"] for r in rooms} == {"PNQ1"}
    racks = (await client.get("/api/v1/racks", headers=h)).json()["items"]
    assert {r["site_code"] for r in racks} == {"PNQ1"}
    comps = (await client.get("/api/v1/components", headers=h)).json()["items"]
    assert {c["site_code"] for c in comps} == {"PNQ1"}
    collectors = (await client.get("/api/v1/collectors", headers=h)).json()["items"]
    assert {c["site_code"] for c in collectors} == {"PNQ1"}
    windows = (await client.get("/api/v1/maintenance-windows", headers=h)).json()["items"]
    assert windows == []
    overview = (await client.get("/api/v1/overview", headers=h)).json()
    assert [s["code"] for s in overview["sites"]] == ["PNQ1"]
    assert overview["totals"]["server_count"] == 2
    search = (await client.get("/api/v1/search?q=SN-", headers=h)).json()
    assert {s["id"] for s in search["servers"]} == {world.s1, world.s2}
    fw = (await client.get("/api/v1/firmware/compliance", headers=h)).json()
    assert [i["server_id"] for i in fw["items"]] == [world.s1]


async def test_unrestricted_users_see_every_site(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    h = tokens.headers("viewer")
    assert len((await client.get("/api/v1/servers", headers=h)).json()["items"]) == 3
    assert len((await client.get("/api/v1/alerts", headers=h)).json()["items"]) == 3
    fw = (await client.get("/api/v1/firmware/compliance", headers=h)).json()
    assert {i["server_id"] for i in fw["items"]} == {world.s1, world.s3}


async def test_direct_access_outside_scope_is_404(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    h = tokens.headers("noc-pune")
    for path in (
        f"/api/v1/sites/{world.hyd}",
        f"/api/v1/rooms/{world.hyd_room}",
        f"/api/v1/racks/{world.hyd_rack}",
        f"/api/v1/servers/{world.s3}",
        f"/api/v1/servers/{world.s3}/readings?metric=inlet_temp_c",
        f"/api/v1/servers/{world.s3}/events",
        f"/api/v1/alerts/{world.a_hyd}",
        f"/api/v1/collectors/{world.hyd_col}",
        f"/api/v1/maintenance-windows/{world.mw_hyd}",
        f"/api/v1/thresholds?server_id={world.s3}",
    ):
        problem(await client.get(path, headers=h), 404)
    problem(await client.post(f"/api/v1/alerts/{world.a_hyd}/ack", headers=h, json={}), 404)
    problem(await client.post(f"/api/v1/alerts/{world.a_hyd}/comments", headers=h, json={"note": "x"}), 404)


async def test_site_limited_engineer_cannot_change_other_sites(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    h = tokens.headers("engineer-hyd")
    problem(await client.patch(f"/api/v1/servers/{world.s1}", headers=h, json={"notes": "x"}), 404)
    problem(await client.patch(f"/api/v1/racks/{world.pnq_rack}", headers=h, json={"row": "Z"}), 404)
    # Onboarding into a rack of another site: the rack is "unknown".
    resp = await client.post(
        "/api/v1/servers",
        headers=h,
        json={"bmc_host": "10.9.9.9", "rack_id": world.pnq_rack, "position_u": 30},
    )
    problem(resp, 422)
    # Moving its own server into a PNQ1 rack is refused the same way.
    problem(
        await client.patch(f"/api/v1/servers/{world.s3}", headers=h, json={"rack_id": world.pnq_rack}), 422
    )
    # Global settings need an unrestricted user.
    baseline = {"vendor": "Dell", "model": "PowerEdge R650", "component": "BIOS", "version": "1"}
    problem(await client.post("/api/v1/firmware/baselines", headers=h, json=baseline), 403)


async def test_site_limited_admin(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    h = tokens.headers("admin-pune")
    problem(await client.get("/api/v1/audit", headers=h), 403)
    problem(
        await client.post(
            "/api/v1/sites", headers=h, json={"code": "BLR1", "name": "B", "city": "B", "country": "IN"}
        ),
        403,
    )
    routes = (await client.get("/api/v1/alert-routes", headers=h)).json()["items"]
    assert [r["id"] for r in routes] == [world.route_pnq]
    resp = await client.post(
        "/api/v1/alert-routes",
        headers=h,
        json={"name": "All sites", "channel": "email", "target": "a@gcc.example"},
    )
    problem(resp, 403)


async def test_csv_export_is_site_scoped(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    resp = await client.get("/api/v1/servers/export.csv", headers=tokens.headers("noc-pune"))
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert {r["site"] for r in rows} == {"PNQ1"}
    resp = await client.get("/api/v1/components/export.csv", headers=tokens.headers("noc-pune"))
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert {r["site"] for r in rows} == {"PNQ1"}
