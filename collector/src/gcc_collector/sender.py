"""Batches server payloads and ships them to the ingest API; falls back to the disk buffer.

Every ``batch_interval_s`` the sender first replays the disk buffer oldest-first. Only when the buffer is
empty are new batches POSTed; otherwise they are appended to the buffer, so the cloud always receives
batches in the order they were made. Each batch carries a UUID ``batch_id``, so a replay of a batch the
cloud already stored (e.g. the response was lost) is acknowledged as a duplicate and ignored.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from gcc_collector import metrics
from gcc_collector.buffer import DiskBuffer
from gcc_collector.cloud import CloudClient, IngestRejected, IngestUnavailable, gzip_json
from gcc_collector.schema import Batch, ServerPayload

log = logging.getLogger("gcc.collector.sender")

MAX_SERVERS_PER_BATCH = 200


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class Sender:
    def __init__(
        self,
        cloud: CloudClient,
        buffer: DiskBuffer,
        collector_name: str,
        *,
        max_servers_per_batch: int = MAX_SERVERS_PER_BATCH,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.cloud = cloud
        self.buffer = buffer
        self.collector_name = collector_name
        self.max_servers = max_servers_per_batch
        self.clock = clock
        self._pending: list[ServerPayload] = []
        self._lock = asyncio.Lock()
        self.last_batch_at: datetime | None = None

    def add(self, payload: ServerPayload) -> None:
        self._pending.append(payload)

    @property
    def pending_payloads(self) -> int:
        return len(self._pending)

    def _take_batches(self) -> list[tuple[str, bytes]]:
        payloads, self._pending = self._pending, []
        out = []
        for start in range(0, len(payloads), self.max_servers):
            batch = Batch(
                batch_id=str(uuid.uuid4()),
                collector=self.collector_name,
                sent_at=self.clock(),
                servers=payloads[start : start + self.max_servers],
            )
            body = json.dumps(batch.to_json_dict(), separators=(",", ":")).encode()
            out.append((batch.batch_id, gzip_json(body)))
        return out

    async def _post(self, batch_id: str, body: bytes) -> bool:
        """True when the cloud took the batch (or rejected it for good); False to keep it for later."""
        started = time.monotonic()
        try:
            resp = await self.cloud.post_batch(body)
        except IngestRejected as exc:
            log.error("ingest rejected batch %s; dropping it: %s", batch_id, exc)
            metrics.BATCHES.labels(result="rejected").inc()
            return True
        except IngestUnavailable as exc:
            log.warning("ingest unavailable for batch %s: %s", batch_id, exc)
            metrics.BATCHES.labels(result="failed").inc()
            return False
        metrics.BATCH_SECONDS.observe(time.monotonic() - started)
        metrics.BATCHES.labels(result="duplicate" if resp.duplicate else "ok").inc()
        self.last_batch_at = self.clock()
        return True

    async def replay(self) -> bool:
        """Send buffered batches oldest-first. True when the buffer is empty afterwards."""
        for item in await asyncio.to_thread(self.buffer.pending):
            body = await asyncio.to_thread(self.buffer.read, item)
            if body is None:
                continue
            if not await self._post(item.batch_id, body):
                return False
            await asyncio.to_thread(self.buffer.remove, item)
            log.info("replayed buffered batch %s", item.batch_id)
        return True

    async def flush(self) -> None:
        """One send cycle: replay the buffer, then send (or buffer) what was polled since the last cycle."""
        async with self._lock:
            drained = await self.replay()
            for batch_id, body in self._take_batches():
                if drained and await self._post(batch_id, body):
                    continue
                drained = False  # keep order: everything after a failure goes to the buffer too
                await asyncio.to_thread(self.buffer.put, batch_id, body)

    async def flush_to_disk(self) -> None:
        """Shutdown: write everything still in memory to the buffer without touching the network."""
        async with self._lock:
            for batch_id, body in self._take_batches():
                await asyncio.to_thread(self.buffer.put, batch_id, body)

    async def run(self, interval: Callable[[], float], stop: asyncio.Event) -> None:
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval())
            if stop.is_set():
                break
            try:
                await self.flush()
            except Exception:  # never let one bad cycle stop the sender
                log.exception("send cycle failed")
