"""WebSocket /api/v1/live: auth by first message, subscribe, receive published updates, site filtering.

Driven through a raw ASGI connection on the test's own event loop (the app shares its DB engine and fake
Redis with the test).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any

import fakeredis
import pytest
from fastapi import FastAPI

from app.api import live
from app.core.live import AlertMessage, HealthChange, HealthMessage, LiveReading, ReadingsMessage, publish
from tests.api.conftest import TokenFactory, World

pytestmark = pytest.mark.db


class WsClient:
    def __init__(self, app: FastAPI, path: str = "/api/v1/live") -> None:
        self.to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "scheme": "ws",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "subprotocols": [],
        }
        self.to_app.put_nowait({"type": "websocket.connect"})
        self.task = asyncio.create_task(app(scope, self._receive, self._send))
        self.close_code: int | None = None

    async def _receive(self) -> MutableMapping[str, Any]:
        return await self.to_app.get()

    async def _send(self, message: MutableMapping[str, Any]) -> None:
        await self.from_app.put(dict(message))
        if message["type"] == "websocket.close":
            self.to_app.put_nowait({"type": "websocket.disconnect", "code": message.get("code", 1000)})

    def send(self, obj: Any) -> None:
        self.to_app.put_nowait({"type": "websocket.receive", "text": json.dumps(obj)})

    async def recv(self, wait: float = 3.0) -> dict[str, Any]:
        """Next JSON message (accept frames skipped). Raises if the socket closes."""
        while True:
            msg = await asyncio.wait_for(self.from_app.get(), wait)
            if msg["type"] == "websocket.accept":
                continue
            if msg["type"] == "websocket.close":
                self.close_code = msg.get("code", 1000)
                raise ConnectionError(f"closed {self.close_code}: {msg.get('reason')}")
            data: dict[str, Any] = json.loads(msg["text"])
            return data

    async def recv_close(self, wait: float = 3.0) -> int:
        with pytest.raises(ConnectionError):
            while True:
                await self.recv(wait)
        assert self.close_code is not None
        return self.close_code

    async def recv_type(self, kind: str, wait: float = 3.0) -> dict[str, Any]:
        while True:
            msg = await self.recv(wait)
            if msg["type"] == kind:
                return msg

    async def nothing(self, wait: float = 0.5) -> None:
        with pytest.raises(TimeoutError):
            msg = await self.recv(wait)
            if msg["type"] == "ping":
                await self.recv(wait)

    async def close(self) -> None:
        self.to_app.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(self.task, 3)


def _readings(server_id: int, site_id: int, value: float = 25.0) -> ReadingsMessage:
    return ReadingsMessage(
        server_id=server_id,
        site_id=site_id,
        readings=[
            LiveReading(metric="inlet_temp_c", component="", value=value, status="OK", time=datetime.now(UTC))
        ],
    )


async def test_auth_timeout_closes_1008(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "AUTH_TIMEOUT_S", 0.2)
    ws = WsClient(app)
    assert await ws.recv_close() == 1008
    await asyncio.wait_for(ws.task, 3)


async def test_invalid_token_and_wrong_first_message_close_1008(app: FastAPI, tokens: TokenFactory) -> None:
    ws = WsClient(app)
    ws.send({"type": "auth", "token": tokens("viewer", expires_in=-300)})
    assert await ws.recv_close() == 1008
    ws = WsClient(app)
    ws.send({"type": "subscribe", "sites": [1]})
    assert await ws.recv_close() == 1008
    ws = WsClient(app)
    ws.send({"type": "auth", "token": tokens("norole")})
    assert await ws.recv_close() == 1008


async def test_subscribe_receive_and_site_filtering(
    app: FastAPI, tokens: TokenFactory, world: World, fake_redis: fakeredis.FakeAsyncRedis
) -> None:
    ws = WsClient(app)
    ws.send({"type": "auth", "token": tokens("noc-pune")})
    ready = await ws.recv()
    assert ready["type"] == "ready" and ready["user"]["sites"] == [world.pnq]

    # HYD1 ids are dropped from the subscription.
    ws.send({"type": "subscribe", "servers": [world.s1, world.s3], "sites": [world.hyd]})
    sub = await ws.recv_type("subscribed")
    assert sub == {"type": "subscribed", "servers": [world.s1], "sites": []}

    await publish(fake_redis, _readings(world.s1, world.pnq, 26.5))
    msg = await ws.recv_type("readings")
    assert msg["server_id"] == world.s1 and msg["readings"][0]["value"] == 26.5

    # Another site's server, even if named in the subscription, never arrives.
    await publish(fake_redis, _readings(world.s3, world.hyd))
    # Not subscribed (s2) → not delivered.
    await publish(fake_redis, _readings(world.s2, world.pnq))
    await ws.nothing()

    # Site subscription: every server of the site, including alerts and health.
    ws.send({"type": "subscribe", "sites": [world.pnq]})
    await ws.recv_type("subscribed")
    await publish(
        fake_redis,
        HealthMessage(
            server_id=world.s2,
            site_id=world.pnq,
            server_health="Critical",
            changes=[
                HealthChange(
                    metric="psu_health",
                    component="PSU 1",
                    health="Critical",
                    state="Critical",
                    since=datetime.now(UTC),
                )
            ],
        ),
    )
    assert (await ws.recv_type("health"))["server_id"] == world.s2
    await publish(
        fake_redis,
        AlertMessage(
            alert_id=world.a_pnq,
            server_id=world.s2,
            site_id=world.pnq,
            state="open",
            severity="Critical",
            title="x",
            change="opened",
        ),
    )
    assert (await ws.recv_type("alert"))["alert_id"] == world.a_pnq

    ws.send({"type": "unsubscribe", "servers": [world.s1], "sites": [world.pnq]})
    assert (await ws.recv_type("subscribed")) == {"type": "subscribed", "servers": [], "sites": []}
    await publish(fake_redis, _readings(world.s1, world.pnq))
    await ws.nothing()
    await ws.close()


async def test_unrestricted_user_receives_any_site(
    app: FastAPI, tokens: TokenFactory, world: World, fake_redis: fakeredis.FakeAsyncRedis
) -> None:
    ws = WsClient(app)
    ws.send({"type": "auth", "token": tokens("viewer")})
    assert (await ws.recv())["user"]["sites"] is None
    ws.send({"type": "subscribe", "sites": [world.pnq, world.hyd]})
    await ws.recv_type("subscribed")
    await publish(fake_redis, _readings(world.s3, world.hyd))
    assert (await ws.recv_type("readings"))["site_id"] == world.hyd
    await ws.close()


async def test_ping_and_token_refresh(
    app: FastAPI, tokens: TokenFactory, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "PING_INTERVAL_S", 0.2)
    ws = WsClient(app)
    ws.send({"type": "auth", "token": tokens("noc")})
    await ws.recv_type("ready")
    assert (await ws.recv_type("ping"))["type"] == "ping"
    ws.send({"type": "pong"})
    ws.send({"type": "auth", "token": tokens("noc")})
    assert (await ws.recv_type("ready"))["user"]["sub"] == "sub-noc"
    ws.send({"type": "bogus"})
    assert (await ws.recv_type("error"))["detail"].startswith("unknown message type")
    # A token for someone else ends the session.
    ws.send({"type": "auth", "token": tokens("viewer")})
    assert await ws.recv_close() == 1008
    await asyncio.wait_for(ws.task, 3)


async def test_expired_session_is_closed(
    app: FastAPI, tokens: TokenFactory, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import timedelta

    monkeypatch.setattr(live, "PING_INTERVAL_S", 0.1)
    monkeypatch.setattr(live, "EXPIRY_GRACE", timedelta(seconds=0))
    ws = WsClient(app)
    ws.send({"type": "auth", "token": tokens("noc", expires_in=1)})
    await ws.recv_type("ready")
    assert await ws.recv_close(wait=5) == 1008
    await asyncio.wait_for(ws.task, 3)
