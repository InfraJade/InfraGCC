"""Batch idempotency by `batch_id` in Redis (48 h).

A batch is claimed with `SET NX` as `pending` (5 min) before it is written and marked `done` (48 h) after the
transaction commits; a failed write releases the claim so the collector's retry is processed. A replay of a
`done` batch is acknowledged as a duplicate; a replay that races an in-flight copy gets 409 and retries.
If Redis is unavailable the batch is processed without dedupe (replays are rare and mostly harmless:
latest values, health, events and inventory are idempotent; only raw readings could be doubled).
"""

from __future__ import annotations

import logging
from typing import Literal

from redis.asyncio import Redis

log = logging.getLogger("gcc.ingest.dedupe")

KEY = "gcc:ingest:batch:{}"
DONE_TTL_S = 48 * 3600
PENDING_TTL_S = 300

Claim = Literal["new", "duplicate", "in_progress", "unavailable"]


async def claim_batch(redis: Redis, batch_id: str) -> Claim:
    key = KEY.format(batch_id)
    try:
        if await redis.set(key, "pending", nx=True, ex=PENDING_TTL_S):
            return "new"
        state = await redis.get(key)
    except Exception:
        log.warning("Redis unavailable; batch %s processed without dedupe", batch_id, exc_info=True)
        return "unavailable"
    return "duplicate" if state in ("done", b"done") else "in_progress"


async def finish_batch(redis: Redis, batch_id: str) -> None:
    try:
        await redis.set(KEY.format(batch_id), "done", ex=DONE_TTL_S)
    except Exception:
        log.warning("could not mark batch %s as done", batch_id, exc_info=True)


async def release_batch(redis: Redis, batch_id: str) -> None:
    try:
        await redis.delete(KEY.format(batch_id))
    except Exception:
        log.warning("could not release batch %s", batch_id, exc_info=True)
