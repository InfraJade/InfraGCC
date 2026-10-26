"""Celery wiring, evaluation coalescing, job bodies end to end, dev backfill, retention and weekly report."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import fakeredis
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import get_settings
from app.core.live import LIVE_CHANNEL
from app.services.alerts.effects import NotifyRequest
from app.services.backfill import generate_rows, run_backfill, sim_index
from app.worker import jobs, names
from app.worker.enqueue import PENDING_KEY, enqueue_evaluation
from tests.ingest.fixtures import TaskRecorder, World, add_readings


def test_celery_app_tasks_queues_and_beat() -> None:
    import app.worker.tasks  # noqa: F401  (registers the tasks)
    from app.worker.celery_app import celery_app

    conf = celery_app.conf
    registered = set(celery_app.tasks)
    for name in (
        names.EVALUATE_SERVERS,
        names.SEND_NOTIFICATION,
        names.CHECK_MISSING_DATA,
        names.CHECK_COLLECTORS,
        names.ESCALATE_CRITICAL,
        names.FIRMWARE_COMPLIANCE,
        names.RESOLVE_STALE_EVENTS,
        names.RETENTION_CLEANUP,
        names.WEEKLY_REPORT,
        names.DEV_BACKFILL,
    ):
        assert name in registered
    assert {q.name for q in conf.task_queues} == {"alerts", "notify", "scheduled"}
    assert conf.task_serializer == "json" and conf.accept_content == ["json"]
    assert conf.task_acks_late and conf.worker_prefetch_multiplier == 1
    beat = {v["task"]: v["schedule"] for v in conf.beat_schedule.values()}
    assert beat[names.CHECK_MISSING_DATA] == timedelta(seconds=30)
    assert beat[names.CHECK_COLLECTORS] == timedelta(seconds=30)
    assert beat[names.ESCALATE_CRITICAL] == timedelta(seconds=60)
    assert set(beat) >= {names.FIRMWARE_COMPLIANCE, names.RETENTION_CLEANUP, names.WEEKLY_REPORT}
    route = celery_app.amqp.router.route({}, names.SEND_NOTIFICATION)
    assert route["queue"].name == "notify"


async def test_enqueue_coalesces_per_server() -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    sent = TaskRecorder()
    assert await enqueue_evaluation([3, 1, 3], redis, sent) == [1, 3]
    assert await enqueue_evaluation([1, 2], redis, sent) == [2]  # 1 is still waiting
    assert sent.calls[0] == (names.EVALUATE_SERVERS, {"args": [[1, 3]], "queue": "alerts", "retry": False})
    await redis.delete(PENDING_KEY.format(1))  # the task started
    assert await enqueue_evaluation([1], redis, sent) == [1]

    broken = TaskRecorder(fail=True)
    assert await enqueue_evaluation([9], redis, broken) == []
    assert await redis.get(PENDING_KEY.format(9)) is None  # released so the next batch retries
    # Without Redis every server is sent.
    assert await enqueue_evaluation([4, 5], None, sent) == [4, 5]
    await redis.aclose()


def test_runtime_runs_coroutines_on_its_own_loop() -> None:
    from app.worker import runtime

    out: list[int] = []

    async def work() -> int:
        await asyncio.sleep(0)
        return 42

    def in_thread() -> None:
        out.append(runtime.run(work()))
        out.append(runtime.run(work()))

    t = threading.Thread(target=in_thread)
    t.start()
    t.join()
    assert out == [42, 42]


@pytest.mark.db
async def test_evaluate_job_publishes_and_queues_notifications(
    world: World, session: AsyncSession, use_app_engine: AsyncEngine
) -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(LIVE_CHANNEL)
    sent: list[NotifyRequest] = []
    now = datetime.now(UTC)
    sid = world.server(0).id
    await redis.set(PENDING_KEY.format(sid), "1")
    await add_readings(session, sid, "bmc_reachable", [(120, 0.0), (60, 0.0), (0, 0.0)], now)

    count = await jobs.evaluate_servers([sid, 999_999], jobs.Outputs(redis, sent.append), now)
    assert count == 1
    assert await redis.get(PENDING_KEY.format(sid)) is None
    assert [(r.kind, r.level) for r in sent] == [("opened", 0)]
    msg = None
    for _ in range(5):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1) or msg
    assert msg is not None
    body = json.loads(msg["data"])
    assert body["type"] == "alert" and body["change"] == "opened" and body["server_id"] == sid
    await pubsub.aclose()  # type: ignore[no-untyped-call]
    await redis.aclose()


@pytest.mark.db
async def test_scheduled_jobs_run_as_app_role(
    world: World, session: AsyncSession, use_app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    out = jobs.Outputs(redis, lambda req: None)
    now = datetime.now(UTC)
    assert await jobs.check_missing_data(out, now) == {"fired": 0, "resolved": 0}
    assert await jobs.check_collector_heartbeats(out, now + timedelta(minutes=10)) == {
        "fired": 3,
        "resolved": 0,
    }
    assert await jobs.escalate_critical(out, now + timedelta(hours=1)) == 3
    assert (await jobs.firmware_compliance(out, now))["deviations"] == 0
    assert await jobs.resolve_events(out, now) == 0

    # Retention: 3-year-old events, resolved alerts and audit entries go; recent ones stay.
    old = now - timedelta(days=3 * 365 + 5)
    sid = world.server(0).id
    await session.execute(
        text(
            "INSERT INTO events (server_id, time, severity, message, entry_id) VALUES "
            "(:s, :old, 'Critical', 'x', 'a'), (:s, :now, 'Critical', 'y', 'b')"
        ),
        {"s": sid, "old": old, "now": now},
    )
    await session.execute(
        text(
            "INSERT INTO audit_log (time, user_name, action, object_type) VALUES (:old, 'u', 'x', 'y'), (:now, 'u', 'x', 'y')"
        ),
        {"old": old, "now": now},
    )
    await session.execute(
        text(
            "UPDATE alerts SET state = 'resolved', resolved_at = :old, opened_at = :old WHERE collector_id IS NOT NULL"
        ),
        {"old": old},
    )
    await session.commit()
    assert await jobs.retention_cleanup(now) == {"events": 1, "alerts": 3, "audit_log": 1}

    # Weekly report goes to REPORT_RECIPIENTS.
    sent: list[EmailMessage] = []

    async def fake_send(message: EmailMessage, **_: Any) -> None:
        sent.append(message)

    monkeypatch.setattr("aiosmtplib.send", fake_send)
    monkeypatch.setattr(get_settings(), "report_recipients", [])
    assert await jobs.weekly_report(now) is False
    monkeypatch.setattr(get_settings(), "report_recipients", ["ops@gcc.example"])
    assert await jobs.weekly_report(now) is True
    assert sent[0]["To"] == "ops@gcc.example" and "Weekly summary" in sent[0]["Subject"]
    await redis.aclose()


def test_backfill_rows_are_plausible() -> None:
    ids = {c: i for i, c in enumerate(["inlet_temp_c", "exhaust_temp_c", "cpu_temp_c", "fan_rpm", "fan_pct",
                                       "power_w", "psu_input_v"], start=1)}  # fmt: skip
    start = datetime(2026, 10, 1, tzinfo=UTC)
    rows = generate_rows(5, 2, ids, start, start + timedelta(hours=1))  # HPE DL380: fans in percent
    assert len(rows) == 12 * (1 + 1 + 1 + 2 + 6 + 2)
    by_metric: dict[int, list[float]] = {}
    for _, sid, mid, _, value, _ in rows:
        assert sid == 5
        by_metric.setdefault(mid, []).append(value)
    assert ids["fan_rpm"] not in by_metric
    assert all(15 < v < 32 for v in by_metric[ids["inlet_temp_c"]])
    assert all(200 < v < 700 for v in by_metric[ids["power_w"]])
    assert all(220 < v < 240 for v in by_metric[ids["psu_input_v"]])
    assert sim_index("http://bmc-simulator:20007", 20000) == 7
    assert sim_index("http://redfish-dell:8000", 20000) is None


@pytest.mark.db
async def test_backfill_runs_once_and_fills_rollups(
    world: World, session: AsyncSession, app_engine: AsyncEngine, engine: AsyncEngine
) -> None:
    settings = get_settings().model_copy(
        # 6 hours keeps the test fast (~10k rows); the code path is the same as the 7-day default.
        update={"app_env": "dev", "dev_backfill_enabled": True, "dev_backfill_days": 0.25}
    )
    result = await run_backfill(app_engine, settings, owner_engine=engine)
    assert result.ran and result.servers == 10 and result.rows >= 10 * 72 * 13
    assert result.seconds < 60
    await session.rollback()
    counts = (
        await session.execute(
            text(
                "SELECT (SELECT count(*) FROM readings WHERE time < now() - interval '3 hours'),"
                " (SELECT count(DISTINCT server_id) FROM readings_1h),"
                " (SELECT count(*) FROM readings_5m WHERE bucket < now() - interval '3 hours')"
            )
        )
    ).one()
    assert counts[0] > 0 and counts[1] == 10 and counts[2] > 0
    again = await run_backfill(app_engine, settings, owner_engine=engine)
    assert not again.ran and again.reason == "already done"
    prod = settings.model_copy(update={"app_env": "prod"})
    assert (await run_backfill(app_engine, prod)).reason == "APP_ENV is prod"
