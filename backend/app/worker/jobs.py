"""The async bodies of every Celery task. Tasks in `app.worker.tasks` only run these on the process loop.

Each job commits its database work first and then applies side effects (live messages, notification jobs).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import httpx
from redis.asyncio import Redis

from app.core import db
from app.core.config import get_settings
from app.core.redis import get_redis
from app.services.alerts.effects import Effects, NotifyRequest, NotifySender, flush_effects
from app.services.alerts.escalation import escalate_due
from app.services.alerts.evaluate import evaluate_server, resolve_stale_events
from app.services.alerts.missing import check_collectors, check_servers
from app.services.alerts.retention import cleanup
from app.services.backfill import run_backfill
from app.services.firmware import run_compliance
from app.services.notify.report import build_summary, render_summary
from app.services.notify.senders import send_email
from app.services.notify.service import SendResult, notify_alert
from app.worker import names
from app.worker.enqueue import release_servers

log = logging.getLogger("gcc.worker.jobs")


def utcnow() -> datetime:
    return datetime.now(UTC)


def celery_notify_sender() -> NotifySender:
    from app.worker.celery_app import celery_app

    def send(req: NotifyRequest) -> None:
        celery_app.send_task(
            names.SEND_NOTIFICATION, args=[req.alert_id, req.kind, req.level], queue=names.QUEUE_NOTIFY
        )

    return send


class Outputs:
    """Where side effects go; tests pass their own Redis client and sender."""

    def __init__(self, redis: Redis | None = None, send: NotifySender | None = None) -> None:
        self._redis = redis
        self._send = send

    @property
    def redis(self) -> Redis:
        return self._redis if self._redis is not None else get_redis()

    @property
    def send(self) -> NotifySender:
        return self._send if self._send is not None else celery_notify_sender()

    async def flush(self, effects: Effects) -> None:
        await flush_effects(effects, self.redis, self.send)


async def evaluate_servers(
    server_ids: Sequence[int], out: Outputs | None = None, now: datetime | None = None
) -> int:
    out = out or Outputs()
    await release_servers(out.redis, server_ids)
    evaluated = 0
    for sid in sorted(set(server_ids)):
        effects = Effects()
        try:
            async with db.session_scope() as session:
                if await evaluate_server(session, sid, now or utcnow(), effects):
                    evaluated += 1
        except Exception:
            log.exception("evaluation of server %s failed", sid)
            continue
        await out.flush(effects)
    return evaluated


async def send_notification(
    alert_id: int,
    kind: str,
    level: int = 0,
    now: datetime | None = None,
    http: httpx.AsyncClient | None = None,
) -> list[SendResult]:
    async with db.session_scope() as session:
        return await notify_alert(session, alert_id, kind, level, get_settings(), now or utcnow(), http)


async def check_missing_data(out: Outputs | None = None, now: datetime | None = None) -> dict[str, int]:
    out = out or Outputs()
    effects = Effects()
    async with db.session_scope() as session:
        fired, resolved = await check_servers(
            session, now or utcnow(), effects, get_settings().collector_offline_after_s
        )
    await out.flush(effects)
    return {"fired": fired, "resolved": resolved}


async def check_collector_heartbeats(
    out: Outputs | None = None, now: datetime | None = None
) -> dict[str, int]:
    out = out or Outputs()
    effects = Effects()
    async with db.session_scope() as session:
        fired, resolved = await check_collectors(session, now or utcnow(), effects)
    await out.flush(effects)
    return {"fired": fired, "resolved": resolved}


async def escalate_critical(out: Outputs | None = None, now: datetime | None = None) -> int:
    out = out or Outputs()
    effects = Effects()
    async with db.session_scope() as session:
        count = await escalate_due(session, now or utcnow(), effects, get_settings().escalation_after_s)
    await out.flush(effects)
    return count


async def firmware_compliance(out: Outputs | None = None, now: datetime | None = None) -> dict[str, int]:
    out = out or Outputs()
    effects = Effects()
    async with db.session_scope() as session:
        result = await run_compliance(session, now or utcnow(), effects)
    await out.flush(effects)
    return {
        "servers": result.checked_servers,
        "deviations": len(result.deviations),
        "resolved": result.resolved,
    }


async def resolve_events(out: Outputs | None = None, now: datetime | None = None) -> int:
    out = out or Outputs()
    effects = Effects()
    async with db.session_scope() as session:
        count = await resolve_stale_events(session, now or utcnow(), effects)
    await out.flush(effects)
    return count


async def retention_cleanup(now: datetime | None = None) -> dict[str, int]:
    async with db.get_sessionmaker()() as session:
        result = await cleanup(session, now or utcnow())
    return asdict(result)


async def weekly_report(now: datetime | None = None) -> bool:
    settings = get_settings()
    if not settings.report_recipients:
        log.info("weekly report skipped: REPORT_RECIPIENTS is empty")
        return False
    async with db.get_sessionmaker()() as session:
        summary = await build_summary(session, now or utcnow())
    await send_email(render_summary(summary, settings, settings.report_recipients), settings)
    return True


async def dev_backfill() -> dict[str, Any]:
    settings = get_settings()
    owner_engine = None
    if settings.migration_database_url is not None:
        # Refreshing rollups needs the schema owner; the owner also loads faster (see backfill).
        owner_engine = db.make_engine(settings.migration_database_url.get_secret_value(), pool_size=1)
    try:
        result = await run_backfill(db.get_engine(), settings, owner_engine=owner_engine)
    finally:
        if owner_engine is not None:
            await owner_engine.dispose()
    return asdict(result)
