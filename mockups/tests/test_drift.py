"""Drift keeps every reading in sane bounds, healthy, and correlated with load and inlet temperature."""

from __future__ import annotations

import statistics
from datetime import timedelta

import pytest

from gcc_redfish_sim.model import OK
from gcc_redfish_sim.simulator.bmc import VirtualBmc
from gcc_redfish_sim.simulator.physics import site_hour

from .conftest import MODEL_INDEXES, T0, make_bmc

STEPS = 9000  # 25 h of 10 s steps


def _inlet(bmc: VirtualBmc) -> float:
    return next(t.reading for t in bmc.state.temps if t.context == "Intake")


def _check_bounds(bmc: VirtualBmc) -> None:
    s = bmc.state
    inlet = _inlet(bmc)
    assert 15.0 <= inlet <= 32.0
    for t in s.temps:
        assert t.health == OK, (t.name, t.reading)
        assert 10.0 <= t.reading <= 100.0
        if t.upper_caution is not None:
            assert t.reading < t.upper_caution
        if t.context == "Exhaust":
            assert t.reading > inlet
    for f in s.fans:
        assert f.health == OK
        assert 15.0 <= f.pct <= 100.0
        if f.lower_caution is not None:
            assert f.rpm > f.lower_caution
    assert 0.4 * 300 <= s.power_w <= s.power_capacity_w
    for p in s.psus:
        assert p.health == OK
        assert 0.0 <= p.output_w <= p.capacity_w
        assert abs(p.input_v - p.nominal_v) <= 6.5
    assert 0.0 < s.load < 1.0
    assert s.system_health() == OK


@pytest.mark.parametrize("model_key", list(MODEL_INDEXES))
def test_drift_stays_in_bounds(model_key: str) -> None:
    bmc = make_bmc(MODEL_INDEXES[model_key])
    for n in range(STEPS):
        bmc.step(T0 + timedelta(seconds=10 * n))
        _check_bounds(bmc)


def test_inlet_follows_site_time_of_day() -> None:
    bmc = make_bmc(1)
    by_hour: dict[int, list[float]] = {}
    for n in range(STEPS):
        now = T0 + timedelta(seconds=10 * n)
        bmc.step(now)
        by_hour.setdefault(int(site_hour(now)), []).append(_inlet(bmc))
    afternoon = statistics.mean(by_hour[15])
    night = statistics.mean(by_hour[3])
    assert afternoon - night > 2.0


def test_load_drives_power_fans_and_temperatures() -> None:
    def settle(load: float) -> VirtualBmc:
        bmc = make_bmc(1)
        bmc.set_load(load)
        for n in range(60):
            bmc.step(T0 + timedelta(seconds=10 * n))
        return bmc

    idle, busy = settle(0.1), settle(0.95)

    def temp(bmc: VirtualBmc, context: str) -> float:
        return max(t.reading for t in bmc.state.temps if t.context == context)

    assert busy.state.power_w > idle.state.power_w * 1.4
    assert statistics.mean(f.rpm for f in busy.state.fans) > statistics.mean(f.rpm for f in idle.state.fans)
    assert temp(busy, "CPU") > temp(idle, "CPU") + 10
    assert temp(busy, "Exhaust") > temp(idle, "Exhaust")
    assert sum(p.output_w for p in busy.state.psus) > sum(p.output_w for p in idle.state.psus)
    # PSU output tracks the draw (≈94 % efficiency)
    assert sum(p.output_w for p in busy.state.psus) == pytest.approx(busy.state.power_w * 0.94, rel=0.05)


def test_same_seed_same_readings() -> None:
    a, b = make_bmc(4, seed="x"), make_bmc(4, seed="x")
    for n in range(50):
        a.step(T0 + timedelta(seconds=10 * n))
        b.step(T0 + timedelta(seconds=10 * n))
    assert a.tree() == b.tree()


def test_render_is_cached_until_state_changes() -> None:
    bmc = make_bmc(1)
    first = bmc.tree()
    assert bmc.tree() is first
    bmc.step(T0 + timedelta(seconds=10))
    assert bmc.tree() is not first
