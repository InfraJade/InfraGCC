"""Admin settings: alert rules, thresholds (+ BMC and effective limits), routes, maintenance, collectors,
baselines, firmware compliance, users and the audit log."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt
from app.models import AlertRoute, AuditLog, BmcThreshold, LatestReading
from tests.api.conftest import TokenFactory, World, problem

pytestmark = pytest.mark.db


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def test_alert_rules(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, db: AsyncSession
) -> None:
    admin = tokens.headers("admin")
    rules = (await client.get("/api/v1/alert-rules?limit=500", headers=tokens.headers())).json()["items"]
    assert len(rules) == 26 and all(r["builtin"] for r in rules)
    inlet = next(r for r in rules if r["name"] == "Inlet temperature high")
    resp = await client.put(
        f"/api/v1/alert-rules/{inlet['id']}", headers=admin, json={"duration_s": 240, "severity": "Critical"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["duration_s"] == 240 and resp.json()["updated_by"] == "Admin"
    # Restore (other suites rely on built-in defaults).
    await client.put(
        f"/api/v1/alert-rules/{inlet['id']}", headers=admin, json={"duration_s": 180, "severity": "Warning"}
    )

    custom = {
        "name": "Exhaust very hot",
        "rule_type": "threshold",
        "metric": "exhaust_temp_c",
        "condition": {"above": 60},
        "duration_s": 60,
        "severity": "Critical",
        "route": "facilities",
    }
    resp = await client.post("/api/v1/alert-rules", headers=admin, json=custom)
    assert resp.status_code == 201, resp.text
    rule_id = resp.json()["id"]
    problem(await client.post("/api/v1/alert-rules", headers=admin, json=custom), 409)
    problem(
        await client.post(
            "/api/v1/alert-rules", headers=admin, json={**custom, "name": "x", "metric": "psu_health"}
        ),
        422,
    )
    bulk = await client.put(
        "/api/v1/alert-rules", headers=admin, json={"items": [{"id": rule_id, "enabled": False}]}
    )
    assert bulk.json()["items"][0]["enabled"] is False
    problem(await client.delete(f"/api/v1/alert-rules/{inlet['id']}", headers=admin), 409)
    assert (await client.delete(f"/api/v1/alert-rules/{rule_id}", headers=admin)).status_code == 204
    actions = {a for (a,) in (await db.execute(select(AuditLog.action))).all()}
    assert {"alert_rule.update", "alert_rule.create", "alert_rule.delete"} <= actions


async def test_thresholds(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, db: AsyncSession
) -> None:
    admin = tokens.headers("admin")
    rows = (await client.get("/api/v1/thresholds?scope=global", headers=tokens.headers())).json()["items"]
    assert {r["metric"] for r in rows} == {"inlet_temp_c", "power_w", "psu_input_v", "drive_life_pct"}

    site = {"metric": "inlet_temp_c", "scope": "site", "site_id": world.pnq, "warning": 25, "critical": 32}
    resp = await client.post("/api/v1/thresholds", headers=admin, json=site)
    assert resp.status_code == 201, resp.text
    site_id = resp.json()["id"]
    problem(await client.post("/api/v1/thresholds", headers=admin, json=site), 409)
    problem(
        await client.post("/api/v1/thresholds", headers=admin, json={**site, "metric": "fan_health"}), 422
    )
    problem(await client.post("/api/v1/thresholds", headers=admin, json={**site, "site_id": None}), 422)
    problem(
        await client.post(
            "/api/v1/thresholds", headers=admin, json={**site, "warning": None, "critical": None}
        ),
        422,
    )

    bulk = await client.put(
        "/api/v1/thresholds",
        headers=admin,
        json={
            "items": [
                {**site, "warning": 26},
                {
                    "metric": "cpu_temp_c",
                    "scope": "server",
                    "server_id": world.s1,
                    "warning": 80,
                    "critical": 90,
                },
                {
                    "metric": "cpu_temp_c",
                    "scope": "model",
                    "vendor": "Dell",
                    "model": "PowerEdge R750",
                    "warning": 85,
                },
            ]
        },
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["items"][0]["warning"] == 26

    db.add(
        BmcThreshold(
            server_id=world.s1, metric_code=4, component="DIMM A1", upper_warning=80, upper_critical=85
        )
    )
    db.add(
        LatestReading(server_id=world.s1, metric_code=3, component="CPU1", value=55, time=datetime.now(UTC))
    )
    db.add(
        LatestReading(
            server_id=world.s1, metric_code=4, component="DIMM A1", value=40, time=datetime.now(UTC)
        )
    )
    await db.commit()
    body = (await client.get(f"/api/v1/thresholds?server_id={world.s1}", headers=tokens.headers())).json()
    assert {(r["scope"], r["metric"]) for r in body["items"]} >= {
        ("site", "inlet_temp_c"),
        ("server", "cpu_temp_c"),
        ("model", "cpu_temp_c"),
    }
    assert body["bmc_limits"][0]["component"] == "DIMM A1"
    effective = {(e["metric"], e["component"]): e for e in body["effective"]}
    assert (
        effective[("inlet_temp_c", "")]["source"] == "site"
        and effective[("inlet_temp_c", "")]["warning"] == 26
    )
    assert effective[("cpu_temp_c", "CPU1")]["source"] == "server"
    assert effective[("dimm_temp_c", "DIMM A1")]["source"] == "bmc"
    assert effective[("power_w", "")]["source"] == "global"

    upd = await client.put(
        f"/api/v1/thresholds/{site_id}", headers=admin, json={"warning": 24, "critical": 30}
    )
    assert upd.json()["critical"] == 30
    glob = next(r for r in rows if r["metric"] == "inlet_temp_c")
    problem(await client.delete(f"/api/v1/thresholds/{glob['id']}", headers=admin), 409)
    assert (await client.delete(f"/api/v1/thresholds/{site_id}", headers=admin)).status_code == 204
    # Site-limited admins may not touch global or model rows.
    problem(
        await client.put(
            f"/api/v1/thresholds/{glob['id']}", headers=tokens.headers("admin-pune"), json={"warning": 1}
        ),
        403,
    )


async def test_alert_routes_store_targets_encrypted(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, db: AsyncSession
) -> None:
    admin = tokens.headers("admin")
    resp = await client.post(
        "/api/v1/alert-routes",
        headers=admin,
        json={
            "name": "HYD on-call",
            "site_id": world.hyd,
            "min_severity": "Warning",
            "channel": "email",
            "target": "oncall@gcc.example; Lead@GCC.example",
        },
    )
    assert resp.status_code == 201, resp.text
    route = resp.json()
    assert "target" not in route and "target_encrypted" not in route
    assert route["target_hint"] == "oncall@gcc.example, Lead@gcc.example"
    row = await db.get(AlertRoute, route["id"])
    assert row is not None and decrypt(row.target_encrypted) == "oncall@gcc.example, Lead@gcc.example"
    problem(
        await client.post(
            "/api/v1/alert-routes", headers=admin, json={"name": "x", "channel": "email", "target": "nope"}
        ),
        422,
    )
    problem(
        await client.post(
            "/api/v1/alert-routes", headers=admin, json={"name": "x", "channel": "teams", "target": "ftp://x"}
        ),
        422,
    )
    upd = await client.patch(
        f"/api/v1/alert-routes/{route['id']}",
        headers=admin,
        json={"channel": "teams", "target": "https://teams.example/hooks/abc/secret"},
    )
    assert upd.json()["target_hint"] == "https://teams.example/…"
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "alert_route.update"))).scalar_one()
    assert "secret" not in str(audit.before) + str(audit.after)
    assert (await client.delete(f"/api/v1/alert-routes/{route['id']}", headers=admin)).status_code == 204


async def test_maintenance_windows(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    eng = tokens.headers("engineer-hyd")
    now = datetime.now(UTC)
    body = {
        "scope": "server",
        "server_id": world.s3,
        "starts_at": _iso(now - timedelta(hours=1)),
        "ends_at": _iso(now + timedelta(hours=1)),
        "reason": "DIMM swap",
    }
    resp = await client.post("/api/v1/maintenance-windows", headers=eng, json=body)
    assert resp.status_code == 201, resp.text
    mw = resp.json()
    assert (
        mw["active"] is True
        and mw["target_site_id"] == world.hyd
        and mw["target_name"] == "hyd1-c01-sr650-03"
    )
    problem(
        await client.post("/api/v1/maintenance-windows", headers=eng, json={**body, "server_id": world.s1}),
        422,
    )
    problem(
        await client.post(
            "/api/v1/maintenance-windows", headers=eng, json={**body, "ends_at": body["starts_at"]}
        ),
        422,
    )
    problem(
        await client.post(
            "/api/v1/maintenance-windows", headers=eng, json={**body, "rack_id": world.hyd_rack}
        ),
        422,
    )
    active = (await client.get("/api/v1/maintenance-windows?when=active", headers=eng)).json()["items"]
    assert [w["id"] for w in active] == [mw["id"]]
    upcoming = (await client.get("/api/v1/maintenance-windows?when=upcoming", headers=eng)).json()["items"]
    assert [w["id"] for w in upcoming] == [world.mw_hyd]
    assert upcoming[0]["target_name"] == "HYD1 / C01"
    upd = await client.patch(
        f"/api/v1/maintenance-windows/{mw['id']}", headers=eng, json={"reason": "DIMM + fan swap"}
    )
    assert upd.json()["reason"] == "DIMM + fan swap"
    problem(
        await client.patch(
            f"/api/v1/maintenance-windows/{mw['id']}",
            headers=eng,
            json={"ends_at": _iso(now - timedelta(hours=2))},
        ),
        422,
    )
    assert (await client.delete(f"/api/v1/maintenance-windows/{mw['id']}", headers=eng)).status_code == 204


async def test_collectors(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    admin = tokens.headers("admin")
    items = (await client.get("/api/v1/collectors", headers=tokens.headers())).json()["items"]
    by_name = {c["name"]: c for c in items}
    assert by_name["pnq1-col-a"]["online"] is True and by_name["pnq1-col-a"]["servers_preferred"] == 2
    assert by_name["hyd1-col-a"]["online"] is False and by_name["hyd1-col-a"]["heartbeat_age_s"] >= 600
    resp = await client.post(
        "/api/v1/collectors", headers=admin, json={"site_id": world.hyd, "name": "hyd1-col-b"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["online"] is False
    problem(
        await client.post(
            "/api/v1/collectors", headers=admin, json={"site_id": world.hyd, "name": "hyd1-col-b"}
        ),
        409,
    )
    upd = await client.patch(
        f"/api/v1/collectors/{resp.json()['id']}",
        headers=admin,
        json={"enabled": False, "cert_fingerprint": "AB:CD"},
    )
    assert upd.json()["enabled"] is False and upd.json()["cert_fingerprint"] == "AB:CD"


async def test_baselines_and_compliance(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    eng = tokens.headers("engineer")
    body = (await client.get("/api/v1/firmware/compliance", headers=tokens.headers())).json()
    assert body["summary"] == {
        "servers_with_firmware": 2,
        "servers_checked": 2,
        "servers_compliant": 0,
        "servers_off_baseline": 2,
        "components_off_baseline": 2,
        "models_without_baseline": 0,
    }
    pnq = next(i for i in body["items"] if i["server_id"] == world.s1)
    assert (
        pnq["differences"][0]["installed_version"] == "1.14.0"
        and pnq["differences"][0]["approved_version"] == "1.15.2"
    )

    resp = await client.put(
        f"/api/v1/firmware/baselines/{world.baseline_bios}", headers=eng, json={"version": "1.14.0"}
    )
    assert resp.status_code == 200 and resp.json()["updated_by"] == "Engineer"
    body = (await client.get("/api/v1/firmware/compliance", headers=tokens.headers())).json()
    assert body["summary"]["servers_compliant"] == 1 and [i["server_id"] for i in body["items"]] == [world.s3]
    created = await client.post(
        "/api/v1/firmware/baselines",
        headers=eng,
        json={"vendor": "Dell", "model": "PowerEdge R750", "component": "BMC", "version": "7.10.70.00"},
    )
    assert created.status_code == 201
    problem(
        await client.post(
            "/api/v1/firmware/baselines",
            headers=eng,
            json={"vendor": "Dell", "model": "PowerEdge R750", "component": "BMC", "version": "1"},
        ),
        409,
    )
    listed = (await client.get("/api/v1/firmware/baselines?vendor=Dell", headers=eng)).json()["items"]
    assert [b["component"] for b in listed] == ["BIOS", "BMC"]
    assert (
        await client.delete(f"/api/v1/firmware/baselines/{created.json()['id']}", headers=eng)
    ).status_code == 204


async def test_users_and_audit(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    for name in ("viewer", "noc-pune", "engineer-hyd"):
        await client.get("/api/v1/me", headers=tokens.headers(name))
    admin = tokens.headers("admin")
    users = (await client.get("/api/v1/users", headers=admin)).json()["items"]
    assert {u["sub"] for u in users} == {"sub-viewer", "sub-noc-pune", "sub-engineer-hyd", "sub-admin"}
    noc = next(u for u in users if u["sub"] == "sub-noc-pune")
    assert noc["sites"] == ["PNQ1"] and noc["roles"] == ["noc_operator"]
    ops = (await client.get("/api/v1/users?role=noc_operator", headers=admin)).json()["items"]
    assert [u["sub"] for u in ops] == ["sub-noc-pune"]
    pune_users = (await client.get("/api/v1/users", headers=tokens.headers("admin-pune"))).json()["items"]
    assert {u["sub"] for u in pune_users} == {"sub-noc-pune", "sub-admin-pune"}

    await client.post(f"/api/v1/alerts/{world.a_pnq}/ack", headers=tokens.headers("noc"), json={})
    logins = (await client.get("/api/v1/audit?action=user.login", headers=admin)).json()["items"]
    assert len(logins) >= 4
    acks = (await client.get(f"/api/v1/audit?action=alert.&object_id={world.a_pnq}", headers=admin)).json()[
        "items"
    ]
    assert [(a["action"], a["user_name"]) for a in acks] == [("alert.ack", "Noc")]
    page = (await client.get("/api/v1/audit?limit=2", headers=admin)).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    times = [a["time"] for a in page["items"]]
    assert times == sorted(times, reverse=True)
