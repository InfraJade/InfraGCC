"""Prometheus metrics (``/metrics`` on ``GCC_METRICS_PORT``) and the rolling stats sent in heartbeats."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from prometheus_client import Counter, Gauge, Histogram, start_http_server

POLLS = Counter("gcc_collector_polls_total", "BMC polls by vendor and result", ["vendor", "result"])
POLL_ERRORS = Counter("gcc_collector_poll_errors_total", "Failed BMC polls by vendor", ["vendor"])
POLL_SECONDS = Histogram(
    "gcc_collector_poll_seconds",
    "Duration of one BMC poll",
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)
CYCLES_SKIPPED = Counter(
    "gcc_collector_cycles_skipped_total", "Poll cycles skipped because the previous poll was still running"
)
SERVERS_ASSIGNED = Gauge("gcc_collector_servers_assigned", "Servers this collector polls")
BUFFER_BATCHES = Gauge("gcc_collector_buffer_batches", "Batches waiting in the disk buffer")
BUFFER_BYTES = Gauge("gcc_collector_buffer_bytes", "Bytes waiting in the disk buffer")
BUFFER_DROPPED = Counter("gcc_collector_buffer_dropped_total", "Buffered batches dropped", ["reason"])
BATCHES = Counter("gcc_collector_batches_total", "Batches sent to the ingest API", ["result"])
BATCH_SECONDS = Histogram(
    "gcc_collector_batch_seconds",
    "Latency of POST /ingest/v1/batches",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
HEARTBEATS = Counter("gcc_collector_heartbeats_total", "Heartbeats sent", ["result"])


def start_metrics_server(port: int) -> None:
    if port > 0:
        start_http_server(port)


class RollingStats:
    """Counts over the last minute for the heartbeat (`polls_ok_1m`, `polls_failed_1m`, ...)."""

    def __init__(self, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.window_s = window_s
        self.clock = clock
        self._polls: deque[tuple[float, str, bool]] = deque()
        self._skips: deque[float] = deque()
        self.server_ok: dict[int, bool] = {}

    def _trim(self) -> None:
        cutoff = self.clock() - self.window_s
        while self._polls and self._polls[0][0] < cutoff:
            self._polls.popleft()
        while self._skips and self._skips[0] < cutoff:
            self._skips.popleft()

    def poll(self, server_id: int, vendor: str, ok: bool, seconds: float | None = None) -> None:
        self._polls.append((self.clock(), vendor, ok))
        self.server_ok[server_id] = ok
        POLLS.labels(vendor=vendor, result="ok" if ok else "failed").inc()
        if not ok:
            POLL_ERRORS.labels(vendor=vendor).inc()
        if seconds is not None:
            POLL_SECONDS.observe(seconds)

    def skipped(self) -> None:
        self._skips.append(self.clock())
        CYCLES_SKIPPED.inc()

    def forget(self, server_ids: set[int]) -> None:
        for server_id in server_ids:
            self.server_ok.pop(server_id, None)

    def snapshot(self) -> dict[str, object]:
        self._trim()
        errors: dict[str, int] = {}
        for _, vendor, ok in self._polls:
            errors.setdefault(vendor, 0)
            if not ok:
                errors[vendor] += 1
        return {
            "servers_ok": sum(1 for ok in self.server_ok.values() if ok),
            "polls_ok_1m": sum(1 for _, _, ok in self._polls if ok),
            "polls_failed_1m": sum(1 for _, _, ok in self._polls if not ok),
            "cycles_skipped_1m": len(self._skips),
            "errors_by_vendor": errors,
        }
