"""App API test fixtures: signed test tokens, fake Redis, an ASGI client and a small two-site world.

Run with `TEST_DATABASE_NAME=gcc_test_api` so parallel suites don't drop each other's database.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis
import httpx
import jwt
import pytest
from asgi_lifespan import LifespanManager
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core import redis as redis_module
from app.core.config import get_settings
from app.core.crypto import encrypt, mask_target
from app.core.security import TokenValidator, reset_security_caches, set_token_validator
from app.models import (
    Alert,
    AlertRoute,
    AlertRule,
    Collector,
    Component,
    Event,
    FirmwareBaseline,
    FirmwareInventory,
    HealthStatus,
    LatestReading,
    MaintenanceWindow,
    Rack,
    Room,
    Server,
    Site,
)
from app.services import superset as superset_module
from app.services.live_hub import hub

KID = "test-key-1"
ISSUER = "http://localhost:8080/realms/gcc"
AUDIENCE = "gcc-api"


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticJWKClient(jwt.PyJWKClient):
    """A JWKS client that serves the test key instead of fetching from Keycloak."""

    def __init__(self, key: rsa.RSAPrivateKey) -> None:
        super().__init__("http://keycloak.test/realms/gcc/protocol/openid-connect/certs", cache_keys=True)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
        self._jwks = {"keys": [jwk]}

    def fetch_data(self) -> Any:
        return self._jwks


# username → (groups, display name)
USERS: dict[str, list[str]] = {
    "viewer": ["gcc-viewer"],
    "analyst": ["gcc-analyst"],
    "noc": ["gcc-noc-operator"],
    "engineer": ["gcc-dc-engineer"],
    "admin": ["gcc-platform-admin"],
    "noc-pune": ["gcc-noc-operator", "gcc-site-PNQ1"],
    "engineer-hyd": ["gcc-dc-engineer", "gcc-site-HYD1"],
    "admin-pune": ["gcc-platform-admin", "gcc-site-PNQ1"],
    "norole": [],
}


@dataclass
class TokenFactory:
    key: rsa.RSAPrivateKey

    def __call__(
        self,
        username: str = "viewer",
        *,
        groups: list[str] | None = None,
        sid: str | None = None,
        expires_in: int = 300,
        audience: str = AUDIENCE,
        audience_list: list[str] | None = None,
        issuer: str = ISSUER,
        kid: str = KID,
        key: rsa.RSAPrivateKey | None = None,
    ) -> str:
        now = int(time.time())
        claims = {
            "sub": f"sub-{username}",
            "preferred_username": username,
            "name": username.replace("-", " ").title(),
            "email": f"{username}@gcc.example",
            "groups": USERS.get(username, []) if groups is None else groups,
            "sid": sid or uuid.uuid4().hex,
            "iss": issuer,
            "aud": audience_list or audience,  # Keycloak sends a single string
            "iat": now,
            "exp": now + expires_in,
        }
        return jwt.encode(claims, key or self.key, algorithm="RS256", headers={"kid": kid})

    def headers(self, username: str = "viewer", **kwargs: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self(username, **kwargs)}"}


@pytest.fixture
def tokens(rsa_key: rsa.RSAPrivateKey) -> TokenFactory:
    return TokenFactory(rsa_key)


@pytest.fixture
def fake_redis() -> Iterator[fakeredis.FakeAsyncRedis]:
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    redis_module.set_redis(client)
    yield client
    redis_module.set_redis(None)


@pytest.fixture
async def app(
    clean_db: AsyncEngine, rsa_key: rsa.RSAPrivateKey, fake_redis: fakeredis.FakeAsyncRedis
) -> AsyncIterator[FastAPI]:
    from app.api.main import app as fastapi_app

    set_token_validator(TokenValidator(get_settings(), jwks_client=StaticJWKClient(rsa_key)))
    reset_security_caches()
    superset_module.set_superset(None)
    async with LifespanManager(fastapi_app):
        await asyncio.wait_for(hub.wait_ready(), 5)
        yield fastapi_app
    set_token_validator(None)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def db(clean_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(clean_db, expire_on_commit=False)() as s:
        yield s


# --------------------------------------------------------------------------------------------- world


@dataclass
class World:
    pnq: int
    hyd: int
    pnq_room: int
    hyd_room: int
    pnq_rack: int
    pnq_rack2: int
    hyd_rack: int
    pnq_col: int
    pnq_col2: int
    hyd_col: int
    s1: int  # PNQ1, OK, Dell R750
    s2: int  # PNQ1, Critical
    s3: int  # HYD1, Warning
    a_pnq: int  # threshold alert, open, Critical, on s2
    a_hyd: int  # threshold alert, open, Warning, on s3
    a_event: int  # event alert, open, on s1
    mw_hyd: int
    route_pnq: int
    baseline_bios: int
    extra: dict[str, int] = field(default_factory=dict)


async def _rule(session: AsyncSession, name: str) -> AlertRule:
    from sqlalchemy import select

    return (await session.execute(select(AlertRule).where(AlertRule.name == name))).scalar_one()


async def build_world(session: AsyncSession) -> World:
    now = datetime.now(UTC)
    pnq = Site(code="PNQ1", name="Pune DC1", city="Pune", country="India", timezone="Asia/Kolkata")
    hyd = Site(code="HYD1", name="Hyderabad DC2", city="Hyderabad", country="India", timezone="Asia/Kolkata")
    session.add_all([pnq, hyd])
    await session.flush()
    pnq_room = Room(site_id=pnq.id, name="Hall A", floor="Ground")
    hyd_room = Room(site_id=hyd.id, name="Hall 1", floor="Ground")
    session.add_all([pnq_room, hyd_room])
    await session.flush()
    pnq_rack = Rack(room_id=pnq_room.id, name="A01", row="A", height_u=42, power_capacity_w=8000)
    pnq_rack2 = Rack(room_id=pnq_room.id, name="A02", row="A", height_u=42, power_capacity_w=8000)
    hyd_rack = Rack(room_id=hyd_room.id, name="C01", row="C", height_u=42, power_capacity_w=8000)
    session.add_all([pnq_rack, pnq_rack2, hyd_rack])
    pnq_col = Collector(site_id=pnq.id, name="pnq1-col-a", last_heartbeat=now, version="1.0.0")
    pnq_col2 = Collector(site_id=pnq.id, name="pnq1-col-b")
    hyd_col = Collector(site_id=hyd.id, name="hyd1-col-a", last_heartbeat=now - timedelta(minutes=10))
    session.add_all([pnq_col, pnq_col2, hyd_col])
    await session.flush()

    def server(site: Site, rack: Rack, pos: int, host: str, col: Collector, **kw: Any) -> Server:
        return Server(
            site_id=site.id,
            rack_id=rack.id,
            position_u=pos,
            height_u=2,
            bmc_host=host,
            collector_id=col.id,
            **kw,
        )

    s1 = server(
        pnq,
        pnq_rack,
        10,
        "http://bmc-simulator:20001",
        pnq_col,
        name="pnq1-a01-r750-01",
        vendor="Dell",
        model="PowerEdge R750",
        serial="SN-PNQ-1",
        asset_tag="GCC-00001",
        last_seen_at=now,
    )
    s2 = server(
        pnq,
        pnq_rack,
        14,
        "http://bmc-simulator:20002",
        pnq_col,
        name="pnq1-a01-dl380-02",
        vendor="HPE",
        model="ProLiant DL380 Gen10",
        serial="SN-PNQ-2",
        asset_tag="GCC-00002",
    )
    s3 = server(
        hyd,
        hyd_rack,
        10,
        "http://bmc-simulator:20003",
        hyd_col,
        name="hyd1-c01-sr650-03",
        vendor="Lenovo",
        model="ThinkSystem SR650 V3",
        serial="SN-HYD-3",
        asset_tag="GCC-00003",
    )
    session.add_all([s1, s2, s3])
    await session.flush()

    metric = {"inlet": 1, "power": 9, "system_health": 16, "psu_health": 12, "cpu_temp": 3}
    for srv, health in ((s1, "OK"), (s2, "Critical"), (s3, "Warning")):
        session.add(
            HealthStatus(
                server_id=srv.id,
                metric_code=metric["system_health"],
                component="",
                health=health,
                state=health,
                since=now - timedelta(hours=1),
                updated_at=now,
            )
        )
        session.add(
            LatestReading(
                server_id=srv.id,
                metric_code=metric["inlet"],
                component="",
                value=24.0,
                status="OK",
                time=now - timedelta(seconds=30),
            )
        )
        session.add(
            LatestReading(
                server_id=srv.id,
                metric_code=metric["power"],
                component="",
                value=400.0,
                status=None,
                time=now - timedelta(seconds=30),
            )
        )
    session.add(
        HealthStatus(
            server_id=s1.id,
            metric_code=metric["psu_health"],
            component="PSU 1",
            health="OK",
            state="OK",
            since=now,
            updated_at=now,
        )
    )
    session.add_all(
        [
            Component(
                server_id=s1.id,
                type="cpu",
                name="CPU1",
                model="Xeon Gold 6338",
                manufacturer="Intel",
                serial="CPU-1",
                capacity=32,
                capacity_unit="cores",
            ),
            Component(
                server_id=s1.id,
                type="psu",
                name="PSU 1",
                model="=HYPERLINK(1)",
                manufacturer="Delta",
                serial="PSU-1",
                capacity=1400,
                capacity_unit="W",
            ),
            Component(
                server_id=s3.id,
                type="cpu",
                name="CPU1",
                model="Xeon Gold 6430",
                manufacturer="Intel",
                serial="CPU-3",
                capacity=32,
                capacity_unit="cores",
            ),
        ]
    )
    session.add_all(
        [
            Event(
                server_id=s1.id,
                time=now - timedelta(minutes=5),
                severity="Critical",
                message="Inlet hot",
                message_id="TMP0120",
                entry_id="Sel/1",
            ),
            Event(
                server_id=s1.id,
                time=now - timedelta(minutes=50),
                severity="OK",
                message="Log cleared",
                message_id="SEL0001",
                entry_id="Sel/0",
            ),
        ]
    )
    baseline = FirmwareBaseline(vendor="Dell", model="PowerEdge R750", component="BIOS", version="1.15.2")
    session.add_all(
        [
            baseline,
            FirmwareBaseline(
                vendor="Lenovo", model="ThinkSystem SR650 V3", component="BIOS", version="ESE124B-3.10"
            ),
            FirmwareInventory(
                server_id=s1.id,
                component="BIOS",
                component_key="BIOS",
                component_type="bios",
                version="1.14.0",
                collected_at=now,
            ),
            FirmwareInventory(
                server_id=s3.id,
                component="BIOS",
                component_key="BIOS",
                component_type="bios",
                version="ESE124B-3.00",
                collected_at=now,
            ),
        ]
    )
    inlet_rule = await _rule(session, "Inlet temperature high")
    event_rule = await _rule(session, "Critical system event")
    a_pnq = Alert(
        rule_id=inlet_rule.id,
        server_id=s2.id,
        site_id=pnq.id,
        metric_code=1,
        component="",
        dedupe_key=f"{s2.id}:1:",
        severity="Critical",
        title="Inlet temperature high on s2",
        opened_at=now - timedelta(minutes=10),
        value=36.0,
        threshold=35.0,
    )
    a_hyd = Alert(
        rule_id=inlet_rule.id,
        server_id=s3.id,
        site_id=hyd.id,
        metric_code=1,
        component="",
        dedupe_key=f"{s3.id}:1:",
        severity="Warning",
        title="Inlet temperature high on s3",
        opened_at=now - timedelta(minutes=5),
    )
    a_event = Alert(
        rule_id=event_rule.id,
        server_id=s1.id,
        site_id=pnq.id,
        metric_code=26,
        component="",
        dedupe_key=f"{s1.id}:event:TMP0120",
        severity="Critical",
        title="Critical event on s1",
        opened_at=now - timedelta(minutes=2),
    )
    session.add_all([a_pnq, a_hyd, a_event])
    mw = MaintenanceWindow(
        scope="rack",
        rack_id=hyd_rack.id,
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=4),
        reason="PDU swap",
        created_by="seed",
    )
    target = "https://teams.example/webhook/pnq"
    route = AlertRoute(
        name="Pune Teams",
        route="*",
        site_id=pnq.id,
        min_severity="Warning",
        channel="teams",
        target_encrypted=encrypt(target),
        target_hint=mask_target("teams", target),
    )
    session.add_all([mw, route])
    await session.commit()
    return World(
        pnq=pnq.id,
        hyd=hyd.id,
        pnq_room=pnq_room.id,
        hyd_room=hyd_room.id,
        pnq_rack=pnq_rack.id,
        pnq_rack2=pnq_rack2.id,
        hyd_rack=hyd_rack.id,
        pnq_col=pnq_col.id,
        pnq_col2=pnq_col2.id,
        hyd_col=hyd_col.id,
        s1=s1.id,
        s2=s2.id,
        s3=s3.id,
        a_pnq=a_pnq.id,
        a_hyd=a_hyd.id,
        a_event=a_event.id,
        mw_hyd=mw.id,
        route_pnq=route.id,
        baseline_bios=baseline.id,
    )


@pytest.fixture
async def world(app: FastAPI, db: AsyncSession) -> World:
    return await build_world(db)


def problem(resp: httpx.Response, status: int) -> dict[str, Any]:
    """Assert an RFC 9457 response with `status` and return its body."""
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json"), resp.headers
    body: dict[str, Any] = resp.json()
    assert body["status"] == status
    assert body["type"].startswith("https://") and body["title"]
    return body
