"""Poll scheduling: sensors every 60 s, health every 5 min, inventory/firmware/limits daily.

Each server has its own timeline with a random start offset inside the first sensor interval, so 500 BMCs
do not all fire in the same second. Every sensor tick starts one poll for the server that also covers
health and/or inventory when those are due. If the server's previous poll is still running, the tick is
skipped (never queued) and counted; health and inventory then stay due for the next tick.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from gcc_collector.adapters import PollKind
from gcc_collector.metrics import SERVERS_ASSIGNED, RollingStats
from gcc_collector.poller import ServerPoller
from gcc_collector.schema import CollectorSettings, ServerConfig, ServerPayload

log = logging.getLogger("gcc.collector.scheduler")

PollerFactory = Callable[[ServerConfig], ServerPoller]
Sink = Callable[[ServerPayload], None]


@dataclass
class _Entry:
    poller: ServerPoller
    next_sensor: float
    next_health: float
    next_inventory: float
    task: asyncio.Task[None] | None = None

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()


def _connection_key(server: ServerConfig) -> tuple[str, str]:
    return server.bmc_host, server.credential_ref


class Scheduler:
    def __init__(
        self,
        settings: CollectorSettings,
        make_poller: PollerFactory,
        sink: Sink,
        stats: RollingStats,
        *,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
        tick_s: float = 1.0,
    ) -> None:
        self.settings = settings
        self.make_poller = make_poller
        self.sink = sink
        self.stats = stats
        self.clock = clock
        self.rng = rng or random.Random()
        self.tick_s = tick_s
        self.entries: dict[int, _Entry] = {}
        self._closing: set[asyncio.Task[None]] = set()

    # ---------------------------------------------------------------------------- server list
    def update(self, servers: list[ServerConfig], settings: CollectorSettings | None = None) -> None:
        """Apply a new config: start polling new servers, stop removed ones, reconnect changed ones."""
        if settings is not None:
            self.settings = settings
        wanted = {s.id: s for s in servers}
        for server_id in list(self.entries):
            entry = self.entries[server_id]
            new = wanted.get(server_id)
            if new is None or _connection_key(new) != _connection_key(entry.poller.server):
                self._drop(server_id)
        now = self.clock()
        for server_id, server in wanted.items():
            existing = self.entries.get(server_id)
            if existing is not None:
                existing.poller.server = server  # status / takeover / vendor hint changes need no reconnect
                continue
            first = now + self.rng.uniform(0, self.settings.sensor_interval_s)
            self.entries[server_id] = _Entry(
                poller=self.make_poller(server),
                next_sensor=first,
                next_health=first + self.settings.health_interval_s,
                next_inventory=first + self.settings.inventory_interval_s,
            )
        self.stats.forget(set(self.stats.server_ok) - set(wanted))
        SERVERS_ASSIGNED.set(len(self.entries))

    def _drop(self, server_id: int) -> None:
        entry = self.entries.pop(server_id)
        if entry.task is not None and not entry.task.done():
            entry.task.cancel()
        closing = asyncio.get_running_loop().create_task(entry.poller.close())
        self._closing.add(closing)
        closing.add_done_callback(self._closing.discard)

    # ------------------------------------------------------------------------------------ ticks
    def tick(self) -> int:
        """Start every poll that is due. Returns how many polls were started."""
        now = self.clock()
        started = 0
        sensor_s = self.settings.sensor_interval_s
        for entry in self.entries.values():
            if now < entry.next_sensor:
                continue
            # Next slot on the server's own grid (several slots may have passed if the loop stalled).
            missed = int((now - entry.next_sensor) // sensor_s)
            entry.next_sensor += (missed + 1) * sensor_s
            if entry.busy:
                self.stats.skipped()
                log.info(
                    "server %s: previous poll still running; skipping this cycle", entry.poller.server.id
                )
                continue
            kinds: set[PollKind] = {"sensors"}
            if now >= entry.next_health:
                kinds.add("health")
                entry.next_health = now + self.settings.health_interval_s
            if now >= entry.next_inventory:
                kinds.add("inventory")
                entry.next_inventory = now + self.settings.inventory_interval_s
            entry.task = asyncio.get_running_loop().create_task(self._run_poll(entry, frozenset(kinds)))
            started += 1
        return started

    async def _run_poll(self, entry: _Entry, kinds: frozenset[PollKind]) -> None:
        poller = entry.poller
        started = time.monotonic()
        try:
            result = await poller.poll(kinds)
        except asyncio.CancelledError:
            raise
        except Exception:  # an adapter bug must not kill the scheduler; report the BMC as unreachable
            log.exception("server %s: poll crashed", poller.server.id)
            self.stats.poll(poller.server.id, poller.vendor, False)
            self.sink(poller.unreachable())
            return
        self.stats.poll(poller.server.id, result.vendor, result.ok, time.monotonic() - started)
        self.sink(result.payload)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            self.tick()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.tick_s)

    async def wait_idle(self) -> None:
        tasks = [e.task for e in self.entries.values() if e.task is not None and not e.task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self, grace_s: float = 5.0) -> None:
        """Give running polls a moment to finish, cancel the rest, delete the BMC sessions."""
        tasks = [e.task for e in self.entries.values() if e.task is not None and not e.task.done()]
        if tasks:
            _, still = await asyncio.wait(tasks, timeout=grace_s)
            for task in still:
                task.cancel()
            await asyncio.gather(*still, return_exceptions=True)
        await asyncio.gather(*(e.poller.close() for e in self.entries.values()), return_exceptions=True)
        await asyncio.gather(*self._closing, return_exceptions=True)
        self.entries.clear()
