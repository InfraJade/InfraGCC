"""Role matrix: every endpoint refuses roles below its minimum (403) and admits its minimum and above."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from tests.api.conftest import TokenFactory, World

pytestmark = pytest.mark.db

V, N, E, A = "viewer", "noc", "engineer", "admin"
LEVEL = {V: 0, "analyst": 0, N: 1, E: 2, A: 3}

# (method, path builder, minimum role, json body)
Body = dict[str, Any] | Callable[[World], dict[str, Any]] | None
Case = tuple[str, Callable[[World], str], str, Body]

CASES: list[Case] = [
    ("GET", lambda w: "/api/v1/overview", V, None),
    ("GET", lambda w: "/api/v1/search?q=pnq", V, None),
    ("GET", lambda w: "/api/v1/metrics", V, None),
    ("GET", lambda w: "/api/v1/sites", V, None),
    ("GET", lambda w: f"/api/v1/sites/{w.pnq}", V, None),
    ("POST", lambda w: "/api/v1/sites", A, {"code": "BLR1", "name": "B", "city": "B", "country": "IN"}),
    ("PATCH", lambda w: f"/api/v1/sites/{w.pnq}", A, {"name": "Pune DC1"}),
    ("DELETE", lambda w: "/api/v1/sites/999999", A, None),
    ("GET", lambda w: "/api/v1/rooms", V, None),
    ("GET", lambda w: f"/api/v1/rooms/{w.pnq_room}", V, None),
    ("POST", lambda w: "/api/v1/rooms", A, lambda w: {"site_id": w.pnq, "name": "Hall Z"}),
    ("PATCH", lambda w: f"/api/v1/rooms/{w.pnq_room}", A, {"floor": "1"}),
    ("DELETE", lambda w: "/api/v1/rooms/999999", A, None),
    ("GET", lambda w: "/api/v1/racks", V, None),
    ("GET", lambda w: f"/api/v1/racks/{w.pnq_rack}", V, None),
    ("POST", lambda w: "/api/v1/racks", E, lambda w: {"room_id": w.pnq_room, "name": "Z99"}),
    ("PATCH", lambda w: f"/api/v1/racks/{w.pnq_rack}", E, {"row": "A"}),
    ("DELETE", lambda w: "/api/v1/racks/999999", E, None),
    ("GET", lambda w: "/api/v1/servers", V, None),
    ("GET", lambda w: "/api/v1/servers/export.csv", V, None),
    ("GET", lambda w: f"/api/v1/servers/{w.s1}", V, None),
    ("GET", lambda w: f"/api/v1/servers/{w.s1}/readings?metric=inlet_temp_c", V, None),
    ("GET", lambda w: f"/api/v1/servers/{w.s1}/events", V, None),
    ("POST", lambda w: "/api/v1/servers", E, {"bmc_host": "10.0.0.1", "rack_id": 999999, "position_u": 1}),
    ("PATCH", lambda w: f"/api/v1/servers/{w.s1}", E, {"notes": "checked"}),
    ("DELETE", lambda w: "/api/v1/servers/999999", E, None),
    ("GET", lambda w: "/api/v1/components", V, None),
    ("GET", lambda w: "/api/v1/components/export.csv", V, None),
    ("GET", lambda w: "/api/v1/alerts", V, None),
    ("GET", lambda w: f"/api/v1/alerts/{w.a_pnq}", V, None),
    ("POST", lambda w: f"/api/v1/alerts/{w.a_pnq}/comments", N, {"note": "looking"}),
    ("POST", lambda w: "/api/v1/alerts/999999/ack", N, {}),
    ("POST", lambda w: "/api/v1/alerts/999999/resolve", N, {}),
    ("GET", lambda w: "/api/v1/alert-rules", V, None),
    ("GET", lambda w: "/api/v1/alert-rules/999999", V, None),
    ("POST", lambda w: "/api/v1/alert-rules", A, {"name": "x", "rule_type": "threshold", "metric": "nope"}),
    ("PUT", lambda w: "/api/v1/alert-rules/999999", A, {"enabled": True}),
    ("PUT", lambda w: "/api/v1/alert-rules", A, {"items": [{"id": 999999, "enabled": True}]}),
    ("DELETE", lambda w: "/api/v1/alert-rules/999999", A, None),
    ("GET", lambda w: "/api/v1/thresholds", V, None),
    (
        "POST",
        lambda w: "/api/v1/thresholds",
        A,
        lambda w: {"metric": "nope", "scope": "site", "site_id": w.pnq, "warning": 1},
    ),
    (
        "PUT",
        lambda w: "/api/v1/thresholds",
        A,
        {"items": [{"metric": "nope", "scope": "global", "warning": 1}]},
    ),
    ("PUT", lambda w: "/api/v1/thresholds/999999", A, {"warning": 1}),
    ("DELETE", lambda w: "/api/v1/thresholds/999999", A, None),
    ("GET", lambda w: "/api/v1/alert-routes", A, None),
    ("GET", lambda w: f"/api/v1/alert-routes/{w.route_pnq}", A, None),
    ("POST", lambda w: "/api/v1/alert-routes", A, {"name": "x", "channel": "email", "target": "bad"}),
    ("PATCH", lambda w: "/api/v1/alert-routes/999999", A, {"enabled": False}),
    ("DELETE", lambda w: "/api/v1/alert-routes/999999", A, None),
    ("GET", lambda w: "/api/v1/maintenance-windows", V, None),
    ("GET", lambda w: f"/api/v1/maintenance-windows/{w.mw_hyd}", V, None),
    (
        "POST",
        lambda w: "/api/v1/maintenance-windows",
        E,
        {
            "scope": "site",
            "site_id": 999999,
            "starts_at": "2030-01-01T00:00:00Z",
            "ends_at": "2030-01-01T01:00:00Z",
            "reason": "x",
        },
    ),
    ("PATCH", lambda w: "/api/v1/maintenance-windows/999999", E, {"reason": "y"}),
    ("DELETE", lambda w: "/api/v1/maintenance-windows/999999", E, None),
    ("GET", lambda w: "/api/v1/collectors", V, None),
    ("GET", lambda w: f"/api/v1/collectors/{w.pnq_col}", V, None),
    ("POST", lambda w: "/api/v1/collectors", A, {"site_id": 999999, "name": "x"}),
    ("PATCH", lambda w: "/api/v1/collectors/999999", A, {"enabled": True}),
    ("GET", lambda w: "/api/v1/firmware/baselines", V, None),
    (
        "POST",
        lambda w: "/api/v1/firmware/baselines",
        E,
        {"vendor": "Dell", "model": "PowerEdge R750", "component": "BIOS", "version": "1"},
    ),
    ("PUT", lambda w: "/api/v1/firmware/baselines/999999", E, {"version": "2"}),
    ("DELETE", lambda w: "/api/v1/firmware/baselines/999999", E, None),
    ("GET", lambda w: "/api/v1/firmware/compliance", V, None),
    ("GET", lambda w: "/api/v1/users", A, None),
    ("GET", lambda w: "/api/v1/audit", A, None),
]


async def test_every_endpoint_is_covered(app: Any) -> None:
    routes = {
        (method.upper(), path)
        for path, ops in app.openapi()["paths"].items()
        if path.startswith("/api/v1") and not path.startswith(("/api/v1/superset", "/api/v1/me"))
        for method in ops
    }
    ids: dict[str, Any] = {f.name: 1 for f in dataclasses.fields(World) if f.name != "extra"}
    dummy = World(**ids)
    templates = {(m, re.sub(r"/\d+", "/{}", p(dummy).split("?")[0])) for m, p, _, _ in CASES}
    missing = [(m, p) for m, p in sorted(routes) if (m, re.sub(r"\{[a-z_]+\}", "{}", p)) not in templates]
    assert not missing, f"no RBAC case for {missing}"


async def test_role_matrix(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    failures: list[str] = []
    for method, path_fn, minimum, body in CASES:
        path = path_fn(world)
        for role in ("viewer", "analyst", "noc", "engineer", "admin"):
            payload = body(world) if callable(body) else body
            resp = await client.request(method, path, headers=tokens.headers(role), json=payload)
            allowed = LEVEL[role] >= LEVEL[minimum]
            if allowed and resp.status_code in (401, 403):
                failures.append(f"{role} refused {method} {path}: {resp.status_code} {resp.text[:200]}")
            if not allowed and resp.status_code != 403:
                failures.append(f"{role} allowed {method} {path}: {resp.status_code}")
            if resp.status_code >= 500:
                failures.append(f"{role} {method} {path}: {resp.status_code} {resp.text[:300]}")
    assert not failures, "\n".join(failures)
