"""Disk buffer (ordering, TTL, atomic writes) and the sender's replay-before-new ordering."""

from __future__ import annotations

import gzip
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import FIXED_NOW

from gcc_collector.buffer import DiskBuffer
from gcc_collector.cloud import CloudClient
from gcc_collector.config import load_env
from gcc_collector.schema import Batch, Reading, ServerPayload
from gcc_collector.sender import Sender


class Clock:
    def __init__(self, ns: int = 1_800_000_000 * 10**9) -> None:
        self.ns = ns

    def __call__(self) -> int:
        return self.ns


def test_buffer_is_fifo_even_with_identical_timestamps(tmp_path: Path) -> None:
    clock = Clock()
    buf = DiskBuffer(tmp_path, clock=clock)
    ids = [str(uuid.uuid4()) for _ in range(5)]
    for i, batch_id in enumerate(ids):
        buf.put(batch_id, f"body-{i}".encode())
    assert [b.batch_id for b in buf.pending()] == ids
    assert [buf.read(b) for b in buf.pending()] == [f"body-{i}".encode() for i in range(5)]
    assert buf.stats() == (5, sum(len(f"body-{i}") for i in range(5)))


def test_buffer_order_survives_restart_and_clock_going_back(tmp_path: Path) -> None:
    clock = Clock()
    first = DiskBuffer(tmp_path, clock=clock)
    a = str(uuid.uuid4())
    first.put(a, b"a")
    clock.ns -= 10**9  # NTP stepped the clock back
    second = DiskBuffer(tmp_path, clock=clock)
    b = str(uuid.uuid4())
    second.put(b, b"b")
    assert [x.batch_id for x in second.pending()] == [a, b]


def test_buffer_ttl_drops_old_batches(tmp_path: Path) -> None:
    clock = Clock()
    buf = DiskBuffer(tmp_path, ttl_s=3600, clock=clock)
    old, new = str(uuid.uuid4()), str(uuid.uuid4())
    buf.put(old, b"old")
    clock.ns += 3000 * 10**9
    buf.put(new, b"new")
    clock.ns += 1000 * 10**9  # old is now 4000 s old, new 1000 s
    assert [b.batch_id for b in buf.pending()] == [new]
    assert len(list(tmp_path.glob("*.json.gz"))) == 1


def test_buffer_writes_atomically_and_cleans_temp_files(tmp_path: Path) -> None:
    (tmp_path / ".tmp-deadbeef").write_bytes(b"partial")  # left by a crash mid-write
    (tmp_path / "config-cache.json").write_text("{}")  # other files are ignored
    buf = DiskBuffer(tmp_path)
    assert not (tmp_path / ".tmp-deadbeef").exists()
    item = buf.put(str(uuid.uuid4()), b"x")
    assert item.path.exists()
    assert list(tmp_path.glob(".tmp-*")) == []
    assert len(buf.pending()) == 1
    with pytest.raises(ValueError):
        buf.put("../../etc/passwd", b"x")


# -------------------------------------------------------------------------------------------- sender


class FakeIngest:
    def __init__(self) -> None:
        self.up = True
        self.status = 200
        self.received: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.up:
            raise httpx.ConnectError("cloud down", request=request)
        if self.status != 200:
            return httpx.Response(self.status, json={"title": "nope"})
        body = json.loads(gzip.decompress(request.content))
        duplicate = any(b["batch_id"] == body["batch_id"] for b in self.received)
        self.received.append(body)
        return httpx.Response(
            200, json={"batch_id": body["batch_id"], "duplicate": duplicate, "servers": len(body["servers"])}
        )


def make_sender(tmp_path: Path, ingest: FakeIngest) -> Sender:
    env = load_env(
        {
            "GCC_COLLECTOR_NAME": "pnq1-col-a",
            "GCC_INGEST_URL": "http://ingest.test",
            "GCC_INGEST_TOKEN": "dev-ingest-token",
            "GCC_BUFFER_DIR": str(tmp_path),
        }
    )
    cloud = CloudClient(env, transport=httpx.MockTransport(ingest.handler))
    return Sender(cloud, DiskBuffer(tmp_path), env.collector_name, clock=lambda: FIXED_NOW)


def payload(server_id: int) -> ServerPayload:
    reading = Reading(time=FIXED_NOW, metric="power_w", component="", value=300.0 + server_id, status=None)
    return ServerPayload(server_id=server_id, polled_at=FIXED_NOW, readings=[reading])


async def test_sender_posts_gzip_with_auth(tmp_path: Path) -> None:
    ingest = FakeIngest()
    sender = make_sender(tmp_path, ingest)
    sender.add(payload(1))
    await sender.flush()
    (req,) = ingest.requests
    assert req.url.path == "/ingest/v1/batches"
    assert req.headers["Content-Encoding"] == "gzip"
    assert req.headers["Authorization"] == "Bearer dev-ingest-token"
    assert req.headers["X-Collector-Name"] == "pnq1-col-a"
    body = ingest.received[0]
    Batch.model_validate(body)  # the wire form is valid against the contract models
    assert body["schema"] == 1 and body["collector"] == "pnq1-col-a"
    assert "events" not in body["servers"][0]  # lists the poll did not produce are omitted
    assert sender.last_batch_at == FIXED_NOW
    await sender.cloud.aclose()


async def test_failed_batches_are_buffered_and_replayed_in_order(tmp_path: Path) -> None:
    ingest = FakeIngest()
    sender = make_sender(tmp_path, ingest)
    ingest.up = False
    for server_id in (1, 2, 3):
        sender.add(payload(server_id))
        await sender.flush()
    assert len(sender.buffer.pending()) == 3
    assert ingest.received == []

    ingest.up = True
    sender.add(payload(4))
    await sender.flush()
    order = [b["servers"][0]["server_id"] for b in ingest.received]
    assert order == [1, 2, 3, 4]  # buffered batches first, oldest first, then the new one
    assert sender.buffer.pending() == []
    await sender.cloud.aclose()


async def test_new_batches_queue_behind_a_partial_replay(tmp_path: Path) -> None:
    ingest = FakeIngest()
    sender = make_sender(tmp_path, ingest)
    ingest.up = False
    sender.add(payload(1))
    await sender.flush()
    ingest.up = True
    ingest.status = 503  # the cloud answers but is not ready
    sender.add(payload(2))
    await sender.flush()
    pending = sender.buffer.pending()
    assert len(pending) == 2
    ingest.status = 200
    await sender.flush()
    assert [b["servers"][0]["server_id"] for b in ingest.received] == [1, 2]
    await sender.cloud.aclose()


async def test_replay_keeps_batch_id_so_it_is_idempotent(tmp_path: Path) -> None:
    ingest = FakeIngest()
    sender = make_sender(tmp_path, ingest)
    ingest.up = False
    sender.add(payload(1))
    await sender.flush()
    (item,) = sender.buffer.pending()
    ingest.up = True
    await sender.flush()
    assert ingest.received[0]["batch_id"] == item.batch_id
    # Replaying the same bytes again (response lost) is acknowledged as a duplicate.
    body = sender.buffer.read(
        sender.buffer.put(item.batch_id, gzip.compress(json.dumps(ingest.received[0]).encode()))
    )
    assert body is not None
    await sender.flush()
    assert [b["batch_id"] for b in ingest.received] == [item.batch_id, item.batch_id]
    assert sender.buffer.pending() == []
    await sender.cloud.aclose()


async def test_rejected_batch_is_dropped_not_retried_forever(tmp_path: Path) -> None:
    ingest = FakeIngest()
    sender = make_sender(tmp_path, ingest)
    ingest.status = 422
    sender.add(payload(1))
    await sender.flush()
    assert sender.buffer.pending() == []
    assert len(ingest.requests) == 1
    await sender.cloud.aclose()


async def test_flush_to_disk_on_shutdown(tmp_path: Path) -> None:
    ingest = FakeIngest()
    sender = make_sender(tmp_path, ingest)
    for server_id in range(450):
        sender.add(payload(server_id))
    await sender.flush_to_disk()
    assert ingest.requests == []
    pending = sender.buffer.pending()
    assert len(pending) == 3  # 200 servers per batch
    first = sender.buffer.read(pending[0])
    assert first is not None
    assert len(json.loads(gzip.decompress(first))["servers"]) == 200
    await sender.cloud.aclose()
