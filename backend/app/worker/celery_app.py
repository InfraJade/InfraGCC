"""The Celery application shared by the alert worker and the scheduler.

    celery -A app.worker.celery_app worker -Q alerts,notify -c 4 -n alerts@%h        # alert worker
    celery -A app.worker.celery_app worker -B -Q scheduled -c 2 -n scheduler@%h      # scheduler (beat inside)

Tasks are idempotent and acknowledged late (a task interrupted by a crash runs again); one task is prefetched
at a time so a slow notification does not hold up evaluations queued behind it. Results are not stored.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import beat_init, worker_process_init, worker_process_shutdown
from kombu import Queue

from app.core.config import get_settings
from app.worker import names

log = logging.getLogger("gcc.worker")

settings = get_settings()


def _every(seconds: int, task: str) -> dict[str, Any]:
    # A run that has not started by the time the next one is due is dropped, so runs never pile up.
    return {"task": task, "schedule": timedelta(seconds=seconds), "options": {"expires": seconds - 5}}


def _cron(task: str, schedule: crontab) -> dict[str, Any]:
    return {"task": task, "schedule": schedule, "options": {"expires": 3600}}


celery_app = Celery("gcc", broker=settings.celery_broker_url, include=["app.worker.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    result_backend=None,
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=15 * 60,
    task_soft_time_limit=14 * 60,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 20 * 60},
    worker_hijack_root_logger=False,
    task_default_queue=names.QUEUE_ALERTS,
    task_queues=(Queue(names.QUEUE_ALERTS), Queue(names.QUEUE_NOTIFY), Queue(names.QUEUE_SCHEDULED)),
    task_routes={
        "gcc.alerts.*": {"queue": names.QUEUE_ALERTS},
        "gcc.notify.*": {"queue": names.QUEUE_NOTIFY},
        "gcc.scheduled.*": {"queue": names.QUEUE_SCHEDULED},
    },
    beat_schedule={
        "missing-data": _every(30, names.CHECK_MISSING_DATA),
        "collector-heartbeats": _every(30, names.CHECK_COLLECTORS),
        "critical-escalation": _every(60, names.ESCALATE_CRITICAL),
        "event-auto-resolve": _every(15 * 60, names.RESOLVE_STALE_EVENTS),
        "firmware-compliance": _cron(names.FIRMWARE_COMPLIANCE, crontab(hour=2, minute=30)),
        "retention-cleanup": _cron(names.RETENTION_CLEANUP, crontab(hour=3, minute=15)),
        # Monday 03:30 UTC = 09:00 IST.
        "weekly-report": _cron(names.WEEKLY_REPORT, crontab(day_of_week=1, hour=3, minute=30)),
    },
)


@worker_process_init.connect
def _init_worker_process(**_: Any) -> None:
    from app.worker import runtime

    runtime.init_process()


@worker_process_shutdown.connect
def _shutdown_worker_process(**_: Any) -> None:
    from app.worker import runtime

    runtime.shutdown_process()


@beat_init.connect
def _on_beat_start(**_: Any) -> None:
    """Startup jobs, sent once by the scheduler's beat: dev history backfill and a first compliance check."""
    try:
        celery_app.send_task(names.DEV_BACKFILL, queue=names.QUEUE_SCHEDULED)
        celery_app.send_task(names.FIRMWARE_COMPLIANCE, queue=names.QUEUE_SCHEDULED, countdown=600)
    except Exception:
        log.exception("could not queue startup jobs")
