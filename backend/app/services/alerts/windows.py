"""Window evaluation (DECISIONS.md D14): stateless flap protection.

For a rule with duration *d* the samples of one series (server, metric, part) over the last *d* — plus one
poll interval of look-back, so the sample that was in effect when the window started counts too — decide:

- **bad** when every sample is bad (the verdict's level is the lowest level they all reach, so a window
  that is all Critical escalates while a Warning/Critical mix stays Warning);
- **good** when every sample is OK;
- **mixed** otherwise, or when any sample cannot be judged: the alert keeps its current state.

A window only counts with ≥ 2 samples spanning ≥ 80 % of *d* and a latest sample that is fresh (no older than
two poll intervals plus a minute); otherwise it is **insufficient** and nothing changes. Rules with *d* = 0
judge the latest fresh sample alone; `consecutive: n` rules need the latest *n* samples all bad to open and
resolve on the first good one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.services.thresholds import Level

VerdictKind = Literal["bad", "good", "mixed", "insufficient"]
MIN_SPAN_FRACTION = 0.8


@dataclass(frozen=True)
class Sample:
    time: datetime
    value: float | None
    level: Level | None  # None: cannot be judged


@dataclass(frozen=True)
class Verdict:
    kind: VerdictKind
    level: Level | None = None
    latest: Sample | None = None


def freshness_limit(interval_s: int) -> timedelta:
    return timedelta(seconds=2 * interval_s + 60)


def lookback(duration_s: int, interval_s: int, consecutive: int = 0) -> timedelta:
    """How far back samples are needed for a rule."""
    needed = max(duration_s + interval_s, 2 * interval_s + 60, consecutive * interval_s + 60)
    return timedelta(seconds=needed)


def _judge(samples: Sequence[Sample]) -> Verdict:
    latest = samples[-1]
    levels = [s.level for s in samples]
    if any(level is None for level in levels):
        return Verdict("mixed", latest=latest)
    if all(level is Level.OK for level in levels):
        return Verdict("good", latest=latest)
    if all(level is not None and level >= Level.WARNING for level in levels):
        lowest = min(level for level in levels if level is not None)
        return Verdict("bad", Level(lowest), latest)
    return Verdict("mixed", latest=latest)


def evaluate_window(
    samples: Sequence[Sample], now: datetime, duration_s: int, interval_s: int, consecutive: int = 0
) -> Verdict:
    """`samples` may be in any order and may include older samples; only the relevant ones are used."""
    ordered = sorted((s for s in samples if s.time <= now), key=lambda s: s.time)
    if not ordered:
        return Verdict("insufficient")
    latest = ordered[-1]
    if now - latest.time > freshness_limit(interval_s):
        return Verdict("insufficient", latest=latest)

    if consecutive > 0:
        if latest.level is Level.OK:
            return Verdict("good", latest=latest)
        tail = ordered[-consecutive:]
        if len(tail) < consecutive:
            return Verdict("insufficient", latest=latest)
        verdict = _judge(tail)
        return verdict if verdict.kind == "bad" else Verdict("mixed", latest=latest)

    if duration_s <= 0:
        return _judge([latest])

    start = now - timedelta(seconds=duration_s + interval_s)
    window = [s for s in ordered if s.time >= start]
    if len(window) < 2:
        return Verdict("insufficient", latest=latest)
    span = (window[-1].time - window[0].time).total_seconds()
    if span < MIN_SPAN_FRACTION * duration_s:
        return Verdict("insufficient", latest=latest)
    return _judge(window)
