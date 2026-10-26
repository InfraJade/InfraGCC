"""`/ingest/v1`: config, batches and heartbeat (docs/contracts/README.md)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from prometheus_client import Counter, Histogram
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.live import HealthMessage, ReadingsMessage, publish
from app.core.problems import Problem
from app.core.redis import get_redis
from app.ingest.auth import current_collector
from app.ingest.body import read_body
from app.ingest.catalog import load_catalog
from app.ingest.dedupe import claim_batch, finish_batch, release_batch
from app.ingest.schemas import (
    AssignedServerOut,
    BatchIn,
    BatchOut,
    CollectorInfo,
    CollectorSettings,
    ConfigOut,
    HeartbeatIn,
    HeartbeatOut,
)
from app.ingest.writer import WriteResult, write_batch
from app.models import Collector, Server
from app.services.assignment import Assignment, collector_settings, compute_assignment, config_version
from app.worker.enqueue import enqueue_evaluation

log = logging.getLogger("gcc.ingest")

router = APIRouter(prefix="/ingest/v1", tags=["ingest"])

BATCHES = Counter("gcc_ingest_batches_total", "Batches received", ["result"])
READINGS = Counter("gcc_ingest_readings_total", "Readings written")
REJECTED_SERVERS = Counter("gcc_ingest_rejected_servers_total", "Server payloads not assigned to the sender")
BATCH_SECONDS = Histogram("gcc_ingest_batch_seconds", "Time to write one batch")
INGEST_LAG = Histogram(
    "gcc_ingest_lag_seconds",
    "Age of the newest reading in a batch when it is written",
    buckets=(1, 2, 5, 10, 15, 30, 60, 120, 300, 900, 3600),
)
SIDE_EFFECT_TIMEOUT_S = 3.0


def now_utc() -> datetime:
    return datetime.now(UTC)


async def _assignment(session: AsyncSession, collector: Collector) -> tuple[Assignment, dict[str, int], str]:
    settings = get_settings()
    assignment = await compute_assignment(session, collector, now_utc(), settings.collector_offline_after_s)
    defaults = CollectorSettings(config_refresh_s=settings.collector_config_refresh_s).model_dump()
    merged = await collector_settings(session, defaults)
    return assignment, merged, config_version(assignment, merged)


@router.get("/config", response_model=ConfigOut)
async def get_config(
    collector: Collector = Depends(current_collector), session: AsyncSession = Depends(get_session)
) -> ConfigOut:
    assignment, merged, version = await _assignment(session, collector)
    return ConfigOut(
        collector=CollectorInfo(id=collector.id, name=collector.name, site_code=assignment.site_code),
        config_version=version,
        settings=CollectorSettings(**merged),
        servers=[
            AssignedServerOut(
                id=s.id,
                bmc_host=s.bmc_host,
                vendor=s.vendor,
                status=s.status,
                credential_ref="default",
                takeover=s.takeover,
            )
            for s in assignment.servers
        ],
    )


def _parse_batch(body: bytes) -> BatchIn:
    try:
        return BatchIn.model_validate_json(body)
    except ValidationError as exc:
        errors = [
            {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()[:50]
        ]
        raise Problem(422, "The batch did not pass validation.", errors=errors) from exc


@router.post("/batches", response_model=BatchOut)
async def post_batch(
    request: Request,
    collector: Collector = Depends(current_collector),
    session: AsyncSession = Depends(get_session),
) -> BatchOut:
    settings = get_settings()
    batch = _parse_batch(await read_body(request, settings.ingest_max_body_bytes))
    if batch.collector != collector.name:
        raise Problem(403, "The batch names a different collector than the credentials.")
    redis = get_redis()
    claim = await claim_batch(redis, batch.batch_id)
    if claim == "duplicate":
        BATCHES.labels("duplicate").inc()
        return BatchOut(batch_id=batch.batch_id, duplicate=True, servers=0, readings=0, events=0)
    if claim == "in_progress":
        # 5xx, not 409: collectors drop batches on most 4xx and keep them buffered on 5xx.
        raise Problem(503, "This batch is being processed; retry shortly.", headers={"Retry-After": "5"})

    started = time.monotonic()
    try:
        assignment, _, _ = await _assignment(session, collector)
        allowed = assignment.server_ids
        accepted = [p for p in batch.servers if p.server_id in allowed]
        rejected = sorted({p.server_id for p in batch.servers if p.server_id not in allowed})
        if rejected:
            REJECTED_SERVERS.inc(len(rejected))
            log.warning("collector %s sent servers it is not assigned: %s", collector.name, rejected)
        site_by_server: dict[int, int] = {}
        if accepted:
            rows = await session.execute(
                select(Server.id, Server.site_id).where(Server.id.in_({p.server_id for p in accepted}))
            )
            site_by_server = dict(rows.all())
        catalog = await load_catalog(session)
        result = await write_batch(session, accepted, site_by_server, catalog, now_utc())
        await session.commit()
    except BaseException as exc:
        try:
            await session.rollback()
        except Exception:
            log.warning("rollback failed", exc_info=True)
        if claim == "new":
            await release_batch(redis, batch.batch_id)
        BATCHES.labels("error").inc()
        if isinstance(exc, DBAPIError | OSError | TimeoutError):
            # Transient: the collector keeps the batch buffered and retries.
            log.exception("batch %s could not be written", batch.batch_id)
            raise Problem(503, "The batch could not be stored right now; retry later.") from exc
        raise
    if claim == "new":
        await finish_batch(redis, batch.batch_id)
    BATCH_SECONDS.observe(time.monotonic() - started)
    BATCHES.labels("ok").inc()
    READINGS.inc(result.readings)
    newest = max((r.time for p in accepted for r in (p.readings or ())), default=None)
    if newest is not None:
        INGEST_LAG.observe(max(0.0, (now_utc() - newest).total_seconds()))

    touched = sorted({p.server_id for p in accepted if p.readings or p.events})
    try:
        await asyncio.wait_for(_after_commit(redis, result, touched), timeout=SIDE_EFFECT_TIMEOUT_S)
    except Exception:
        log.warning("live publish / alert enqueue did not complete", exc_info=True)
    return BatchOut(
        batch_id=batch.batch_id,
        duplicate=False,
        servers=len(accepted),
        readings=result.readings,
        events=result.events,
    )


async def _after_commit(redis: Redis, result: WriteResult, touched: list[int]) -> None:
    """Live updates and alert evaluation. Failures are logged; the batch is already stored."""
    try:
        for sr in result.servers.values():
            if sr.readings:
                await publish(
                    redis, ReadingsMessage(server_id=sr.server_id, site_id=sr.site_id, readings=sr.readings)
                )
            if sr.health_changes:
                await publish(
                    redis,
                    HealthMessage(
                        server_id=sr.server_id,
                        site_id=sr.site_id,
                        changes=sr.health_changes,
                        server_health=sr.server_health,
                    ),
                )
    except Exception:
        log.warning("could not publish live updates", exc_info=True)
    if touched:
        await enqueue_evaluation(touched, redis)


@router.post("/heartbeat", response_model=HeartbeatOut)
async def heartbeat(
    body: HeartbeatIn,
    collector: Collector = Depends(current_collector),
    session: AsyncSession = Depends(get_session),
) -> HeartbeatOut:
    if body.collector != collector.name:
        raise Problem(403, "The heartbeat names a different collector than the credentials.")
    stats: dict[str, Any] = body.stats.model_dump(mode="json")
    stats["sent_at"] = body.sent_at.isoformat()
    stats["config_version"] = body.config_version
    values: dict[str, Any] = {"last_heartbeat": func.now(), "stats": stats, "updated_at": func.now()}
    if body.version is not None:
        values["version"] = body.version
    if body.hostname is not None:
        values["hostname"] = body.hostname
    await session.execute(
        update(Collector).where(Collector.id == collector.id).values(**values),
        execution_options={"synchronize_session": False},
    )
    await session.commit()
    _, _, version = await _assignment(session, collector)
    return HeartbeatOut(ok=True, config_version=version)
