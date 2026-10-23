"""Superset embedding: dashboard discovery and guest tokens (RLS for site-limited users), Superset mocked."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
import jwt
import pytest
import respx

from app.core.config import get_settings
from app.services.superset import DASHBOARDS
from tests.api.conftest import TokenFactory, World, problem

pytestmark = pytest.mark.db


def _uuid(slug: str) -> str:
    return f"00000000-0000-4000-8000-{abs(hash(slug)) % 10**12:012d}"


@pytest.fixture
def superset() -> Iterator[respx.MockRouter]:
    base = get_settings().superset_url.rstrip("/")
    exp = int(time.time()) + 900
    with respx.mock(base_url=base, assert_all_called=False) as mock:
        access = jwt.encode({"exp": exp, "sub": "1"}, "x", algorithm="HS256")
        mock.post("/api/v1/security/login").respond(200, json={"access_token": access})
        mock.get("/api/v1/security/csrf_token/").respond(200, json={"result": "csrf-1"})
        for i, slug in enumerate(DASHBOARDS, start=1):
            if slug == "inventory-firmware":
                mock.get(f"/api/v1/dashboard/{slug}").respond(404, json={"message": "Not found"})
                continue
            meta = json.dumps({"refresh_frequency": 600}) if slug == "thermal" else "{}"
            mock.get(f"/api/v1/dashboard/{slug}").respond(
                200, json={"result": {"id": i, "dashboard_title": slug.title(), "json_metadata": meta}}
            )
            mock.get(f"/api/v1/dashboard/{i}/embedded").respond(200, json={"result": {"uuid": _uuid(slug)}})
        guest = jwt.encode({"exp": int(time.time()) + 300, "type": "guest"}, "x", algorithm="HS256")
        mock.post("/api/v1/security/guest_token/", name="guest").respond(200, json={"token": guest})
        yield mock


async def test_dashboards(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, superset: respx.MockRouter
) -> None:
    resp = await client.get("/api/v1/superset/dashboards", headers=tokens.headers("viewer"))
    assert resp.status_code == 200, resp.text
    dashboards = {d["slug"]: d for d in resp.json()}
    assert set(dashboards) == set(DASHBOARDS) - {"inventory-firmware"}
    assert dashboards["thermal"]["refresh_s"] == 600
    assert dashboards["power-capacity"]["refresh_s"] == 900
    assert dashboards["dc-overview"]["embedded_uuid"] == _uuid("dc-overview")


def _guest_body(mock: respx.MockRouter) -> dict[str, Any]:
    request = mock.routes["guest"].calls.last.request
    assert request.headers["X-CSRFToken"] == "csrf-1"
    assert request.headers["Authorization"].startswith("Bearer ")
    body: dict[str, Any] = json.loads(request.content)
    return body


async def test_guest_token_has_rls_for_site_limited_users(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, superset: respx.MockRouter
) -> None:
    uuid = _uuid("thermal")
    resp = await client.post(
        "/api/v1/superset/guest-token", headers=tokens.headers("noc-pune"), json={"dashboard": uuid}
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert (
        out["superset_url"] == get_settings().superset_public_url.rstrip("/")
        and out["token"]
        and out["expires_at"]
    )
    body = _guest_body(superset)
    assert body["rls"] == [{"clause": f"site_id IN ({world.pnq})"}]
    assert body["resources"] == [{"type": "dashboard", "id": uuid}]
    assert body["user"]["username"] == "noc-pune"


async def test_guest_token_without_rls_for_unrestricted_users(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, superset: respx.MockRouter
) -> None:
    resp = await client.post(
        "/api/v1/superset/guest-token", headers=tokens.headers("analyst"), json={"dashboard": _uuid("alerts")}
    )
    assert resp.status_code == 200, resp.text
    assert _guest_body(superset)["rls"] == []


async def test_unknown_dashboard_is_404(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World, superset: respx.MockRouter
) -> None:
    problem(
        await client.post(
            "/api/v1/superset/guest-token", headers=tokens.headers(), json={"dashboard": "nope"}
        ),
        404,
    )


async def test_superset_down_is_503(client: httpx.AsyncClient, tokens: TokenFactory, world: World) -> None:
    base = get_settings().superset_url.rstrip("/")
    with respx.mock(base_url=base) as mock:
        mock.post("/api/v1/security/login").mock(side_effect=httpx.ConnectError("refused"))
        problem(await client.get("/api/v1/superset/dashboards", headers=tokens.headers()), 503)
        problem(
            await client.post(
                "/api/v1/superset/guest-token", headers=tokens.headers(), json={"dashboard": "x"}
            ),
            503,
        )


async def test_superset_requires_a_role(client: httpx.AsyncClient, tokens: TokenFactory) -> None:
    problem(await client.get("/api/v1/superset/dashboards", headers=tokens.headers("norole")), 403)
    problem(await client.get("/api/v1/superset/dashboards"), 401)
