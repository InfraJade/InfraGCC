"""Offline disk queue for batches the cloud could not take.

One file per batch (the exact gzip body that would have been POSTed, so a replay is byte-identical and
idempotent by ``batch_id``). Files are written atomically (temp file + ``os.replace``) and named
``<unix ns>-<batch_id>.json.gz`` with strictly increasing timestamps, so sorting by name is FIFO order.
Batches older than the TTL (default 24 h) are dropped.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gcc_collector import metrics

log = logging.getLogger("gcc.collector.buffer")

_NAME = re.compile(r"^(\d{20})-([0-9a-fA-F-]{36})\.json\.gz$")


@dataclass(frozen=True)
class BufferedBatch:
    path: Path
    batch_id: str
    created_ns: int
    size: int


class DiskBuffer:
    def __init__(
        self, directory: Path, ttl_s: float = 86400.0, *, clock: Callable[[], int] = time.time_ns
    ) -> None:
        self.directory = directory
        self.ttl_ns = int(ttl_s * 1e9)
        self.clock = clock
        self.directory.mkdir(parents=True, exist_ok=True)
        self._last_ns = max((b.created_ns for b in self._scan()), default=0)
        for stale in self.directory.glob(".tmp-*"):
            stale.unlink(missing_ok=True)  # a crash mid-write leaves only a temp file, never a partial batch
        self._update_gauges()

    def _scan(self) -> list[BufferedBatch]:
        out = []
        for path in self.directory.iterdir():
            match = _NAME.match(path.name)
            if not match:
                continue
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            out.append(BufferedBatch(path, match.group(2), int(match.group(1)), size))
        out.sort(key=lambda b: b.path.name)
        return out

    def put(self, batch_id: str, body: bytes) -> BufferedBatch:
        """Store one batch body. Atomic: readers never see a partial file."""
        str(uuid.UUID(batch_id))  # reject anything that is not a UUID (it becomes part of a file name)
        created = max(self.clock(), self._last_ns + 1)
        self._last_ns = created
        final = self.directory / f"{created:020d}-{batch_id}.json.gz"
        tmp = self.directory / f".tmp-{uuid.uuid4().hex}"
        with tmp.open("wb") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(final)
        self._update_gauges()
        return BufferedBatch(final, batch_id, created, len(body))

    def pending(self) -> list[BufferedBatch]:
        """Buffered batches oldest first, after dropping the ones past the TTL."""
        cutoff = self.clock() - self.ttl_ns
        keep = []
        for item in self._scan():
            if item.created_ns < cutoff:
                log.warning("dropping buffered batch %s: older than the buffer TTL", item.batch_id)
                item.path.unlink(missing_ok=True)
                metrics.BUFFER_DROPPED.labels(reason="ttl").inc()
            else:
                keep.append(item)
        self._update_gauges(keep)
        return keep

    def read(self, item: BufferedBatch) -> bytes | None:
        try:
            return item.path.read_bytes()
        except FileNotFoundError:
            return None

    def remove(self, item: BufferedBatch, reason: str | None = None) -> None:
        item.path.unlink(missing_ok=True)
        if reason is not None:
            metrics.BUFFER_DROPPED.labels(reason=reason).inc()
        self._update_gauges()

    def stats(self) -> tuple[int, int]:
        items = self._scan()
        return len(items), sum(i.size for i in items)

    def _update_gauges(self, items: list[BufferedBatch] | None = None) -> None:
        items = self._scan() if items is None else items
        metrics.BUFFER_BATCHES.set(len(items))
        metrics.BUFFER_BYTES.set(sum(i.size for i in items))
