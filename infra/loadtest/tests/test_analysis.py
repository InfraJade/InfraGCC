"""Unit tests for the load test's pure logic: statistics, targets, alert timing, history plan, report."""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from analysis import (
    AlertTiming,
    FreshnessSample,
    QueryTiming,
    Report,
    evaluate,
    expected_readings_per_s,
    format_value,
    lag_growth,
    not_measured,
    overall,
    percentile,
    reporting_share,
    share_pct,
    standard_targets,
)
from history import PROFILES, STEP, day_records, floor_step, plan_history
from queries import QUERIES

T0 = datetime(2026, 10, 22, 10, 0, tzinfo=UTC)


class TestPercentile:
    def test_matches_numpy_linear(self) -> None:
        data = [15.0, 20.0, 35.0, 40.0, 50.0]
        assert percentile(data, 0) == 15.0
        assert percentile(data, 100) == 50.0
        assert percentile(data, 50) == 35.0
        assert percentile(data, 40) == pytest.approx(29.0)  # numpy.percentile(data, 40)
        assert percentile(data, 95) == pytest.approx(48.0)

    def test_unsorted_and_single(self) -> None:
        assert percentile([3.0, 1.0, 2.0], 50) == 2.0
        assert percentile([7.0], 95) == 7.0

    def test_infinity_for_silent_servers(self) -> None:
        assert percentile([1.0, 2.0, math.inf], 50) == 2.0
        assert percentile([1.0, 2.0, math.inf], 100) == math.inf

    def test_errors(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            percentile([], 50)
        with pytest.raises(ValueError, match="between"):
            percentile([1.0], 101)


def test_share_and_growth() -> None:
    assert share_pct(495, 500) == 99.0
    assert share_pct(1, 0) == 0.0
    assert lag_growth([60.0, 60.0, 60.0, 61.0, 62.0, 90.0]) == pytest.approx(16.0)
    assert lag_growth([60.0, 70.0]) == 0.0
    assert reporting_share([500, 497, 499], 500) == pytest.approx(99.4)
    assert reporting_share([], 500) is None


class TestTargets:
    def test_scaled_throughput(self) -> None:
        assert expected_readings_per_s(500) == 330.0
        targets = standard_targets(250)
        assert targets["readings_per_s"].threshold == pytest.approx(148.5)

    @pytest.mark.parametrize(
        ("key", "value", "passed"),
        [
            ("servers_reporting", 99.0, True),
            ("servers_reporting", 98.99, False),
            ("live_freshness", 100.0, True),
            ("ingest_lag_p95", 119.9, True),
            ("ingest_lag_p95", 120.0, False),
            ("ingest_lag_growth", 15.0, True),
            ("alert_delay", 30.0, True),
            ("alert_delay", 125.0, False),
            ("dashboard_30d", 2.99, True),
            ("dashboard_30d", 3.0, False),
            ("readings_per_s", 300.0, True),
            ("readings_per_s", 296.0, False),
        ],
    )
    def test_boundaries(self, key: str, value: float, passed: bool) -> None:
        result = evaluate(standard_targets(500)[key], value)
        assert result.passed is passed

    def test_overall(self) -> None:
        targets = standard_targets(500)
        ok = evaluate(targets["alert_delay"], 10.0)
        bad = evaluate(targets["dashboard_30d"], 4.0)
        skipped = not_measured(targets["live_freshness"], "--skip-live")
        assert skipped.passed is None
        assert overall([ok, skipped]) is True
        assert overall([ok, bad, skipped]) is False
        assert overall([skipped]) is None


class TestAlertTiming:
    def test_delay_counts_from_hold_duration(self) -> None:
        t = AlertTiming(
            injected_at=T0,
            first_bad_at=T0 + timedelta(seconds=40),
            rule_duration_s=180,
            alert_seen_at=T0 + timedelta(seconds=40 + 180 + 55),
            alert_opened_at=T0 + timedelta(seconds=40 + 180 + 54),
        )
        assert t.detection_s == 40
        assert t.end_to_end_s == 275
        assert t.delay_s == pytest.approx(55)

    def test_early_alert_clamps_to_zero(self) -> None:
        # The window can turn all-bad just before first_bad + duration (last good sample was earlier).
        t = AlertTiming(T0, T0 + timedelta(seconds=60), 180, T0 + timedelta(seconds=230), None)
        assert t.delay_s == 0.0

    def test_missing(self) -> None:
        t = AlertTiming(T0, None, 180, None, None)
        assert t.delay_s is None
        assert t.end_to_end_s is None
        assert t.detection_s is None


def test_freshness_sample() -> None:
    s = FreshnessSample(T0, 4, [30.0, 70.0, 130.0, math.inf])
    assert s.fresh_pct == 50.0
    row = s.to_row()
    assert row["never_reported"] == 1
    assert row["lag_p50_s"] == 100.0
    assert row["lag_max_s"] == math.inf


class TestHistory:
    def test_floor_step(self) -> None:
        assert floor_step(T0 + timedelta(minutes=7, seconds=3)) == T0 + timedelta(minutes=5)

    def test_plan_empty_database(self) -> None:
        plan = plan_history(T0, 30, None)
        assert plan.start == T0 - timedelta(days=30)
        assert plan.end == T0
        assert plan.days == 30

    def test_plan_backfills_only_before_existing(self) -> None:
        earliest = T0 - timedelta(days=7, seconds=17)
        plan = plan_history(T0, 30, earliest)
        assert plan.end == floor_step(earliest)
        assert plan.needed

    def test_plan_already_covered(self) -> None:
        plan = plan_history(T0, 30, T0 - timedelta(days=30))
        assert not plan.needed

    def test_day_records(self) -> None:
        series = [(1, "inlet_temp_c", ""), (3, "cpu_temp_c", "CPU1")]
        rows = list(day_records([10, 11], series, T0, T0 + 3 * STEP, seed=1))
        assert len(rows) == 3 * 2 * 2
        assert {r[0] for r in rows} == {T0, T0 + STEP, T0 + 2 * STEP}
        inlet = [r[4] for r in rows if r[2] == 1]
        assert all(15 < v < 30 for v in inlet)
        assert rows == list(day_records([10, 11], series, T0, T0 + 3 * STEP, seed=1))

    def test_profiles_have_unique_series(self) -> None:
        for series in PROFILES.values():
            assert len(series) == len(set(series))
        assert len(PROFILES["handful"]) == 5


def test_queries_are_named_and_parameterised() -> None:
    names = [q.name for q in QUERIES]
    assert len(names) == len(set(names))
    for q in QUERIES:
        assert "$1" in q.sql
        assert ("$2" in q.sql) == (q.scope != "fleet")
        assert f"reporting.{q.view}" in q.sql


def test_report_rendering() -> None:
    targets = standard_targets(500)
    report = Report(
        started_at=T0,
        finished_at=T0 + timedelta(minutes=16),
        parameters={"servers_expected": 500, "window_min": 10},
        environment={"onboarded_servers": 503},
        results=[
            evaluate(targets["readings_per_s"], 412.5, "247,500 readings in 600 s"),
            evaluate(targets["dashboard_30d"], 3.4, "slowest: power_site_5m"),
            not_measured(targets["alert_delay"], "--skip-alert"),
        ],
        queries=[
            QueryTiming("power_site_5m", "Site power | 5 min", "v_readings_5m", [3.4, 1.2, 1.1], 10000),
            QueryTiming("broken", "x", "v_readings_1h", [], 0, error="permission denied"),
        ],
        samples=[FreshnessSample(T0, 2, [10.0, 20.0]).to_row()],
        alert={"bmc_index": 500},
        throughput_per_min=[{"minute": "10:00", "readings": 24000, "servers": 500}],
        notes=["synthetic"],
    )
    md = report.to_markdown()
    assert "Overall: **FAIL**" in md
    assert "| Ingest throughput |" in md
    assert "412.5/s (247,500 readings in 600 s) | PASS |" in md
    assert "| 30-day dashboard queries |" in md and "| FAIL |" in md
    assert "not measured" in md
    assert "Site power \\| 5 min" not in md  # descriptions go in the bullet list, not the table
    assert "ERROR: permission denied" in md
    body = json.loads(report.to_json())
    assert body["passed"] is False
    assert body["queries"][0]["max_s"] == 3.4
    assert body["queries"][0]["median_s"] == 1.2
    assert body["results"][2]["passed"] is None


def test_format_value() -> None:
    assert format_value(None, "s") == "n/a"
    assert format_value(99.456, "%") == "99.46 %"
    assert format_value(1.234, "s") == "1.23 s"
    assert format_value(65.43, "s") == "65.4 s"
    assert format_value(1234.5, "/s") == "1,234.5/s"


def test_synthetic_values_are_reproducible() -> None:
    from history import synth_value

    a = synth_value("power_w", 3, "", T0, random.Random(5))
    b = synth_value("power_w", 3, "", T0, random.Random(5))
    assert a == b
    assert synth_value("fan_health", 3, "Fan 1", T0, random.Random(5)) == 0.0
