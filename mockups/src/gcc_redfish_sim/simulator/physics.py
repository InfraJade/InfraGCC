"""Realistic drift of one server's sensors.

The model is deliberately small but correlated, one step every ~10 s:

  inlet    = nominal + rack offset + diurnal swing (peak mid-afternoon site time) + noise
  load     = mean-reverting random walk around a per-server target, busier in business hours
  power    = nominal * (0.55 + load)                (≈ nominal at 45 % load; standby when the host is off)
  fans     = nominal % + load term + inlet term     (hot inlet or high load spin the fans up)
  CPU/DIMM = nominal + inlet delta + load term
  exhaust  = inlet + nominal rise * power ratio * sqrt(nominal fan % / fan %)
  PSUs     = share the draw (≈94 % efficiency); input voltage wanders around nominal

Temperatures and power approach their targets with first-order lag (thermal inertia). The physical values
live in `Physics`, separate from the rendered `ServerState`, so a fault overlay never leaks into them and
clearing a fault restores the state exactly.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from gcc_redfish_sim.model import CRITICAL, OK, WARNING, Fan, ServerState, Temp

# Both seeded sites (PNQ1 Pune, HYD1 Hyderabad) run on India Standard Time.
SITE_TZ = timezone(timedelta(hours=5, minutes=30), "IST")

LOAD_MIN, LOAD_MAX = 0.05, 0.98
FAN_PCT_MIN, FAN_PCT_MAX = 20.0, 100.0
STANDBY_POWER_RATIO = 0.04
PSU_EFFICIENCY = 0.94
INLET_SWING_C = 1.5
VOLTAGE_SWING_V = 6.0


@dataclass(frozen=True)
class Effects:
    """What active faults do to the physics (as opposed to what they overlay on the rendered state)."""

    host_off: bool = False
    inlet_override_c: float | None = None
    fan_boost_pct: float = 0.0


@dataclass
class Physics:
    inlet_key: str
    inlet_nominal: float
    inlet_offset: float
    load_target: float
    nominal_power_w: float
    nominal_fan_pct: float
    temps: dict[str, float]
    fan_pct: float
    fan_rpm: list[float]
    power_w: float
    psu_out_w: list[float]
    psu_in_v: list[float]
    pinned_load: float | None = None
    _jitter: dict[str, float] = field(default_factory=dict)

    @classmethod
    def initial(cls, state: ServerState, index: int, rng: random.Random) -> Physics:
        inlet = next(t for t in state.temps if t.context == "Intake")
        offset = ((index % 12) - 6) * 0.25  # rack position: lower slots run a little cooler
        nominal_fan = state.fans[0].nominal_pct
        phys = cls(
            inlet_key=inlet.key,
            inlet_nominal=inlet.nominal,
            inlet_offset=offset,
            load_target=0.3 + 0.35 * rng.random(),
            nominal_power_w=state.power_w,
            nominal_fan_pct=nominal_fan,
            temps={t.key: t.nominal + (offset if t.context == "Intake" else 0.0) for t in state.temps},
            fan_pct=nominal_fan,
            fan_rpm=[f.max_rpm * nominal_fan / 100.0 for f in state.fans],
            power_w=state.power_w,
            psu_out_w=[state.power_w * PSU_EFFICIENCY / len(state.psus) for _ in state.psus],
            psu_in_v=[p.nominal_v for p in state.psus],
        )
        phys._jitter = {t.key: rng.uniform(-1.5, 1.5) for t in state.temps if t.context in ("CPU", "Memory")}
        state.load = phys.load_target
        return phys


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def site_hour(now: datetime) -> float:
    local = now.astimezone(SITE_TZ)
    return local.hour + local.minute / 60.0 + local.second / 3600.0


def _business(hour: float) -> float:
    return max(0.0, math.sin(math.pi * (hour - 8.0) / 12.0)) if 8.0 < hour < 20.0 else 0.0


def step(phys: Physics, state: ServerState, now: datetime, rng: random.Random, fx: Effects) -> None:
    """Advance the physics one step and write the readings into `state` (health is set separately)."""
    hour = site_hour(now)

    # Workload
    if phys.pinned_load is not None:
        state.load = phys.pinned_load
    else:
        target = phys.load_target + 0.15 * _business(hour)
        state.load = _clamp(
            state.load + 0.2 * (target - state.load) + rng.gauss(0.0, 0.03), LOAD_MIN, LOAD_MAX
        )
    load = 0.0 if fx.host_off else state.load

    # Inlet (room air) never depends on faults; the inlet spike is an overlay plus an effect on the rest.
    inlet_target = (
        phys.inlet_nominal + phys.inlet_offset + INLET_SWING_C * math.sin(2 * math.pi * (hour - 9.0) / 24.0)
    )
    inlet = phys.temps[phys.inlet_key]
    inlet += 0.5 * (inlet_target - inlet) + rng.gauss(0.0, 0.08)
    inlet = _clamp(inlet, phys.inlet_nominal - 6.0, phys.inlet_nominal + 6.0)
    phys.temps[phys.inlet_key] = inlet
    eff_inlet = fx.inlet_override_c if fx.inlet_override_c is not None else inlet
    inlet_delta = eff_inlet - phys.inlet_nominal

    # Power
    nominal = phys.nominal_power_w
    power_target = nominal * STANDBY_POWER_RATIO if fx.host_off else nominal * (0.55 + load)
    power_target += rng.gauss(0.0, 0.01 * nominal)
    phys.power_w = _clamp(
        phys.power_w + 0.6 * (power_target - phys.power_w),
        nominal * STANDBY_POWER_RATIO * 0.5,
        state.power_capacity_w * 0.9,
    )
    power_ratio = phys.power_w / nominal

    # Fans
    if fx.host_off:
        fan_target = FAN_PCT_MIN
    else:
        fan_target = phys.nominal_fan_pct + (load - 0.45) * 30.0 + max(0.0, eff_inlet - 25.0) * 3.0
    fan_target += fx.fan_boost_pct
    phys.fan_pct = _clamp(phys.fan_pct + 0.5 * (fan_target - phys.fan_pct), FAN_PCT_MIN, FAN_PCT_MAX)
    for i, fan in enumerate(state.fans):
        pct = phys.fan_pct * (1.0 + 0.015 * ((i % 3) - 1)) + rng.gauss(0.0, 0.4)
        phys.fan_rpm[i] = fan.max_rpm * _clamp(pct, FAN_PCT_MIN * 0.9, FAN_PCT_MAX) / 100.0

    # Component temperatures
    airflow = math.sqrt(phys.nominal_fan_pct / phys.fan_pct)
    for t in state.temps:
        if t.key == phys.inlet_key:
            continue
        jitter = phys._jitter.get(t.key, 0.0)
        if t.context == "Exhaust":
            rise = (t.nominal - phys.inlet_nominal) * power_ratio * airflow
            target = eff_inlet + (1.5 if fx.host_off else rise)
        elif t.context == "CPU":
            gain = 45.0 if t.nominal >= 50.0 else 35.0
            target = (
                eff_inlet + 3.0 if fx.host_off else t.nominal + inlet_delta + (load - 0.45) * gain + jitter
            )
        elif t.context == "Memory":
            target = eff_inlet + 2.0 if fx.host_off else t.nominal + 0.8 * inlet_delta + (load - 0.45) * 12.0
        else:
            target = t.nominal + inlet_delta
        current = phys.temps[t.key]
        phys.temps[t.key] = current + 0.35 * (target - current) + rng.gauss(0.0, 0.15)

    # Power supplies
    n = len(state.psus)
    for i, psu in enumerate(state.psus):
        share = phys.power_w * PSU_EFFICIENCY / n
        phys.psu_out_w[i] = max(0.0, share * (1.0 + 0.02 * (1 if i % 2 else -1)) + rng.gauss(0.0, 1.0))
        v = phys.psu_in_v[i]
        v += 0.3 * (psu.nominal_v - v) + rng.gauss(0.0, 0.5)
        phys.psu_in_v[i] = _clamp(v, psu.nominal_v - VOLTAGE_SWING_V, psu.nominal_v + VOLTAGE_SWING_V)


def write_readings(phys: Physics, state: ServerState) -> None:
    for t in state.temps:
        t.reading = round(phys.temps[t.key], 2)
    for fan, rpm in zip(state.fans, phys.fan_rpm, strict=True):
        fan.rpm = rpm
    state.power_w = phys.power_w
    for psu, out_w, in_v in zip(state.psus, phys.psu_out_w, phys.psu_in_v, strict=True):
        psu.output_w = out_w
        psu.input_v = in_v


def temp_health(t: Temp) -> str:
    if t.upper_critical is not None and t.reading >= t.upper_critical:
        return CRITICAL
    if t.upper_caution is not None and t.reading >= t.upper_caution:
        return WARNING
    return OK


def fan_health(f: Fan) -> str:
    if f.lower_critical is not None and f.rpm <= f.lower_critical:
        return CRITICAL
    if f.lower_caution is not None and f.rpm <= f.lower_caution:
        return WARNING
    return OK
