"""Pure unit tests: window evaluation (D14) and effective thresholds (D12)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import BmcThreshold, Server, Threshold
from app.services.alerts.windows import Sample, evaluate_window
from app.services.thresholds import Level, Limit, ThresholdResolver

NOW = datetime(2026, 10, 22, 10, 0, tzinfo=UTC)


def samples(*points: tuple[int, Level | None]) -> list[Sample]:
    return [Sample(NOW - timedelta(seconds=s), None, level) for s, level in points]


W, C, OK = Level.WARNING, Level.CRITICAL, Level.OK


def test_window_needs_two_samples_spanning_80_percent() -> None:
    assert evaluate_window(samples((0, C)), NOW, 180, 60).kind == "insufficient"
    assert evaluate_window(samples((120, C), (60, C), (0, C)), NOW, 180, 60).kind == "insufficient"
    assert evaluate_window(samples((180, C), (120, C), (60, C), (0, C)), NOW, 180, 60).kind == "bad"


def test_window_levels_and_mixes() -> None:
    v = evaluate_window(samples((180, C), (120, W), (60, C), (0, C)), NOW, 180, 60)
    assert (v.kind, v.level) == ("bad", W)
    assert evaluate_window(samples((180, OK), (120, W), (0, W)), NOW, 180, 60).kind == "mixed"
    assert evaluate_window(samples((180, W), (120, None), (0, W)), NOW, 180, 60).kind == "mixed"
    assert evaluate_window(samples((180, OK), (60, OK), (0, OK)), NOW, 180, 60).kind == "good"
    # Samples older than the window plus one interval of look-back are ignored.
    assert evaluate_window(samples((600, OK), (180, C), (90, C), (0, C)), NOW, 180, 60).kind == "bad"


def test_stale_data_is_insufficient() -> None:
    assert evaluate_window(samples((400, C), (300, C), (200, C)), NOW, 180, 60).kind == "insufficient"
    assert evaluate_window(samples((10, C)), NOW, 0, 60).kind == "bad"
    assert evaluate_window(samples((1000, C)), NOW, 0, 300).kind == "insufficient"


def test_consecutive() -> None:
    assert evaluate_window(samples((120, C), (60, C)), NOW, 0, 60, consecutive=3).kind == "insufficient"
    assert evaluate_window(samples((120, C), (60, C), (0, C)), NOW, 0, 60, consecutive=3).kind == "bad"
    assert evaluate_window(samples((120, C), (60, OK), (0, C)), NOW, 0, 60, consecutive=3).kind == "mixed"
    assert evaluate_window(samples((120, C), (60, C), (0, OK)), NOW, 0, 60, consecutive=3).kind == "good"


def test_limit_directions() -> None:
    above = Limit("above", 27, 35)
    assert [above.level(v) for v in (27, 27.1, 35.5, None)] == [OK, W, C, None]
    below = Limit("below", 10, None)
    assert [below.level(v) for v in (50, 9)] == [OK, W]
    dev = Limit("deviation_pct", 10, 20)
    assert [dev.level(v) for v in (231, 205, 180, 118, 100)] == [OK, W, C, OK, W]
    assert Limit("deviation_pct", 10, None, nominal=208).level(205) is OK
    pct = Limit("pct_of_capacity", 90, 100)
    assert [pct.level(850, 1000), pct.level(950, 1000), pct.level(1100, 1000), pct.level(950, None)] == [
        OK,
        W,
        C,
        None,
    ]


def _server() -> Server:
    return Server(id=7, site_id=2, model="PowerEdge R750", vendor="Dell", bmc_host="x")


def _t(scope: str, warning: float, **kw: object) -> Threshold:
    return Threshold(metric_code=3, scope=scope, direction="above", warning=warning, critical=None, **kw)


def test_precedence_server_site_model_global_bmc() -> None:
    bmc = [BmcThreshold(server_id=7, metric_code=3, component="CPU1", upper_warning=85.0, upper_critical=95.0,
                        lower_warning=None, lower_critical=None)]  # fmt: skip
    rows = [
        _t("global", 60),
        _t("model", 61, model="PowerEdge R750", vendor="Dell"),
        _t("model", 99, model="Other"),
        _t("site", 62, site_id=2),
        _t("site", 98, site_id=3),
        _t("server", 63, server_id=7),
    ]
    for expected, active in ((63, rows), (62, rows[:5]), (61, rows[:3]), (60, rows[:1])):
        limit = ThresholdResolver(_server(), active, bmc).effective(3, "CPU1", "upper")
        assert limit is not None and limit.warning == expected
    from_bmc = ThresholdResolver(_server(), [rows[2], rows[4]], bmc).effective(3, "CPU1", "upper")
    assert from_bmc == Limit("above", 85.0, 95.0, source="bmc")
    assert ThresholdResolver(_server(), [], bmc).effective(3, "CPU1", "lower") is None
    assert ThresholdResolver(_server(), [], bmc).effective(3, "CPU2") is None
