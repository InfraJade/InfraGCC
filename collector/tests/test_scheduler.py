"""Scheduler: jittered start, health/inventory cadence, skip-a-cycle (never queue) when a poll is slow."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime

from conftest import FIXED_NOW, creds

from gcc_collector.adapters import PollKind
from gcc_collector.metrics import RollingStats
from gcc_collector.poller import PollResult, ServerPoller
from gcc_collector.redfish.client import RedfishClient
from gcc_collector.scheduler import Scheduler
from gcc_collector.schema import CollectorSettings, ServerConfig, ServerPayload


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakePoller(ServerPoller):
    """Records the kinds of each poll; blocks while ``gate`` is cleared."""

    def __init__(self, server: ServerConfig) -> None:
        super().__init__(server, RedfishClient(server.bmc_host, creds()), clock=lambda: FIXED_NOW)
        self.calls: list[frozenset[PollKind]] = []
        self.gate = asyncio.Event()
        self.gate.set()
        self.closed = False

    async def poll(self, kinds: frozenset[PollKind]) -> PollResult:
        self.calls.append(kinds)
        await self.gate.wait()
        return PollResult(
            ServerPayload(server_id=self.server.id, polled_at=FIXED_NOW), ok=True, vendor="Dell"
        )

    async def close(self) -> None:
        self.closed = True
        await super().close()


def make(
    settings: CollectorSettings | None = None,
) -> tuple[Scheduler, FakeClock, dict[int, FakePoller], list[ServerPayload]]:
    clock = FakeClock()
    pollers: dict[int, FakePoller] = {}
    sink: list[ServerPayload] = []

    def factory(server: ServerConfig) -> ServerPoller:
        pollers[server.id] = FakePoller(server)
        return pollers[server.id]

    sched = Scheduler(
        settings or CollectorSettings(),
        factory,
        sink.append,
        RollingStats(clock=clock),
        clock=clock,
        rng=random.Random(42),
    )
    return sched, clock, pollers, sink


def servers(n: int) -> list[ServerConfig]:
    return [ServerConfig(id=i, bmc_host=f"http://bmc-simulator:{20000 + i}") for i in range(1, n + 1)]


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_start_times_are_spread_over_the_first_interval() -> None:
    sched, clock, _, _ = make()
    sched.update(servers(500))
    starts = sorted(e.next_sensor - clock.now for e in sched.entries.values())
    assert starts[0] >= 0 and starts[-1] < 60
    # No second has more than a small share of the fleet.
    per_second: dict[int, int] = {}
    for s in starts:
        per_second[int(s)] = per_second.get(int(s), 0) + 1
    assert max(per_second.values()) < 25
    await sched.close()


async def test_cadence_sensors_health_inventory() -> None:
    sched, clock, pollers, sink = make()
    sched.update(servers(1))
    entry = sched.entries[1]
    clock.now = entry.next_sensor
    assert sched.tick() == 1
    await settle()
    poller = pollers[1]
    assert poller.calls == [frozenset({"sensors"})]  # (the poller itself upgrades first contact to all)
    for _ in range(4):
        clock.now += 60
        sched.tick()
        await settle()
    assert [len(c) for c in poller.calls] == [1, 1, 1, 1, 1]
    clock.now += 60  # 300 s after the first poll
    sched.tick()
    await settle()
    assert poller.calls[-1] == frozenset({"sensors", "health"})
    assert len(sink) == 6
    clock.now = entry.next_inventory + 1
    sched.tick()
    await settle()
    assert "inventory" in poller.calls[-1]
    await sched.close()


async def test_slow_poll_skips_the_cycle_instead_of_queueing() -> None:
    sched, clock, pollers, sink = make()
    sched.update(servers(2))
    clock.now += 61
    assert sched.tick() == 2
    await settle()
    slow = pollers[1]
    slow.gate.clear()  # server 1's next poll hangs
    clock.now += 60
    sched.tick()
    await settle()
    calls_before = len(slow.calls)
    for _ in range(3):  # three more cycles while it is stuck
        clock.now += 60
        assert sched.tick() == 1  # only server 2 is polled
        await settle()
    assert len(slow.calls) == calls_before  # nothing queued for server 1
    assert sched.stats.snapshot()["cycles_skipped_1m"] != 0
    slow.gate.set()
    await settle()
    clock.now += 60
    assert sched.tick() == 2
    await settle()
    assert len(slow.calls) == calls_before + 1  # exactly one new poll, not a backlog
    assert len(sink) > 0
    await sched.close()


async def test_health_stays_due_across_a_skipped_cycle() -> None:
    sched, clock, pollers, _ = make(CollectorSettings(sensor_interval_s=60, health_interval_s=120))
    sched.update(servers(1))
    entry = sched.entries[1]
    clock.now = entry.next_sensor
    sched.tick()
    await settle()
    poller = pollers[1]
    poller.gate.clear()
    clock.now += 60
    sched.tick()  # starts a poll that hangs
    await settle()
    clock.now += 60  # health due now, but the BMC is busy: skipped
    sched.tick()
    await settle()
    poller.gate.set()
    await settle()
    clock.now += 60
    sched.tick()
    await settle()
    assert "health" in poller.calls[-1]
    await sched.close()


async def test_update_adds_removes_and_reconnects() -> None:
    sched, _, pollers, _ = make()
    sched.update(servers(3))
    first = pollers[2]
    changed = [
        ServerConfig(id=1, bmc_host="http://bmc-simulator:20001", takeover=True),
        ServerConfig(id=2, bmc_host="http://bmc-simulator:29999"),
        ServerConfig(id=4, bmc_host="http://bmc-simulator:20004"),
    ]
    sched.update(changed)
    await settle()
    assert set(sched.entries) == {1, 2, 4}
    assert pollers[3].closed  # removed
    assert first.closed and pollers[2] is not first  # new address: new client
    assert sched.entries[1].poller.server.takeover is True  # flag change, same client
    await sched.close()
    assert all(p.closed for p in pollers.values())


async def test_poll_crash_reports_unreachable() -> None:
    sched, clock, pollers, sink = make()
    sched.update(servers(1))

    async def boom(kinds: frozenset[PollKind]) -> PollResult:
        raise RuntimeError("adapter bug")

    pollers[1].poll = boom  # type: ignore[method-assign]
    clock.now += 61
    sched.tick()
    await settle()
    assert [(r.metric, r.value) for r in sink[0].readings or []] == [("bmc_reachable", 0)]
    await sched.close()


def test_fixed_now_is_utc() -> None:
    assert isinstance(FIXED_NOW, datetime) and FIXED_NOW.utcoffset() is not None
