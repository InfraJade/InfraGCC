"""Queueing alert evaluation from the ingest API, coalesced per server.

A burst of batches touching the same server should cause one evaluation, not one per batch. Before sending a
task the ingest API sets `gcc:alerts:pending:<server_id>` (NX, short TTL); only servers whose marker was not
already set are sent. The evaluation task deletes the markers of its servers *before* reading data, so a
batch committed after that point queues a fresh evaluation. If Redis is down every server is sent (correct,
just less efficient); if the broker is down the error is logged and the batch still succeeds.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from typing import Any

from redis.asyncio import Redis

from app.worker import names

log = logging.getLogger("gcc.worker.enqueue")

PENDING_KEY = "gcc:alerts:pending:{}"
PENDING_TTL_S = 120
SEND_TIMEOUT_S = 3.0

TaskSender = Callable[..., Any]


def _default_sender() -> TaskSender:
    from app.worker.celery_app import celery_app

    return celery_app.send_task


async def claim_servers(redis: Redis | None, server_ids: Sequence[int]) -> list[int]:
    """Server ids that are not already waiting for an evaluation (all of them if Redis is unavailable)."""
    ids = sorted(set(server_ids))
    if redis is None or not ids:
        return ids
    try:
        async with redis.pipeline(transaction=False) as pipe:
            for sid in ids:
                pipe.set(PENDING_KEY.format(sid), "1", nx=True, ex=PENDING_TTL_S)
            results = await pipe.execute()
    except Exception:
        log.warning("Redis unavailable; evaluation is not coalesced", exc_info=True)
        return ids
    return [sid for sid, ok in zip(ids, results, strict=True) if ok]


async def release_servers(redis: Redis | None, server_ids: Sequence[int]) -> None:
    if redis is None or not server_ids:
        return
    try:
        await redis.delete(*(PENDING_KEY.format(sid) for sid in server_ids))
    except Exception:
        log.warning("could not clear pending-evaluation markers", exc_info=True)


async def enqueue_evaluation(
    server_ids: Sequence[int], redis: Redis | None, sender: TaskSender | None = None
) -> list[int]:
    """Queue `gcc.alerts.evaluate_servers` for servers not already queued. Returns the ids sent."""
    ids = await claim_servers(redis, server_ids)
    if not ids:
        return []
    send = sender or _default_sender()
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                send, names.EVALUATE_SERVERS, args=[ids], queue=names.QUEUE_ALERTS, retry=False
            ),
            timeout=SEND_TIMEOUT_S,
        )
    except Exception:
        log.exception("could not queue alert evaluation for %d servers", len(ids))
        await release_servers(redis, ids)
        return []
    return ids
