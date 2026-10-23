"""Fan-out of live updates from Redis to browser WebSockets.

One Redis subscription to LIVE_CHANNEL per app-API process. Each message carries `server_id` and
`site_id`; a socket receives it when the user may see that site and has subscribed to the server or the
site. Every socket has its own bounded queue drained by a single writer task, so a slow browser never
holds up the others (when its queue is full, the oldest updates for it are dropped).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.live import LIVE_CHANNEL, LiveMessage
from app.core.redis import get_redis
from app.core.security import Principal

log = logging.getLogger("gcc.live")

QUEUE_SIZE = 500
_adapter: TypeAdapter[Any] = TypeAdapter(LiveMessage)


@dataclass(eq=False)
class LiveConnection:
    principal: Principal
    servers: set[int] = field(default_factory=set)
    sites: set[int] = field(default_factory=set)
    queue: asyncio.Queue[str] = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))
    dropped: int = 0

    def wants(self, server_id: int | None, site_id: int | None) -> bool:
        if not self.principal.can_see_site(site_id):
            return False
        if server_id is not None and server_id in self.servers:
            return True
        return site_id is not None and site_id in self.sites

    def offer(self, payload: str) -> None:
        if self.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait(payload)


class LiveHub:
    def __init__(self) -> None:
        self._connections: set[LiveConnection] = set()
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    @property
    def connections(self) -> int:
        return len(self._connections)

    def register(self, conn: LiveConnection) -> None:
        self._connections.add(conn)

    def unregister(self, conn: LiveConnection) -> None:
        self._connections.discard(conn)

    async def start(self, redis: Redis | None = None) -> None:
        if self._task is None:
            self._ready = asyncio.Event()
            self._task = asyncio.create_task(self._run(redis), name="live-hub")

    async def wait_ready(self) -> None:
        await self._ready.wait()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._connections.clear()

    def dispatch(self, raw: str) -> int:
        """Deliver one channel message to every interested socket. Returns how many got it."""
        try:
            message = _adapter.validate_json(raw)
        except ValidationError:
            log.warning("ignoring malformed live message: %.200s", raw)
            return 0
        server_id = getattr(message, "server_id", None)
        site_id = getattr(message, "site_id", None)
        payload = message.model_dump_json()
        delivered = 0
        for conn in list(self._connections):
            if conn.wants(server_id, site_id):
                conn.offer(payload)
                delivered += 1
        return delivered

    async def _run(self, redis: Redis | None) -> None:
        backoff = 1.0
        while True:
            client = redis or get_redis()
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            try:
                await pubsub.subscribe(LIVE_CHANNEL)
                self._ready.set()
                backoff = 1.0
                while True:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if msg is None:
                        continue
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode()
                    if isinstance(data, str):
                        self.dispatch(data)
            except asyncio.CancelledError:
                raise
            except (RedisError, OSError) as exc:
                log.warning("live hub lost Redis (%s); retrying in %.0f s", exc, backoff)
                self._ready.clear()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()  # type: ignore[no-untyped-call]


hub = LiveHub()


def user_payload(principal: Principal) -> dict[str, Any]:
    return {
        "sub": principal.sub,
        "name": principal.display_name,
        "roles": sorted(r.value for r in principal.roles),
        "sites": sorted(principal.site_ids) if principal.site_ids is not None else None,
        "expires_at": principal.expires_at.isoformat(),
    }


def dumps(obj: dict[str, Any]) -> str:
    return json.dumps(obj, separators=(",", ":"))
