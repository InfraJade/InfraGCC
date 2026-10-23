"""WebSocket `/api/v1/live`: live readings, health changes and alerts for the servers a page shows.

Protocol (DECISIONS D23):
  client → `{"type":"auth","token":"<access token>"}` within 5 s (anything else, or a bad token → close 1008)
  server → `{"type":"ready","user":{...}}`
  client → `{"type":"subscribe","servers":[ids],"sites":[ids]}` / `{"type":"unsubscribe",...}`
  server → `{"type":"subscribed","servers":[...],"sites":[...]}` (what is now subscribed, out-of-scope ids
           dropped), then `readings` / `health` / `alert` messages (shapes in app.core.live)
  server → `{"type":"ping"}` every 25 s; the client may answer `{"type":"pong"}`
  client → `{"type":"auth","token":...}` again at any time with a refreshed token (same user), answered by
           another `ready`. A socket whose token has expired without a refresh is closed with 1008.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.core.problems import Problem
from app.core.security import AuthError, Principal, principal_from_token
from app.models import Server
from app.services.live_hub import LiveConnection, dumps, hub, user_payload

log = logging.getLogger("gcc.live")

router = APIRouter()

AUTH_TIMEOUT_S = 5.0
PING_INTERVAL_S = 25.0
EXPIRY_GRACE = timedelta(seconds=30)
MAX_SERVERS = 2000
MAX_SITES = 200
POLICY_VIOLATION = 1008
INTERNAL_ERROR = 1011


class _Reject(Exception):
    def __init__(self, reason: str, code: int = POLICY_VIOLATION) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


class _Auth(BaseModel):
    type: Literal["auth"]
    token: str = Field(min_length=1, max_length=16384)


class _Subscription(BaseModel):
    type: Literal["subscribe", "unsubscribe"]
    servers: list[int] = Field(default_factory=list, max_length=MAX_SERVERS)
    sites: list[int] = Field(default_factory=list, max_length=MAX_SITES)


async def _authenticate(token: str) -> Principal:
    try:
        principal = await principal_from_token(token)
    except AuthError as exc:
        raise _Reject(f"invalid token: {exc}") from exc
    except Problem as exc:
        raise _Reject("identity provider unavailable", INTERNAL_ERROR) from exc
    if not principal.roles:
        raise _Reject("no Jade GCC role")
    return principal


async def _first_auth(ws: WebSocket) -> Principal:
    try:
        raw = await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_S)
    except TimeoutError as exc:
        raise _Reject("authentication timeout") from exc
    try:
        msg = _Auth.model_validate_json(raw)
    except ValidationError as exc:
        raise _Reject("first message must be {type: auth, token}") from exc
    return await _authenticate(msg.token)


async def _visible_servers(principal: Principal, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    async with get_sessionmaker()() as session:
        rows = await session.execute(select(Server.id, Server.site_id).where(Server.id.in_(ids)))
        return {sid for sid, site_id in rows.all() if principal.can_see_site(site_id)}


def _subscribed(conn: LiveConnection) -> str:
    return dumps({"type": "subscribed", "servers": sorted(conn.servers), "sites": sorted(conn.sites)})


async def _handle(raw: str, conn: LiveConnection) -> None:
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        conn.offer(dumps({"type": "error", "detail": "messages must be JSON"}))
        return
    kind = data.get("type") if isinstance(data, dict) else None
    if kind == "pong":
        return
    if kind == "auth":
        try:
            msg = _Auth.model_validate(data)
        except ValidationError as exc:
            raise _Reject("malformed auth message") from exc
        principal = await _authenticate(msg.token)
        if principal.sub != conn.principal.sub:
            raise _Reject("token belongs to a different user")
        conn.principal = principal
        conn.sites = {s for s in conn.sites if principal.can_see_site(s)}
        conn.servers = await _visible_servers(principal, sorted(conn.servers))
        conn.offer(dumps({"type": "ready", "user": user_payload(principal)}))
        return
    if kind in ("subscribe", "unsubscribe"):
        try:
            sub = _Subscription.model_validate(data)
        except ValidationError as exc:
            conn.offer(dumps({"type": "error", "detail": f"invalid {kind}: {exc.errors()[0]['msg']}"}))
            return
        if sub.type == "subscribe":
            conn.sites |= {s for s in sub.sites if conn.principal.can_see_site(s)}
            conn.servers |= await _visible_servers(conn.principal, sub.servers)
            if len(conn.servers) > MAX_SERVERS or len(conn.sites) > MAX_SITES:
                conn.offer(dumps({"type": "error", "detail": "too many subscriptions"}))
        else:
            conn.sites -= set(sub.sites)
            conn.servers -= set(sub.servers)
        conn.offer(_subscribed(conn))
        return
    conn.offer(dumps({"type": "error", "detail": f"unknown message type {kind!r}"}))


async def _writer(ws: WebSocket, conn: LiveConnection) -> None:
    """The only task that sends on the socket: queued messages, pings, and the expiry close."""
    loop = asyncio.get_running_loop()
    next_ping = loop.time() + PING_INTERVAL_S
    while True:
        if datetime.now(UTC) > conn.principal.expires_at + EXPIRY_GRACE:
            await ws.close(code=POLICY_VIOLATION, reason="token expired")
            return
        try:
            payload = await asyncio.wait_for(conn.queue.get(), max(0.0, next_ping - loop.time()))
        except TimeoutError:
            payload = dumps({"type": "ping"})
            next_ping = loop.time() + PING_INTERVAL_S
        await ws.send_text(payload)


@router.websocket("/live")
async def live(ws: WebSocket) -> None:
    await ws.accept()
    try:
        principal = await _first_auth(ws)
    except WebSocketDisconnect:
        return
    except _Reject as exc:
        await ws.close(code=exc.code, reason=exc.reason)
        return
    conn = LiveConnection(principal=principal)
    conn.offer(dumps({"type": "ready", "user": user_payload(principal)}))
    hub.register(conn)
    writer = asyncio.create_task(_writer(ws, conn), name="live-writer")
    close: _Reject | None = None
    try:
        while True:
            try:
                raw = await ws.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                break
            try:
                await _handle(raw, conn)
            except _Reject as exc:
                close = exc
                break
    finally:
        hub.unregister(conn)
        writer.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await writer
        if close is not None:
            with contextlib.suppress(Exception):
                await ws.close(code=close.code, reason=close.reason)
