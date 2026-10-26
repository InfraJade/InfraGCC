"""Fixtures shared by the ingest, alert and worker tests (imported by their conftest.py files).

Database work runs as the real least-privilege roles: the ingest API as `gcc_ingest`, the alert engine and jobs
as `gcc_app` (the owner session only builds test data). Redis is fakeredis; Celery is replaced by a recorder.
"""

from __future__ import annotations

import gzip
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import fakeredis
import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app import seed
from app.core import db
from app.core.redis import set_redis
from app.ingest.catalog import clear_catalog_cache
from app.models import Collector, Rack, Server, Site

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_EXAMPLE = REPO_ROOT / "docs" / "contracts" / "ingest-batch.example.json"
TOKEN = "dev-ingest-token"


def role_engine(url: str, role: str) -> AsyncEngine:
    """An engine whose connections run as `role` (the owner logs in, the server switches role at startup)."""
    return create_async_engine(
        url, pool_size=3, max_overflow=3, connect_args={"server_settings": {"role": role}}
    )


@pytest.fixture(scope="session")
async def ingest_engine(database_url: str, engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    eng = role_engine(database_url, "gcc_ingest")
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
async def app_engine(database_url: str, engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    eng = role_engine(database_url, "gcc_app")
    yield eng
    await eng.dispose()


@pytest.fixture
async def fake_redis() -> AsyncIterator[fakeredis.FakeAsyncRedis]:
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    set_redis(client)
    yield client
    set_redis(None)
    await client.aclose()


@dataclass
class TaskRecorder:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    fail: bool = False

    def __call__(self, name: str, **kwargs: Any) -> None:
        if self.fail:
            raise ConnectionError("broker down")
        self.calls.append((name, kwargs))

    def server_ids(self) -> list[int]:
        return sorted(sid for _, kw in self.calls for sid in kw["args"][0])


@dataclass(frozen=True)
class Ref:
    """Plain ids of a row created for a test (ORM objects expire when test sessions roll back)."""

    id: int
    name: str = ""
    site_id: int | None = None
    rack_id: int | None = None
    collector_id: int | None = None


@dataclass
class World:
    sites: dict[str, Ref]
    racks: dict[str, Ref]
    collectors: dict[str, Ref]
    servers: list[Ref]

    def server(self, index: int) -> Ref:
        return self.servers[index]


async def build_world(session: AsyncSession) -> World:
    """PNQ1: 4 servers on pnq1-col-a, 4 on pnq1-col-b; HYD1: 2 servers on hyd1-col-a. All collectors live."""
    racks_by_site = await seed.seed_topology(session)
    sites = {s.code: s for s in (await session.execute(select(Site))).scalars()}
    collectors = {c.name: c for c in (await session.execute(select(Collector))).scalars()}
    now = datetime.now(UTC)
    for c in collectors.values():
        c.last_heartbeat = now
    servers: list[Server] = []
    plan = [("PNQ1", "pnq1-col-a")] * 4 + [("PNQ1", "pnq1-col-b")] * 4 + [("HYD1", "hyd1-col-a")] * 2
    for i, (site_code, collector_name) in enumerate(plan):
        rack = racks_by_site[site_code][0]
        server = Server(
            site_id=sites[site_code].id,
            rack_id=rack.id,
            position_u=2 + i * 3,
            height_u=2,
            bmc_host=f"http://bmc-test:{20001 + i}",
            collector_id=collectors[collector_name].id,
            name=f"srv-{i + 1:02d}",
        )
        session.add(server)
        servers.append(server)
    await session.flush()
    racks = {r.name: Ref(r.id, r.name) for r in (await session.execute(select(Rack))).scalars()}
    world = World(
        sites={code: Ref(s.id, s.name) for code, s in sites.items()},
        racks=racks,
        collectors={name: Ref(c.id, name, c.site_id) for name, c in collectors.items()},
        servers=[Ref(s.id, s.name or "", s.site_id, s.rack_id, s.collector_id) for s in servers],
    )
    await session.commit()
    return world


@pytest.fixture
async def world(session: AsyncSession) -> World:
    clear_catalog_cache()
    return await build_world(session)


@pytest.fixture
def use_app_engine(app_engine: AsyncEngine, engine: AsyncEngine) -> Iterator[AsyncEngine]:
    """Point app.core.db at the gcc_app role for the test, then back at the owner engine."""
    db.set_engine(app_engine)
    yield app_engine
    db.set_engine(engine)


@pytest.fixture
def tasks(monkeypatch: pytest.MonkeyPatch) -> TaskRecorder:
    recorder = TaskRecorder()
    monkeypatch.setattr("app.worker.enqueue._default_sender", lambda: recorder)
    return recorder


@pytest.fixture
async def ingest_client(
    world: World,
    fake_redis: fakeredis.FakeAsyncRedis,
    ingest_engine: AsyncEngine,
    engine: AsyncEngine,
    tasks: TaskRecorder,
) -> AsyncIterator[httpx.AsyncClient]:
    from app.ingest.main import app

    db.set_engine(ingest_engine)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://ingest") as client:
        yield client
    db.set_engine(engine)


def headers(collector: str = "pnq1-col-a", token: str = TOKEN, gzip_body: bool = False) -> dict[str, str]:
    out = {
        "Authorization": f"Bearer {token}",
        "X-Collector-Name": collector,
        "Content-Type": "application/json",
    }
    if gzip_body:
        out["Content-Encoding"] = "gzip"
    return out


def iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def batch(collector: str, servers: list[dict[str, Any]], batch_id: str | None = None) -> dict[str, Any]:
    return {
        "schema": 1,
        "batch_id": batch_id or str(uuid.uuid4()),
        "collector": collector,
        "sent_at": iso(datetime.now(UTC)),
        "servers": servers,
    }


def reading(
    t: datetime, metric: str, value: float | None, component: str = "", status: str | None = None
) -> dict[str, Any]:
    return {"time": iso(t), "metric": metric, "component": component, "value": value, "status": status}


def gz(doc: dict[str, Any]) -> bytes:
    return gzip.compress(json.dumps(doc).encode())


async def post_batch(
    client: httpx.AsyncClient, doc: dict[str, Any], collector: str | None = None, compress: bool = True
) -> httpx.Response:
    body = gz(doc) if compress else json.dumps(doc).encode()
    return await client.post(
        "/ingest/v1/batches", content=body, headers=headers(collector or doc["collector"], gzip_body=compress)
    )


async def add_readings(
    session: AsyncSession,
    server_id: int,
    metric: str,
    points: list[tuple[float, float | None]],
    now: datetime,
    component: str = "",
    status: str | None = None,
) -> None:
    """Insert readings at `now - seconds_ago` (owner session; tests set up data, the engine reads it)."""
    for seconds_ago, value in points:
        await session.execute(
            text(
                "INSERT INTO readings (time, server_id, metric_code, component, value, status) "
                "SELECT :t, :sid, id, :comp, :v, :st FROM metric_definitions WHERE code = :code"
            ),
            {
                "t": now - timedelta(seconds=seconds_ago),
                "sid": server_id,
                "comp": component,
                "v": value,
                "st": status,
                "code": metric,
            },
        )
    await session.commit()


async def metric_id(session: AsyncSession, code: str) -> int:
    return int(
        (
            await session.execute(text("SELECT id FROM metric_definitions WHERE code = :c"), {"c": code})
        ).scalar_one()
    )


__all__ = [
    "CONTRACT_EXAMPLE",
    "TOKEN",
    "Ref",
    "TaskRecorder",
    "World",
    "add_readings",
    "app_engine",
    "batch",
    "build_world",
    "fake_redis",
    "gz",
    "headers",
    "ingest_client",
    "ingest_engine",
    "iso",
    "metric_id",
    "post_batch",
    "reading",
    "role_engine",
    "tasks",
    "use_app_engine",
    "world",
]
