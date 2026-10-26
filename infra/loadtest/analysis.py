"""Pure load-test logic: statistics, the design targets, pass/fail evaluation and report rendering.

Nothing here touches the network or the database, so it is unit-tested directly (tests/test_analysis.py).
The targets come from docs/DESIGN.md: "Proposed success measures", "Sizing and performance" and "Load test".
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

Comparison = Literal["<", "<=", ">=", ">"]

# DESIGN "Sizing and performance": about 20,000 readings a minute (330 a second) at 500 servers.
DESIGN_READINGS_PER_S_AT_500 = 330.0
# The ingest rate must reach this share of the design estimate (the estimate is "about").
READINGS_RATE_TOLERANCE = 0.9
REPORTING_SHARE_MIN = 99.0  # % of onboarded servers reporting every 5 minutes
FRESH_AGE_S = 120.0  # live readings under 2 minutes old
FRESH_SHARE_MIN = 99.0  # % of servers whose newest reading is younger than FRESH_AGE_S
LAG_P95_MAX_S = 120.0
LAG_GROWTH_MAX_S = 15.0  # "no growing lag": last third of the window vs the first third
ALERT_DELAY_MAX_S = 120.0  # alert raised within 2 minutes of the rule's condition being met
DASHBOARD_QUERY_MAX_S = 3.0  # 30-day views load in under 3 seconds


def percentile(values: Iterable[float], pct: float) -> float:
    """Percentile with linear interpolation between closest ranks (NumPy's default method)."""
    data = sorted(values)
    if not data:
        raise ValueError("percentile of an empty sequence")
    if not 0.0 <= pct <= 100.0:
        raise ValueError("pct must be between 0 and 100")
    if len(data) == 1:
        return data[0]
    rank = (len(data) - 1) * pct / 100.0
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return data[lo]
    return data[lo] + (data[hi] - data[lo]) * (rank - lo)


def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("mean of an empty sequence")
    return sum(values) / len(values)


def share_pct(part: int, whole: int) -> float:
    """`part` as a percentage of `whole`; an empty fleet counts as 0 % (nothing is reporting)."""
    return 100.0 * part / whole if whole > 0 else 0.0


def lag_growth(series: Sequence[float]) -> float:
    """Mean of the last third minus mean of the first third (positive = lag is growing)."""
    if len(series) < 3:
        return 0.0
    third = len(series) // 3
    return mean(series[-third:]) - mean(series[:third])


def expected_readings_per_s(servers: int) -> float:
    """The design's readings-per-second estimate scaled to the fleet size."""
    return DESIGN_READINGS_PER_S_AT_500 * servers / 500.0


@dataclass(frozen=True)
class Target:
    key: str
    name: str
    design: str  # the design-doc wording the target comes from
    comparison: Comparison
    threshold: float
    unit: str

    def check(self, value: float) -> bool:
        match self.comparison:
            case "<":
                return value < self.threshold
            case "<=":
                return value <= self.threshold
            case ">=":
                return value >= self.threshold
            case ">":
                return value > self.threshold

    def describe(self) -> str:
        return f"{self.comparison} {format_value(self.threshold, self.unit)}"


def standard_targets(servers: int) -> dict[str, Target]:
    rate = expected_readings_per_s(servers) * READINGS_RATE_TOLERANCE
    targets = [
        Target(
            "readings_per_s",
            "Ingest throughput",
            f"About 330 readings/s at 500 servers (Sizing); {READINGS_RATE_TOLERANCE:.0%} of that, scaled to "
            f"{servers} servers",
            ">=",
            round(rate, 1),
            "/s",
        ),
        Target(
            "servers_reporting",
            "Servers reporting",
            "At least 99% of onboarded servers report every 5 minutes (worst 5-minute bucket)",
            ">=",
            REPORTING_SHARE_MIN,
            "%",
        ),
        Target(
            "live_freshness",
            "Live freshness",
            "Live readings are under 2 minutes old (worst sample: share of servers with data < 120 s old)",
            ">=",
            FRESH_SHARE_MIN,
            "%",
        ),
        Target(
            "ingest_lag_p95",
            "Ingest lag p95",
            "Ingest keeps up (worst sample of p95 of now - newest reading per server)",
            "<",
            LAG_P95_MAX_S,
            "s",
        ),
        Target(
            "ingest_lag_growth",
            "Lag growth",
            "No growing lag (mean p95 lag, last third of the window minus first third)",
            "<=",
            LAG_GROWTH_MAX_S,
            "s",
        ),
        Target(
            "alert_delay",
            "Alert delay",
            "Alert raised within 2 minutes of a reading crossing its threshold, measured after the "
            "rule's hold duration",
            "<",
            ALERT_DELAY_MAX_S,
            "s",
        ),
        Target(
            "dashboard_30d",
            "30-day dashboard queries",
            "30-day views load in under 3 seconds (slowest run of the slowest query)",
            "<",
            DASHBOARD_QUERY_MAX_S,
            "s",
        ),
    ]
    return {t.key: t for t in targets}


@dataclass
class Result:
    key: str
    name: str
    design: str
    target: str
    value: float | None  # None = not measured
    unit: str
    passed: bool | None  # None = not measured
    detail: str = ""


def evaluate(target: Target, value: float | None, detail: str = "") -> Result:
    passed = None if value is None else target.check(value)
    return Result(
        key=target.key,
        name=target.name,
        design=target.design,
        target=target.describe(),
        value=value,
        unit=target.unit,
        passed=passed,
        detail=detail,
    )


def not_measured(target: Target, reason: str) -> Result:
    return evaluate(target, None, reason)


def overall(results: Sequence[Result]) -> bool | None:
    """True when every measured target passed; None when nothing was measured."""
    measured = [r for r in results if r.passed is not None]
    if not measured:
        return None
    return all(r.passed for r in measured)


def format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "%":
        return f"{value:.2f} %"
    if unit == "s":
        return f"{value:.2f} s" if abs(value) < 10 else f"{value:.1f} s"
    if unit == "/s":
        return f"{value:,.1f}/s"
    return f"{value:g} {unit}".strip()


def verdict(passed: bool | None) -> str:
    return {True: "PASS", False: "FAIL", None: "not measured"}[passed]


@dataclass
class QueryTiming:
    name: str
    description: str
    view: str
    runs_s: list[float]
    rows: int
    error: str | None = None

    @property
    def first_s(self) -> float | None:
        return self.runs_s[0] if self.runs_s else None

    @property
    def max_s(self) -> float | None:
        return max(self.runs_s) if self.runs_s else None

    @property
    def median_s(self) -> float | None:
        return percentile(self.runs_s, 50) if self.runs_s else None


@dataclass
class Report:
    started_at: datetime
    finished_at: datetime
    parameters: dict[str, Any]
    environment: dict[str, Any]
    results: list[Result]
    queries: list[QueryTiming] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)
    alert: dict[str, Any] = field(default_factory=dict)
    throughput_per_min: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool | None:
        return overall(self.results)

    def to_json(self) -> str:
        body: dict[str, Any] = {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "passed": self.passed,
            "parameters": self.parameters,
            "environment": self.environment,
            "results": [asdict(r) for r in self.results],
            "queries": [
                {
                    **asdict(q),
                    "first_s": q.first_s,
                    "median_s": q.median_s,
                    "max_s": q.max_s,
                }
                for q in self.queries
            ],
            "alert": self.alert,
            "throughput_per_min": self.throughput_per_min,
            "samples": self.samples,
            "notes": self.notes,
        }
        return json.dumps(body, indent=2, default=str)

    def to_markdown(self) -> str:
        lines = [
            "# Jade GCC load test report",
            "",
            f"- Started: {self.started_at.isoformat(timespec='seconds')}",
            f"- Finished: {self.finished_at.isoformat(timespec='seconds')}",
            f"- Overall: **{verdict(self.passed)}**",
        ]
        lines += [f"- {k.replace('_', ' ').capitalize()}: {v}" for k, v in self.parameters.items()]
        if self.environment:
            lines += ["", "## Environment", ""]
            lines += [f"- {k.replace('_', ' ').capitalize()}: {v}" for k, v in self.environment.items()]
        lines += [
            "",
            "## Targets",
            "",
            "| Target | Design | Required | Measured | Result |",
            "|---|---|---|---|---|",
        ]
        for r in self.results:
            measured = format_value(r.value, r.unit)
            if r.detail:
                measured += f" ({r.detail})"
            lines.append(
                f"| {r.name} | {_cell(r.design)} | {r.target} | {_cell(measured)} | {verdict(r.passed)} |"
            )
        if self.queries:
            lines += [
                "",
                "## 30-day dashboard queries (as gcc_superset_ro)",
                "",
                "| Query | View | Rows | First | Median | Max | Result |",
                "|---|---|---|---|---|---|---|",
            ]
            for q in self.queries:
                if q.error:
                    lines.append(f"| {q.name} | {q.view} | - | - | - | - | ERROR: {_cell(q.error)} |")
                    continue
                ok = q.max_s is not None and q.max_s < DASHBOARD_QUERY_MAX_S
                lines.append(
                    f"| {q.name} | {q.view} | {q.rows} | {format_value(q.first_s, 's')} | "
                    f"{format_value(q.median_s, 's')} | {format_value(q.max_s, 's')} | {verdict(ok)} |"
                )
            lines += ["", *[f"- `{q.name}`: {q.description}" for q in self.queries]]
        if self.alert:
            lines += ["", "## Alert delay", ""]
            lines += [f"- {k.replace('_', ' ').capitalize()}: {v}" for k, v in self.alert.items()]
        if self.throughput_per_min:
            lines += ["", "## Readings per minute", "", "| Minute | Readings | Servers |", "|---|---|---|"]
            lines += [
                f"| {row['minute']} | {row['readings']} | {row['servers']} |"
                for row in self.throughput_per_min
            ]
        if self.samples:
            lines += [
                "",
                "## Freshness samples",
                "",
                "| Time | Servers | Fresh < 120 s | Lag p50 | Lag p95 | Lag max |",
                "|---|---|---|---|---|---|",
            ]
            for s in self.samples:
                lines.append(
                    f"| {s['time']} | {s['servers']} | {format_value(s['fresh_pct'], '%')} | "
                    f"{format_value(s['lag_p50_s'], 's')} | {format_value(s['lag_p95_s'], 's')} | "
                    f"{format_value(s['lag_max_s'], 's')} |"
                )
        if self.notes:
            lines += ["", "## Notes", "", *[f"- {n}" for n in self.notes]]
        return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


@dataclass(frozen=True)
class FreshnessSample:
    time: datetime
    servers: int
    ages_s: list[float]  # newest reading age per server; math.inf when a server has none

    @property
    def fresh_pct(self) -> float:
        return share_pct(sum(1 for a in self.ages_s if a < FRESH_AGE_S), self.servers)

    def lag(self, pct: float) -> float | None:
        return percentile(self.ages_s, pct) if self.ages_s else None

    def to_row(self) -> dict[str, Any]:
        finite = [a for a in self.ages_s if math.isfinite(a)]
        return {
            "time": self.time.isoformat(timespec="seconds"),
            "servers": self.servers,
            "fresh_pct": round(self.fresh_pct, 2),
            "never_reported": self.servers - len(finite),
            "lag_p50_s": _round(self.lag(50)),
            "lag_p95_s": _round(self.lag(95)),
            "lag_max_s": _round(max(self.ages_s) if self.ages_s else None),
        }


def _round(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return value
    return round(value, 2)


@dataclass(frozen=True)
class AlertTiming:
    """Timestamps for one injected fault (all from the database clock).

    `delay_s` is measured from the moment the rule could first fire: the first reading past the threshold
    plus the rule's hold duration (D14: a value must stay bad for the duration). The poll interval
    (time from injection to the first bad reading) and the hold duration are reported but not counted.
    """

    injected_at: datetime
    first_bad_at: datetime | None
    rule_duration_s: float
    alert_seen_at: datetime | None
    alert_opened_at: datetime | None

    @property
    def detection_s(self) -> float | None:
        if self.first_bad_at is None:
            return None
        return (self.first_bad_at - self.injected_at).total_seconds()

    @property
    def end_to_end_s(self) -> float | None:
        if self.alert_seen_at is None:
            return None
        return (self.alert_seen_at - self.injected_at).total_seconds()

    @property
    def delay_s(self) -> float | None:
        if self.alert_seen_at is None or self.first_bad_at is None:
            return None
        eligible = self.first_bad_at.timestamp() + self.rule_duration_s
        return max(0.0, self.alert_seen_at.timestamp() - eligible)


def reporting_share(bucket_servers: Sequence[int], onboarded: int) -> float | None:
    """Worst share of onboarded servers seen in any bucket."""
    if not bucket_servers:
        return None
    return min(share_pct(n, onboarded) for n in bucket_servers)
