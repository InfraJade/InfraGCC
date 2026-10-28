"""Jade GCC load test runner: measures the running stack against the design targets and writes a report.

    docker compose -f compose.yaml -f infra/loadtest/compose.loadtest.yaml up -d --build
    uv run --project infra/loadtest python infra/loadtest/runner.py            # 5 min warm-up, 10 min window
    uv run --project infra/loadtest python infra/loadtest/runner.py --quick    # 1 min warm-up, 3 min window
    uv run --project infra/loadtest python infra/loadtest/runner.py --skip-live --skip-alert  # queries only

Steps:
 1. history  make sure 30 days of readings + rollups exist (synthetic backfill before the oldest reading)
 2. warm-up  let collectors, ingest and the rollup policies settle
 3. window   every --sample-s: newest-reading age per onboarded server (freshness, ingest lag);
             at the window start an `inlet_spike` fault is injected through the simulator control API and
             the alerts table is polled until the alert opens
 4. queries  the 30-day dashboard queries (queries.py) as gcc_superset_ro, while ingest keeps running
 5. totals   readings/s and per-5-minute reporting share over the window (after a grace period so batches
             still in flight land)
 6. report   infra/loadtest/reports/<timestamp>.md and .json, pass/fail per DESIGN target; exit code 1 if
             any measured target failed

All "now" values come from the database clock (the collectors stamp readings with the same Docker host
clock), so host/VM clock skew does not leak into lag numbers.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import httpx

from analysis import (
    AlertTiming,
    FreshnessSample,
    QueryTiming,
    Report,
    Result,
    evaluate,
    format_value,
    lag_growth,
    not_measured,
    reporting_share,
    standard_targets,
    verdict,
)
from history import PROFILES, ensure_history
from queries import QUERIES, DashboardQuery

HERE = Path(__file__).resolve().parent
DEFAULT_DB_URL = "postgresql://gcc_owner:dev-owner-pw@localhost:15433/gcc"
DEFAULT_RO_DB_URL = "postgresql://gcc_superset_ro:dev-superset-ro-pw@localhost:15433/gcc"
DEFAULT_SIM_URL = "http://localhost:9100"
# Grace after the window so batches already polled (collector batch interval 12 s) reach the database.
INGEST_GRACE_S = 30.0
ALERT_POLL_S = 2.0


def log(msg: str) -> None:
    print(f"{datetime.now(UTC):%H:%M:%S} {msg}", flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db-url", default=os.environ.get("LOADTEST_DB_URL", DEFAULT_DB_URL), help="owner DSN")
    p.add_argument(
        "--ro-db-url",
        default=os.environ.get("LOADTEST_RO_DB_URL", DEFAULT_RO_DB_URL),
        help="Superset read-only DSN for the dashboard queries",
    )
    p.add_argument("--sim-url", default=os.environ.get("LOADTEST_SIM_URL", DEFAULT_SIM_URL))
    p.add_argument("--sim-host", default="bmc-simulator", help="host part of the simulated servers' bmc_host")
    p.add_argument("--sim-base-port", type=int, default=20000)
    p.add_argument("--servers", type=int, default=500, help="expected simulated fleet size")
    p.add_argument("--quick", action="store_true", help="1 min warm-up, 3 min window")
    p.add_argument("--warmup-min", type=float, default=None, help="default 5 (quick: 1)")
    p.add_argument("--window-min", type=float, default=None, help="default 10 (quick: 3)")
    p.add_argument("--sample-s", type=float, default=30.0)
    p.add_argument("--alert-bmc", type=int, default=None, help="simulator BMC index (default: --servers)")
    p.add_argument(
        "--alert-timeout-s",
        type=float,
        default=None,
        help="give up waiting for the alert (default: rule duration + 6 min)",
    )
    p.add_argument("--history-days", type=int, default=30)
    p.add_argument("--history-profile", choices=sorted(PROFILES), default="dashboard")
    p.add_argument("--query-repeats", type=int, default=3)
    p.add_argument("--skip-history", action="store_true")
    p.add_argument(
        "--history-safe",
        action="store_true",
        help="backfill with FK and invalidation triggers on even as superuser (slower)",
    )
    p.add_argument("--skip-live", action="store_true", help="no warm-up/window (queries only)")
    p.add_argument("--skip-alert", action="store_true")
    p.add_argument("--skip-queries", action="store_true")
    p.add_argument("--reports-dir", type=Path, default=HERE / "reports")
    args = p.parse_args(argv)
    if args.warmup_min is None:
        args.warmup_min = 1.0 if args.quick else 5.0
    if args.window_min is None:
        args.window_min = 3.0 if args.quick else 10.0
    if args.alert_bmc is None:
        args.alert_bmc = args.servers
    if args.skip_live:
        args.skip_alert = True
    return args


async def db_now(conn: asyncpg.Connection[Any]) -> datetime:
    value = await conn.fetchval("SELECT now()")
    assert isinstance(value, datetime)
    return value


async def metric_id(conn: asyncpg.Connection[Any], code: str) -> int:
    value = await conn.fetchval("SELECT id FROM metric_definitions WHERE code = $1", code)
    if not isinstance(value, int):
        raise RuntimeError(f"metric {code!r} missing from metric_definitions")
    return value


async def environment(conn: asyncpg.Connection[Any]) -> dict[str, Any]:
    servers = await conn.fetchval("SELECT count(*) FROM servers WHERE status <> 'decommissioned'")
    by_collector = await conn.fetch(
        """
        SELECT c.name, count(s.id) AS servers, c.last_heartbeat
        FROM collectors c LEFT JOIN servers s ON s.collector_id = c.id AND s.status <> 'decommissioned'
        GROUP BY c.id ORDER BY c.name
        """
    )
    pg = await conn.fetchval("SHOW server_version")
    ts = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
    return {
        "onboarded_servers": servers,
        "collectors": ", ".join(
            f"{r['name']} ({r['servers']} servers, heartbeat {r['last_heartbeat'] or 'never'})"
            for r in by_collector
        ),
        "postgresql": pg,
        "timescaledb": ts,
    }


# ------------------------------------------------------------------------------------------- live window


async def sample_freshness(conn: asyncpg.Connection[Any], reachable_id: int) -> FreshnessSample:
    """Newest reading age per onboarded server. `bmc_reachable = 0` rows alone do not count as data."""
    rows = await conn.fetch(
        """
        SELECT now() AS now, extract(epoch FROM now() - max(lr.time))::float8 AS age_s
        FROM servers s
        LEFT JOIN latest_readings lr ON lr.server_id = s.id AND lr.metric_code <> $1
        WHERE s.status <> 'decommissioned'
        GROUP BY s.id
        """,
        reachable_id,
    )
    now = rows[0]["now"] if rows else await db_now(conn)
    ages = [float(r["age_s"]) if r["age_s"] is not None else math.inf for r in rows]
    return FreshnessSample(time=now, servers=len(rows), ages_s=ages)


async def window_totals(
    conn: asyncpg.Connection[Any], start: datetime, end: datetime, reachable_id: int
) -> tuple[int, list[dict[str, Any]], list[int]]:
    """Readings in [start, end), per-minute throughput, and servers seen per full 5-minute bucket."""
    total = await conn.fetchval("SELECT count(*) FROM readings WHERE time >= $1 AND time < $2", start, end)
    per_min = await conn.fetch(
        """
        SELECT time_bucket('1 minute', time) AS minute, count(*) AS readings,
               count(DISTINCT server_id) AS servers
        FROM readings WHERE time >= $1 AND time < $2
        GROUP BY 1 ORDER BY 1
        """,
        start,
        end,
    )
    # Full 5-minute buckets inside the window; a window shorter than 5 minutes is one bucket.
    first = datetime.fromtimestamp(math.ceil(start.timestamp() / 300) * 300, tz=UTC)
    buckets: list[tuple[datetime, datetime]] = []
    b = first
    while b + timedelta(minutes=5) <= end:
        buckets.append((b, b + timedelta(minutes=5)))
        b += timedelta(minutes=5)
    if not buckets:
        buckets = [(start, end)]
    seen: list[int] = []
    for lo, hi in buckets:
        n = await conn.fetchval(
            """
            SELECT count(DISTINCT server_id) FROM readings
            WHERE time >= $1 AND time < $2 AND metric_code <> $3
            """,
            lo,
            hi,
            reachable_id,
        )
        seen.append(int(n or 0))
    rows = [
        {
            "minute": r["minute"].isoformat(timespec="minutes"),
            "readings": r["readings"],
            "servers": r["servers"],
        }
        for r in per_min
    ]
    return int(total or 0), rows, seen


@dataclass
class AlertOutcome:
    timing: AlertTiming | None
    info: dict[str, Any]
    error: str | None = None


async def measure_alert(args: argparse.Namespace, db_url: str) -> AlertOutcome:
    """Inject an inlet spike on one simulated BMC and time how long until its alert row appears.

    Fair measure (DESIGN: "alert raised within 2 minutes of a reading crossing its threshold"): the clock
    starts when the rule *could* first fire, i.e. at the first ingested inlet reading above the threshold
    plus the rule's hold duration (3 minutes, D14). Polling delay before that reading (collector interval)
    and the hold duration are reported separately, not counted against the target.
    """
    info: dict[str, Any] = {"bmc_index": args.alert_bmc}
    conn = await asyncpg.connect(db_url)
    fault_id: int | None = None
    async with httpx.AsyncClient(base_url=args.sim_url, timeout=10.0) as sim:
        try:
            host = f"http://{args.sim_host}:{args.sim_base_port + args.alert_bmc}"
            server_id = await conn.fetchval("SELECT id FROM servers WHERE bmc_host = $1", host)
            if not isinstance(server_id, int):
                return AlertOutcome(None, info, f"no onboarded server with bmc_host {host}")
            inlet = await metric_id(conn, "inlet_temp_c")
            rule = await conn.fetchrow(
                """
                SELECT name, duration_s FROM alert_rules
                WHERE rule_type = 'threshold' AND metric_code = $1 AND enabled ORDER BY id LIMIT 1
                """,
                inlet,
            )
            if rule is None:
                return AlertOutcome(None, info, "no enabled inlet threshold rule")
            threshold = await conn.fetchval(
                """
                SELECT warning FROM thresholds
                WHERE metric_code = $1 AND (scope = 'global' OR server_id = $2)
                ORDER BY (scope = 'server') DESC LIMIT 1
                """,
                inlet,
                server_id,
            )
            threshold = float(threshold) if threshold is not None else 27.0
            info.update(
                server_id=server_id,
                rule=rule["name"],
                rule_duration_s=rule["duration_s"],
                threshold_c=threshold,
            )
            timeout_s = args.alert_timeout_s or float(rule["duration_s"]) + 360.0

            # Start clean: no fault on this BMC and no open inlet alert for this server.
            bmc = (await sim.get(f"/bmcs/{args.alert_bmc}")).raise_for_status().json()
            for f in bmc.get("faults", []):
                await sim.delete(f"/faults/{f['id']}")
            open_alert = await conn.fetchval(
                "SELECT id FROM alerts WHERE server_id = $1 AND metric_code = $2 AND state <> 'resolved'",
                server_id,
                inlet,
            )
            if open_alert is not None:
                return AlertOutcome(None, info, f"alert {open_alert} already open for this server/metric")
            max_id = await conn.fetchval("SELECT coalesce(max(id), 0) FROM alerts")

            injected_at = await db_now(conn)
            resp = await sim.post(
                "/faults",
                json={"bmc": args.alert_bmc, "kind": "inlet_spike", "duration_s": timeout_s + 60},
            )
            resp.raise_for_status()
            fault_id = int(resp.json()["id"])
            log(f"alert: inlet_spike injected on BMC {args.alert_bmc} (server {server_id}), fault {fault_id}")

            seen_at: datetime | None = None
            opened_at: datetime | None = None
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                row = await conn.fetchrow(
                    """
                    SELECT now() AS now, id, opened_at, severity FROM alerts
                    WHERE server_id = $1 AND metric_code = $2 AND id > $3 ORDER BY id LIMIT 1
                    """,
                    server_id,
                    inlet,
                    max_id,
                )
                if row is not None:
                    seen_at, opened_at = row["now"], row["opened_at"]
                    info.update(alert_id=row["id"], severity=row["severity"])
                    break
                await asyncio.sleep(ALERT_POLL_S)
            first_bad = await conn.fetchval(
                """
                SELECT min(time) FROM readings
                WHERE server_id = $1 AND metric_code = $2 AND component = '' AND time >= $3 AND value > $4
                """,
                server_id,
                inlet,
                injected_at - timedelta(seconds=60),
                threshold,
            )
            timing = AlertTiming(
                injected_at=injected_at,
                first_bad_at=first_bad,
                rule_duration_s=float(rule["duration_s"]),
                alert_seen_at=seen_at,
                alert_opened_at=opened_at,
            )
            info.update(
                injected_at=injected_at.isoformat(timespec="seconds"),
                first_bad_reading_at=first_bad.isoformat(timespec="seconds") if first_bad else None,
                alert_seen_at=seen_at.isoformat(timespec="seconds") if seen_at else None,
                alert_opened_at=opened_at.isoformat(timespec="seconds") if opened_at else None,
                injection_to_first_bad_reading_s=_r(timing.detection_s),
                injection_to_alert_s=_r(timing.end_to_end_s),
                delay_after_hold_duration_s=_r(timing.delay_s),
            )
            if seen_at is None:
                return AlertOutcome(timing, info, f"no alert within {timeout_s:.0f} s")
            if first_bad is None:
                return AlertOutcome(timing, info, "alert opened but no reading above threshold was ingested")
            return AlertOutcome(timing, info)
        except (httpx.HTTPError, OSError) as exc:
            return AlertOutcome(None, info, f"simulator control API: {exc}")
        finally:
            if fault_id is not None:
                try:
                    await sim.delete(f"/faults/{fault_id}")
                except httpx.HTTPError as exc:
                    log(f"alert: could not clear fault {fault_id}: {exc}")
            await conn.close()


def _r(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


# ------------------------------------------------------------------------------------- dashboard queries


async def time_queries(
    owner: asyncpg.Connection[Any], ro_url: str, since: datetime, repeats: int
) -> list[QueryTiming]:
    site_id = await owner.fetchval(
        """
        SELECT site_id FROM servers WHERE status <> 'decommissioned'
        GROUP BY 1 ORDER BY count(*) DESC LIMIT 1
        """
    )
    server_id = await owner.fetchval(
        "SELECT server_id FROM latest_readings GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
    ) or await owner.fetchval("SELECT min(id) FROM servers WHERE status <> 'decommissioned'")
    ro = await asyncpg.connect(ro_url)
    timings: list[QueryTiming] = []
    try:
        await ro.execute("SET statement_timeout = '60s'")
        for q in QUERIES:
            timings.append(await _time_query(ro, q, since, site_id, server_id, repeats))
            t = timings[-1]
            log(
                f"query {q.name}: rows {t.rows}, runs "
                + ", ".join(f"{s:.2f}s" for s in t.runs_s)
                + (f" ERROR {t.error}" if t.error else "")
            )
    finally:
        await ro.close()
    return timings


async def _time_query(
    ro: asyncpg.Connection[Any],
    q: DashboardQuery,
    since: datetime,
    site_id: int | None,
    server_id: int | None,
    repeats: int,
) -> QueryTiming:
    params: list[Any] = [since]
    if q.scope == "site":
        params.append(site_id)
    elif q.scope == "server":
        params.append(server_id)
    runs: list[float] = []
    rows = 0
    try:
        for _ in range(repeats):
            t0 = time.perf_counter()
            result = await ro.fetch(q.sql, *params)
            runs.append(time.perf_counter() - t0)
            rows = len(result)
    except asyncpg.PostgresError as exc:
        return QueryTiming(q.name, q.description, q.view, runs, rows, error=str(exc).splitlines()[0])
    return QueryTiming(q.name, q.description, q.view, runs, rows)


# -------------------------------------------------------------------------------------------- main flow


async def run(args: argparse.Namespace) -> Report:
    started = datetime.now(UTC)
    conn = await asyncpg.connect(args.db_url)
    try:
        env = await environment(conn)
        onboarded = int(env["onboarded_servers"])
        log(f"stack: {onboarded} onboarded servers; {env['collectors']}")
        targets = standard_targets(onboarded)
        notes: list[str] = []
        if onboarded < args.servers:
            notes.append(f"Only {onboarded} servers onboarded (expected {args.servers}).")
        reachable_id = await metric_id(conn, "bmc_reachable")

        history: dict[str, Any] = {}
        if not args.skip_queries and not args.skip_history:
            history = await ensure_history(
                conn,
                days=args.history_days,
                profile=args.history_profile,
                log=log,
                allow_fast=not args.history_safe,
            )
            env["history"] = ", ".join(f"{k}={v}" for k, v in history.items())

        results: list[Result] = []
        samples: list[FreshnessSample] = []
        per_min: list[dict[str, Any]] = []
        alert_info: dict[str, Any] = {}
        alert_task: asyncio.Task[AlertOutcome] | None = None
        timings: list[QueryTiming] = []

        if not args.skip_live:
            log(f"warm-up {args.warmup_min:g} min")
            await asyncio.sleep(args.warmup_min * 60)
            start = await db_now(conn)
            end_mono = time.monotonic() + args.window_min * 60
            log(f"window {args.window_min:g} min from {start:%H:%M:%S} UTC (db clock)")
            if not args.skip_alert:
                alert_task = asyncio.create_task(measure_alert(args, args.db_url))
            while True:
                s = await sample_freshness(conn, reachable_id)
                samples.append(s)
                log(
                    f"sample: fresh {s.fresh_pct:.2f} %, lag p95 {format_value(s.lag(95), 's')}, "
                    f"servers {s.servers}"
                )
                remaining = end_mono - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(args.sample_s, remaining))
            end = await db_now(conn)

        if not args.skip_queries:
            since = await db_now(conn) - timedelta(days=args.history_days)
            log("dashboard queries (30 days) as the Superset read-only role")
            timings = await time_queries(conn, args.ro_db_url, since, args.query_repeats)

        if not args.skip_live:
            await asyncio.sleep(INGEST_GRACE_S)
            total, per_min, seen = await window_totals(conn, start, end, reachable_id)
            secs = (end - start).total_seconds()
            rate = total / secs if secs > 0 else 0.0
            results.append(evaluate(targets["readings_per_s"], rate, f"{total:,} readings in {secs:.0f} s"))
            worst_bucket = reporting_share(seen, onboarded)
            results.append(
                evaluate(
                    targets["servers_reporting"],
                    worst_bucket,
                    f"servers seen per 5-min bucket: {seen} of {onboarded}",
                )
            )
            fresh = [s.fresh_pct for s in samples]
            p95s = [p for s in samples if (p := s.lag(95)) is not None]
            results.append(evaluate(targets["live_freshness"], min(fresh), f"{len(samples)} samples"))
            results.append(
                evaluate(
                    targets["ingest_lag_p95"],
                    max(p95s) if p95s else None,
                    f"median of samples {sorted(p95s)[len(p95s) // 2]:.1f} s" if p95s else "",
                )
            )
            results.append(
                evaluate(targets["ingest_lag_growth"], lag_growth(p95s) if len(p95s) >= 3 else None)
            )
        else:
            for key in (
                "readings_per_s",
                "servers_reporting",
                "live_freshness",
                "ingest_lag_p95",
                "ingest_lag_growth",
            ):
                results.append(not_measured(targets[key], "--skip-live"))

        if alert_task is not None:
            log("waiting for the alert measurement to finish")
            outcome = await alert_task
            alert_info = outcome.info
            delay = outcome.timing.delay_s if outcome.timing else None
            results.append(evaluate(targets["alert_delay"], delay, outcome.error or ""))
        else:
            results.append(not_measured(targets["alert_delay"], "--skip-alert"))

        if timings:
            ok = [t.max_s for t in timings if t.max_s is not None and t.error is None]
            errors = [t.name for t in timings if t.error]
            slowest = max(timings, key=lambda t: t.max_s or 0.0)
            value = None if errors or not ok else max(ok)
            detail = f"slowest: {slowest.name}" if not errors else f"errors: {', '.join(errors)}"
            res = evaluate(targets["dashboard_30d"], value, detail)
            if errors:
                res.passed = False
            results.append(res)
        else:
            results.append(not_measured(targets["dashboard_30d"], "--skip-queries"))

        params = {
            "servers_expected": args.servers,
            "warmup_min": 0 if args.skip_live else args.warmup_min,
            "window_min": 0 if args.skip_live else args.window_min,
            "sample_s": args.sample_s,
            "history_days": args.history_days,
            "history_profile": args.history_profile,
            "query_repeats": args.query_repeats,
            "alert_bmc": None if args.skip_alert else args.alert_bmc,
        }
        return Report(
            started_at=started,
            finished_at=datetime.now(UTC),
            parameters=params,
            environment=env,
            results=results,
            queries=timings,
            samples=[s.to_row() for s in samples],
            alert=alert_info,
            throughput_per_min=per_min,
            notes=notes,
        )
    finally:
        await conn.close()


def write_report(report: Report, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.strftime("%Y%m%dT%H%M%SZ")
    md = reports_dir / f"{stamp}.md"
    js = reports_dir / f"{stamp}.json"
    md.write_text(report.to_markdown(), encoding="utf-8", newline="\n")
    js.write_text(report.to_json() + "\n", encoding="utf-8", newline="\n")
    return md, js


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = asyncio.run(run(args))
    md, js = write_report(report, args.reports_dir)
    for r in report.results:
        log(f"{verdict(r.passed):>12}  {r.name}: {format_value(r.value, r.unit)} (target {r.target})")
    log(f"overall {verdict(report.passed)}; report {md} and {js.name}")
    return 1 if report.passed is False else 0


if __name__ == "__main__":
    sys.exit(main())
