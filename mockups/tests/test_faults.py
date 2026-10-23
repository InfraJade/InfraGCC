"""Each fault changes the right resources and health rollups, logs like a real BMC, and clears cleanly."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from gcc_redfish_sim.model import CRITICAL, OK, WARNING
from gcc_redfish_sim.simulator.bmc import VirtualBmc
from gcc_redfish_sim.simulator.faults import FaultKind
from gcc_redfish_sim.simulator.fleet import FaultError, Fleet
from gcc_redfish_sim.tree import STYLES

from .conftest import PROFILE_INDEXES, T0, ClientFactory, basic, make_config

Json = dict[str, Any]
PROFILES = list(PROFILE_INDEXES)


def _paths(bmc: VirtualBmc) -> tuple[str, str, str]:
    st = STYLES[bmc.state.profile]
    return (
        f"/redfish/v1/Systems/{st.system_id}",
        f"/redfish/v1/Chassis/{st.chassis_id}",
        f"/redfish/v1/Managers/{st.manager_id}",
    )


def _log_entries(bmc: VirtualBmc) -> list[Json]:
    st = STYLES[bmc.state.profile]
    system, _, manager = _paths(bmc)
    owner = system if st.log_on_system else manager
    tree = bmc.tree()
    coll = tree[f"{owner}/LogServices/{st.log_id}/Entries"]
    return [tree[m["@odata.id"]] for m in coll["Members"]]


def _without_logs(tree: dict[str, Json]) -> dict[str, Json]:
    return {p: body for p, body in tree.items() if "/LogServices/" not in p}


def _rollup(bmc: VirtualBmc) -> str:
    system, _, _ = _paths(bmc)
    status: Json = bmc.tree()[system]["Status"]
    assert status["Health"] == status["HealthRollup"]
    return str(status["HealthRollup"])


def _fleet() -> Fleet:
    return Fleet(make_config(count=3), now=T0)


def _raise(fleet: Fleet, profile: str, kind: FaultKind) -> tuple[VirtualBmc, int, dict[str, Json], int]:
    index = PROFILE_INDEXES[profile]
    bmc = fleet.bmcs[index]
    before = {p: dict(b) for p, b in bmc.tree().items()}
    logs_before = len(_log_entries(bmc))
    assert _rollup(bmc) == OK
    fault = fleet.raise_fault(index, kind, now=T0)
    return bmc, fault.id, before, logs_before


def _clear_and_check_restored(fleet: Fleet, bmc: VirtualBmc, fault_id: int, before: dict[str, Json]) -> None:
    fleet.clear_fault(fault_id, now=T0)
    assert _without_logs(bmc.tree()) == _without_logs(before)
    assert _rollup(bmc) == OK


@pytest.mark.parametrize("profile", PROFILES)
def test_fan_slow(profile: str) -> None:
    fleet = _fleet()
    bmc, fault_id, before, logs_before = _raise(fleet, profile, FaultKind.FAN_SLOW)
    fan = next(f for f in bmc.state.fans if f.key == fleet.faults[fault_id].target)
    assert fan.health == CRITICAL
    if fan.lower_critical is not None:
        assert fan.rpm < fan.lower_critical
    else:
        assert fan.pct <= 5
    tree = bmc.tree()
    _, chassis, _ = _paths(bmc)
    st = STYLES[bmc.state.profile]
    if st.legacy_layout:
        thermal = tree[f"{chassis}/Thermal"]
        legacy = next(f for f in thermal["Fans"] if f["MemberId"] == fan.key)
        assert legacy["Status"]["Health"] == CRITICAL
        assert thermal["Redundancy"][0]["Status"]["Health"] == WARNING
    if st.new_layout:
        assert tree[f"{chassis}/ThermalSubsystem/Fans/{fan.key}"]["Status"]["Health"] == CRITICAL
        assert tree[f"{chassis}/ThermalSubsystem"]["Status"]["HealthRollup"] == CRITICAL
        sensor = tree[f"{chassis}/Sensors/{fan.key.replace('.', '')}Speed"]
        assert sensor["Reading"] < sensor["Thresholds"]["LowerCritical"]["Reading"]
    assert tree[chassis]["Status"]["HealthRollup"] == CRITICAL
    assert _rollup(bmc) == CRITICAL
    entries = _log_entries(bmc)
    assert len(entries) == logs_before + 1
    assert entries[-1]["Severity"] == CRITICAL
    _clear_and_check_restored(fleet, bmc, fault_id, before)
    assert _log_entries(bmc)[-1]["Severity"] == OK  # the deassert entry


@pytest.mark.parametrize("profile", PROFILES)
def test_psu_warning(profile: str) -> None:
    fleet = _fleet()
    bmc, fault_id, before, logs_before = _raise(fleet, profile, FaultKind.PSU_WARNING)
    psu = next(p for p in bmc.state.psus if p.key == fleet.faults[fault_id].target)
    tree = bmc.tree()
    _, chassis, _ = _paths(bmc)
    st = STYLES[bmc.state.profile]
    if st.legacy_layout:
        legacy = next(p for p in tree[f"{chassis}/Power"]["PowerSupplies"] if p["MemberId"] == psu.key)
        assert legacy["Status"]["Health"] == WARNING
    if st.new_layout:
        assert tree[f"{chassis}/PowerSubsystem/PowerSupplies/{psu.key}"]["Status"]["Health"] == WARNING
        assert tree[f"{chassis}/PowerSubsystem"]["Status"]["HealthRollup"] == WARNING
    assert _rollup(bmc) == WARNING
    assert _log_entries(bmc)[-1]["Severity"] == WARNING
    assert len(_log_entries(bmc)) == logs_before + 1
    _clear_and_check_restored(fleet, bmc, fault_id, before)


@pytest.mark.parametrize("profile", PROFILES)
def test_inlet_spike(profile: str) -> None:
    fleet = _fleet()
    bmc, fault_id, _before, _ = _raise(fleet, profile, FaultKind.INLET_SPIKE)
    inlet = next(t for t in bmc.state.temps if t.context == "Intake")
    assert inlet.reading > 36.0
    assert inlet.upper_caution is not None
    assert inlet.reading >= inlet.upper_caution
    assert inlet.health == WARNING
    tree = bmc.tree()
    _, chassis, _ = _paths(bmc)
    st = STYLES[bmc.state.profile]
    if st.legacy_layout:
        legacy = next(t for t in tree[f"{chassis}/Thermal"]["Temperatures"] if t["Name"] == inlet.name)
        assert legacy["ReadingCelsius"] > 36.0
        assert legacy["Status"]["Health"] == WARNING
    if st.new_layout:
        assert tree[f"{chassis}/Sensors/{inlet.key}"]["Reading"] > 36.0
        metrics = tree[f"{chassis}/ThermalSubsystem/ThermalMetrics"]
        assert metrics["TemperatureSummaryCelsius"]["Intake"]["Reading"] > 36.0
    assert _rollup(bmc) == WARNING
    assert _log_entries(bmc)[-1]["Severity"] == WARNING
    # The rest of the server reacts: fans spin up over the next steps.
    rpm_before = sum(f.rpm for f in bmc.state.fans)
    for n in range(1, 10):
        bmc.step(T0 + timedelta(seconds=10 * n))
    assert sum(f.rpm for f in bmc.state.fans) > rpm_before * 1.2
    assert next(t for t in bmc.state.temps if t.context == "Intake").reading > 36.0
    fleet.clear_fault(fault_id, now=T0)
    assert next(t for t in bmc.state.temps if t.context == "Intake").reading < 30.0


@pytest.mark.parametrize("profile", PROFILES)
def test_drive_wear(profile: str) -> None:
    fleet = _fleet()
    bmc, fault_id, before, _ = _raise(fleet, profile, FaultKind.DRIVE_WEAR)
    drive = next(d for d in bmc.state.drives() if d.key == fleet.faults[fault_id].target)
    ctl = bmc.state.controllers[0]
    system, _, _ = _paths(bmc)
    tree = bmc.tree()
    body = tree[f"{system}/Storage/{ctl.key}/Drives/{drive.key}"]
    assert body["PredictedMediaLifeLeftPercent"] == 5.0
    assert body["Status"]["Health"] == WARNING
    assert tree[f"{system}/Storage/{ctl.key}"]["Status"]["HealthRollup"] == WARNING
    assert _rollup(bmc) == WARNING
    assert _log_entries(bmc)[-1]["Severity"] == WARNING
    _clear_and_check_restored(fleet, bmc, fault_id, before)


@pytest.mark.parametrize("profile", PROFILES)
def test_nic_down(profile: str) -> None:
    fleet = _fleet()
    bmc, fault_id, before, _ = _raise(fleet, profile, FaultKind.NIC_DOWN)
    key = fleet.faults[fault_id].target
    system, _, _ = _paths(bmc)
    before_nic = before[f"{system}/EthernetInterfaces/{key}"]
    assert before_nic["LinkStatus"] == "LinkUp"  # an expected link
    nic = bmc.tree()[f"{system}/EthernetInterfaces/{key}"]
    assert nic["LinkStatus"] == "LinkDown"
    assert nic["SpeedMbps"] == 0
    assert _log_entries(bmc)[-1]["Severity"] == WARNING
    _clear_and_check_restored(fleet, bmc, fault_id, before)


@pytest.mark.parametrize("profile", PROFILES)
def test_critical_sel(profile: str) -> None:
    fleet = _fleet()
    bmc, fault_id, before, logs_before = _raise(fleet, profile, FaultKind.CRITICAL_SEL)
    entries = _log_entries(bmc)
    assert len(entries) == logs_before + 1
    entry = entries[-1]
    assert entry["Severity"] == CRITICAL
    assert entry["Created"].startswith("2026-10-22T09:30:00")  # site time (IST) of T0
    assert entry["Created"].endswith("+05:30")
    assert entry["Id"] == str(logs_before + 1)
    assert entry["MessageId"]
    _clear_and_check_restored(fleet, bmc, fault_id, before)
    assert len(_log_entries(bmc)) == logs_before + 1  # history stays


@pytest.mark.parametrize("profile", PROFILES)
def test_power_off(profile: str) -> None:
    fleet = _fleet()
    bmc, fault_id, _before, _ = _raise(fleet, profile, FaultKind.POWER_OFF)
    system, chassis, _ = _paths(bmc)
    assert bmc.tree()[system]["PowerState"] == "Off"
    assert bmc.tree()[chassis]["PowerState"] == "Off"
    on_power = bmc.state.power_w
    for n in range(1, 20):
        bmc.step(T0 + timedelta(seconds=10 * n))
    assert bmc.state.power_w < on_power * 0.2
    cpu = max(t.reading for t in bmc.state.temps if t.context == "CPU")
    inlet = next(t.reading for t in bmc.state.temps if t.context == "Intake")
    assert cpu < inlet + 6
    fleet.clear_fault(fault_id, now=T0)
    assert bmc.tree()[system]["PowerState"] == "On"


async def test_bmc_unresponsive(bmc_client: ClientFactory) -> None:
    fleet = _fleet()
    bmc = fleet.bmcs[1]
    client = await bmc_client(bmc)
    fault = fleet.raise_fault(1, FaultKind.BMC_UNRESPONSIVE, now=T0)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(client.get("/redfish/v1"), timeout=0.3)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(client.get("/redfish/v1/Systems", headers=basic()), timeout=0.3)
    fleet.clear_fault(fault.id, now=T0)
    resp = await client.get("/redfish/v1/Systems", headers=basic())
    assert resp.status == 200
    assert _log_entries(bmc)[-1]["MessageId"]  # BMC reset logged


def test_fault_errors_and_expiry() -> None:
    fleet = _fleet()
    with pytest.raises(FaultError) as unknown_kind:
        fleet.raise_fault(1, "meltdown")
    assert unknown_kind.value.status == 400
    with pytest.raises(FaultError) as unknown_bmc:
        fleet.raise_fault(99, FaultKind.FAN_SLOW)
    assert unknown_bmc.value.status == 404
    fault = fleet.raise_fault(1, FaultKind.FAN_SLOW, duration_s=30, now=T0)
    with pytest.raises(FaultError) as duplicate:
        fleet.raise_fault(1, FaultKind.FAN_SLOW)
    assert duplicate.value.status == 409
    fleet.step(T0 + timedelta(seconds=20))
    assert fault.id in fleet.faults
    fleet.step(T0 + timedelta(seconds=30))
    assert fault.id not in fleet.faults
    assert fleet.bmcs[1].state.system_health() == OK


def test_faults_combine_and_clear_all() -> None:
    fleet = _fleet()
    for kind in FaultKind:
        fleet.raise_fault(2, kind, now=T0)
    bmc = fleet.bmcs[2]
    assert bmc.state.power_state == "Off"
    assert bmc.summary()["responsive"] is False
    assert bmc.state.system_health() == CRITICAL
    assert fleet.clear_all(now=T0) == len(FaultKind)
    assert not bmc.faults
    assert bmc.summary()["responsive"] is True
    assert bmc.state.system_health() == OK
    assert bmc.state.power_state == "On"


def test_random_faults_are_seeded_and_expire() -> None:
    def run(seed: str) -> list[tuple[int, str]]:
        fleet = Fleet(make_config(count=20, fault_rate_per_hour=60.0, seed=seed), now=T0)
        seen: list[tuple[int, str]] = []
        for n in range(1, 100):
            fleet.step(T0 + timedelta(seconds=10 * n))
            seen.extend(
                (f.bmc, str(f.kind)) for f in fleet.faults.values() if (f.bmc, str(f.kind)) not in seen
            )
        assert all(f.source == "random" and f.expires_at is not None for f in fleet.faults.values())
        # all random faults expire within 30 minutes (the step may raise new ones)
        earlier = set(fleet.faults)
        assert earlier
        fleet.step(T0 + timedelta(seconds=10 * 100 + 1800))
        assert not earlier & set(fleet.faults)
        return seen

    first = run("a")
    assert first
    assert first == run("a")
