"""Celery tasks. Names and queues are in `app.worker.names`; the bodies are in `app.worker.jobs`."""

from __future__ import annotations

from typing import Any

from app.worker import jobs, names
from app.worker.celery_app import celery_app
from app.worker.runtime import run


@celery_app.task(name=names.EVALUATE_SERVERS)
def evaluate_servers(server_ids: list[int]) -> int:
    return run(jobs.evaluate_servers(server_ids))


@celery_app.task(name=names.SEND_NOTIFICATION)
def send_notification(alert_id: int, kind: str, level: int = 0) -> int:
    return sum(1 for r in run(jobs.send_notification(alert_id, kind, level)) if r.ok)


@celery_app.task(name=names.CHECK_MISSING_DATA)
def check_missing_data() -> dict[str, int]:
    return run(jobs.check_missing_data())


@celery_app.task(name=names.CHECK_COLLECTORS)
def check_collector_heartbeats() -> dict[str, int]:
    return run(jobs.check_collector_heartbeats())


@celery_app.task(name=names.ESCALATE_CRITICAL)
def escalate_critical() -> int:
    return run(jobs.escalate_critical())


@celery_app.task(name=names.FIRMWARE_COMPLIANCE)
def firmware_compliance() -> dict[str, int]:
    return run(jobs.firmware_compliance())


@celery_app.task(name=names.RESOLVE_STALE_EVENTS)
def resolve_stale_events() -> int:
    return run(jobs.resolve_events())


@celery_app.task(name=names.RETENTION_CLEANUP)
def retention_cleanup() -> dict[str, int]:
    return run(jobs.retention_cleanup())


@celery_app.task(name=names.WEEKLY_REPORT)
def weekly_report() -> bool:
    return run(jobs.weekly_report())


@celery_app.task(name=names.DEV_BACKFILL, time_limit=30 * 60, soft_time_limit=29 * 60)
def dev_backfill() -> dict[str, Any]:
    return run(jobs.dev_backfill())
