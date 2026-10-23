"""Token validation, problem+json errors, /me, sign-in auditing, rate limits, health endpoints."""

from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import AuditLog, User
from tests.api.conftest import TokenFactory, World, problem

pytestmark = pytest.mark.db


async def test_missing_token_is_401_problem(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/servers")
    body = problem(resp, 401)
    assert resp.headers["www-authenticate"].startswith("Bearer")
    assert body["instance"] == "/api/v1/servers"
    assert resp.headers["x-request-id"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expires_in": -120},
        {"audience": "someone-else"},
        {"issuer": "http://evil.example/realms/gcc"},
        {"kid": "unknown-kid"},
        {"key": rsa.generate_private_key(public_exponent=65537, key_size=2048)},
    ],
    ids=["expired", "audience", "issuer", "kid", "signature"],
)
async def test_bad_tokens_are_rejected(
    client: httpx.AsyncClient, tokens: TokenFactory, kwargs: dict[str, object]
) -> None:
    resp = await client.get("/api/v1/me", headers=tokens.headers("viewer", **kwargs))
    problem(resp, 401)


async def test_string_and_list_audiences_are_accepted(
    client: httpx.AsyncClient, tokens: TokenFactory
) -> None:
    assert (await client.get("/api/v1/me", headers=tokens.headers("viewer"))).status_code == 200
    headers = tokens.headers("viewer", audience_list=["account", "gcc-api"])
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 200
    problem(await client.get("/api/v1/me", headers=tokens.headers("viewer", audience_list=["account"])), 401)


async def test_malformed_token(client: httpx.AsyncClient) -> None:
    problem(await client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-jwt"}), 401)
    problem(await client.get("/api/v1/me", headers={"Authorization": "Basic abc"}), 401)


async def test_me_reports_roles_sites_and_capabilities(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    me = (await client.get("/api/v1/me", headers=tokens.headers("noc-pune"))).json()
    assert me["roles"] == ["noc_operator"]
    assert me["primary_role"] == "noc_operator"
    assert me["site_limited"] is True
    assert [s["code"] for s in me["sites"]] == ["PNQ1"]
    assert me["capabilities"]["ack_alerts"] is True
    assert me["capabilities"]["onboard_servers"] is False

    admin = (await client.get("/api/v1/me", headers=tokens.headers("admin"))).json()
    assert admin["sites"] is None and admin["site_limited"] is False
    assert admin["capabilities"]["view_audit"] is True

    analyst = (await client.get("/api/v1/me", headers=tokens.headers("analyst"))).json()
    assert analyst["capabilities"]["superset_editor"] is True
    assert analyst["capabilities"]["ack_alerts"] is False


async def test_user_without_role_can_see_me_but_nothing_else(
    client: httpx.AsyncClient, tokens: TokenFactory
) -> None:
    headers = tokens.headers("norole")
    assert (await client.get("/api/v1/me", headers=headers)).json()["roles"] == []
    body = problem(await client.get("/api/v1/servers", headers=headers), 403)
    assert "no Jade GCC role" in body["detail"]


async def test_full_path_groups_are_accepted(client: httpx.AsyncClient, tokens: TokenFactory) -> None:
    headers = tokens.headers("x", groups=["/gcc-dc-engineer", "/gcc-site-hyd1"])
    me = (await client.get("/api/v1/me", headers=headers)).json()
    assert me["roles"] == ["dc_engineer"]
    assert me["site_limited"] is True


async def test_login_is_upserted_and_audited_once_per_session(
    client: httpx.AsyncClient, tokens: TokenFactory, db: AsyncSession
) -> None:
    for _ in range(3):
        assert (
            await client.get("/api/v1/me", headers=tokens.headers("noc", sid="session-1"))
        ).status_code == 200
    await client.get("/api/v1/me", headers=tokens.headers("noc", sid="session-2"))
    users = (await db.execute(select(User))).scalars().all()
    assert [(u.sub, u.roles, u.sites, u.last_session) for u in users] == [
        ("sub-noc", ["noc_operator"], None, "session-2")
    ]
    logins = (await db.execute(select(AuditLog).where(AuditLog.action == "user.login"))).scalars().all()
    assert len(logins) == 2
    assert logins[0].user_sub == "sub-noc" and logins[0].request_id and logins[0].ip


async def test_rate_limit_returns_429_with_retry_after(
    client: httpx.AsyncClient, tokens: TokenFactory
) -> None:
    settings = get_settings()
    old = settings.rate_limit_per_minute
    settings.rate_limit_per_minute = 3
    try:
        headers = tokens.headers("viewer")
        for _ in range(3):
            assert (await client.get("/api/v1/me", headers=headers)).status_code == 200
        resp = await client.get("/api/v1/me", headers=headers)
        body = problem(resp, 429)
        assert int(resp.headers["retry-after"]) >= 1
        assert body["limit"] == 3
        # Limits are per user.
        assert (await client.get("/api/v1/me", headers=tokens.headers("noc"))).status_code == 200
    finally:
        settings.rate_limit_per_minute = old


async def test_rate_limit_fails_open_without_redis(client: httpx.AsyncClient, tokens: TokenFactory) -> None:
    from redis.asyncio import Redis

    from app.core import redis as redis_module

    original = redis_module.get_redis()
    redis_module.set_redis(Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2))
    try:
        assert (await client.get("/api/v1/me", headers=tokens.headers("viewer"))).status_code == 200
    finally:
        redis_module.set_redis(original)


async def test_validation_errors_are_422_problems(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    body = problem(await client.get("/api/v1/servers?limit=9999", headers=tokens.headers()), 422)
    assert body["errors"][0]["loc"] == ["query", "limit"]
    problem(await client.get("/api/v1/servers?cursor=garbage", headers=tokens.headers()), 422)
    problem(await client.get("/api/v1/servers?health=Purple", headers=tokens.headers()), 422)


async def test_not_found_is_404_problem(
    client: httpx.AsyncClient, tokens: TokenFactory, world: World
) -> None:
    problem(await client.get("/api/v1/servers/999999", headers=tokens.headers()), 404)
    problem(await client.get("/api/v1/nope", headers=tokens.headers()), 404)


async def test_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    resp = await client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert resp.json() == {"status": "ok"}
    assert resp.headers["x-request-id"] == "abc-123"
    resp = await client.get("/healthz", headers={"X-Request-ID": "bad id with spaces"})
    assert resp.headers["x-request-id"] != "bad id with spaces"


async def test_readyz_checks_database_and_redis(client: httpx.AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200, resp.text
    assert resp.json()["checks"] == {"database": "ok", "redis": "ok"}


async def test_cors_preflight(client: httpx.AsyncClient) -> None:
    resp = await client.options(
        "/api/v1/servers",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
