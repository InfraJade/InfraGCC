"""Celery task names and queues, importable without loading the task modules (the ingest API uses them)."""

from __future__ import annotations

QUEUE_ALERTS = "alerts"
QUEUE_NOTIFY = "notify"
QUEUE_SCHEDULED = "scheduled"

EVALUATE_SERVERS = "gcc.alerts.evaluate_servers"
SEND_NOTIFICATION = "gcc.notify.send_notification"
CHECK_MISSING_DATA = "gcc.scheduled.check_missing_data"
CHECK_COLLECTORS = "gcc.scheduled.check_collector_heartbeats"
ESCALATE_CRITICAL = "gcc.scheduled.escalate_critical"
FIRMWARE_COMPLIANCE = "gcc.scheduled.firmware_compliance"
RESOLVE_STALE_EVENTS = "gcc.scheduled.resolve_stale_events"
RETENTION_CLEANUP = "gcc.scheduled.retention_cleanup"
WEEKLY_REPORT = "gcc.scheduled.weekly_report"
DEV_BACKFILL = "gcc.scheduled.dev_backfill"
