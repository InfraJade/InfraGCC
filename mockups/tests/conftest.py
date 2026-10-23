"""Shared fixtures: virtual BMCs, a small fleet, and aiohttp test clients for the BMC and control apps."""

from __future__ import annotations

import base64
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gcc_redfish_sim.catalog import FLEET
from gcc_redfish_sim.simulator.bmc import VirtualBmc
from gcc_redfish_sim.simulator.config import SimConfig
from gcc_redfish_sim.simulator.control import create_control_app
from gcc_redfish_sim.simulator.fleet import Fleet
from gcc_redfish_sim.simulator.redfish import create_bmc_app

USER = "gcc-monitor"
PASSWORD = "test-pw"
T0 = datetime(2026, 10, 22, 4, 0, tzinfo=UTC)  # 09:30 IST
SESSIONS = "/redfish/v1/SessionService/Sessions"

# One BMC index per model (BMC i runs FLEET[(i - 1) % 6]).
MODEL_INDEXES = {key: i + 1 for i, key in enumerate(FLEET)}
PROFILE_INDEXES = {"dell": 1, "hpe": 2, "lenovo": 3}

Client = TestClient[web.Request, web.Application]
ClientFactory = Callable[[VirtualBmc], Awaitable[Client]]


def make_bmc(index: int, seed: str = "test") -> VirtualBmc:
    return VirtualBmc(index, 20000 + index, random.Random(f"{seed}-{index}"), T0)


def basic(user: str = USER, password: str = PASSWORD) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def make_config(**overrides: Any) -> SimConfig:
    values: dict[str, Any] = {
        "count": 6,
        "base_port": 30000,
        "control_port": 9100,
        "username": USER,
        "password": PASSWORD,
        "fault_rate_per_hour": 0.0,
        "seed": "test",
    }
    values.update(overrides)
    return SimConfig(**values)


@pytest.fixture
def fleet() -> Fleet:
    return Fleet(make_config(), now=T0)


@pytest.fixture
async def bmc_client() -> AsyncIterator[ClientFactory]:
    started: list[tuple[Client, VirtualBmc]] = []

    async def factory(bmc: VirtualBmc) -> Client:
        client: Client = TestClient(TestServer(create_bmc_app(bmc, USER, PASSWORD)))
        await client.start_server()
        started.append((client, bmc))
        return client

    yield factory
    for client, bmc in started:
        bmc.release_waiters()
        await client.close()


@pytest.fixture
async def control_client(fleet: Fleet) -> AsyncIterator[Client]:
    client: Client = TestClient(TestServer(create_control_app(fleet)))
    await client.start_server()
    yield client
    await client.close()


async def session_token(client: Client) -> str:
    resp = await client.post(SESSIONS, json={"UserName": USER, "Password": PASSWORD})
    assert resp.status == 201
    return resp.headers["X-Auth-Token"]
