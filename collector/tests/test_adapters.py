"""Adapters replayed against the vendor mockup trees (mockups/trees/*) through an httpx transport.

Each vendor test asserts every metric code the vendor exposes, the D13 component names, limits, events,
identity, components and firmware. The trees have no power cap configured, so ``power_limit_w`` is
checked with a patched resource; HPE reports fans in percent (``fan_pct``), the others in RPM.
"""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any

import httpx
import pytest
from conftest import DELL, HPE, LENOVO, TreeBmc, creds, tree_poller

from gcc_collector.adapters import ALL_KINDS, PollKind
from gcc_collector.adapters.dell import DellAdapter
from gcc_collector.adapters.generic import GenericAdapter
from gcc_collector.adapters.hpe import HpeAdapter
from gcc_collector.adapters.lenovo import LenovoAdapter
from gcc_collector.adapters.registry import detect_adapter
from gcc_collector.poller import PollResult, ServerPoller
from gcc_collector.redfish.client import RedfishClient
from gcc_collector.schema import READING_METRICS, ServerConfig, ServerPayload

SENSORS: frozenset[PollKind] = frozenset({"sensors"})
HEALTH: frozenset[PollKind] = frozenset({"sensors", "health"})

COMMON_CODES = set(READING_METRICS) - {"fan_rpm", "fan_pct", "power_limit_w"}


async def poll_all(bmc: TreeBmc) -> ServerPayload:
    poller = tree_poller(bmc)
    result = await poller.poll(ALL_KINDS)
    await poller.close()
    assert result.ok, result.error
    return result.payload


def by_metric(payload: ServerPayload) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in payload.readings or []:
        out.setdefault(r.metric, {})[r.component] = (r.value, r.status)
    return out


def assert_no_duplicates(payload: ServerPayload) -> None:
    keys = Counter((r.metric, r.component) for r in payload.readings or [])
    assert [k for k, n in keys.items() if n > 1] == []


def components(payload: ServerPayload, kind: str) -> list[str]:
    return [c.name for c in payload.components or [] if c.type == kind]


# ------------------------------------------------------------------------------------------------ Dell


async def test_dell_all_parameters() -> None:
    bmc = TreeBmc(DELL)
    payload = await poll_all(bmc)
    m = by_metric(payload)
    assert set(m) == COMMON_CODES | {"fan_rpm"}
    assert_no_duplicates(payload)

    assert m["inlet_temp_c"] == {"": (23.0, "OK")}
    assert m["exhaust_temp_c"] == {"": (38.0, "OK")}
    assert set(m["cpu_temp_c"]) == {"CPU1", "CPU2"}
    assert set(m["dimm_temp_c"]) == {"DIMM A1", "DIMM B1"}
    assert set(m["fan_rpm"]) == {f"Fan {n}" for n in range(1, 7)}
    assert set(m["fan_health"]) == set(m["fan_rpm"])
    assert m["fan_redundancy"] == {"": (0, "OK")}
    assert m["power_w"] == {"": (320.0, "OK")}
    assert m["power_capacity_w"] == {"": (1400.0, None)}
    assert m["psu_input_v"] == {"PSU 1": (231.0, "OK"), "PSU 2": (231.0, "OK")}
    assert set(m["psu_health"]) == {"PSU 1", "PSU 2"}
    assert m["psu_redundancy"] == {"": (0, "OK")}
    assert m["power_state"] == {"": (1, "On")}
    assert m["system_health"] == {"": (0, "OK")}
    assert set(m["cpu_health"]) == {"CPU1", "CPU2"}
    assert set(m["memory_health"]) == {f"DIMM {b}{n}" for b in "AB" for n in range(1, 9)}
    assert set(m["drive_health"]) == {f"Disk {n}" for n in range(4)}
    assert set(m["drive_life_pct"]) == set(m["drive_health"])
    assert m["storage_health"] == {"RAID.SL.3-1": (0, "OK")}
    assert m["volume_health"] == {"Volume 0": (0, "OK")}
    assert m["nic_link"] == {
        "NIC 1": (1, "Up"),
        "NIC 2": (1, "Up"),
        "NIC 3": (0, "Down"),
        "NIC 4": (0, "Down"),
    }
    assert m["bmc_health"] == {"": (0, "OK")}
    assert m["bmc_reachable"] == {"": (1, "Reachable")}

    limits = {(lim.metric, lim.component): lim for lim in payload.bmc_limits or []}
    assert limits[("cpu_temp_c", "CPU1")].upper_warning == 93.0
    assert limits[("cpu_temp_c", "CPU1")].upper_critical == 98.0
    assert limits[("fan_rpm", "Fan 1")].lower_warning == 960.0
    assert limits[("fan_rpm", "Fan 1")].lower_critical == 600.0

    assert [e.entry_id for e in payload.events or []] == ["Sel/1", "Sel/2"]  # Lclog is ignored

    identity = payload.identity
    assert identity is not None
    assert identity.vendor == "Dell"
    assert identity.model == "PowerEdge R750"
    assert identity.bmc_model == "iDRAC9"
    assert identity.bmc_firmware == "7.10.70.00"
    assert identity.serial == identity.sku  # the Service Tag
    assert identity.system_path == "/redfish/v1/Systems/System.Embedded.1"
    assert identity.bmc_mac and identity.bmc_mac.startswith("D0:8E:79")
    assert len(identity.host_ips) == 1

    assert components(payload, "cpu") == ["CPU1", "CPU2"]
    assert components(payload, "dimm")[:2] == ["DIMM A1", "DIMM A2"]
    assert components(payload, "fan") == [f"Fan {n}" for n in range(1, 7)]
    assert components(payload, "psu") == ["PSU 1", "PSU 2"]
    assert components(payload, "drive") == [f"Disk {n}" for n in range(4)]
    assert components(payload, "volume") == ["Volume 0"]
    assert components(payload, "storage_controller") == ["RAID.SL.3-1"]
    assert components(payload, "nic") == ["NIC 1", "NIC 2", "NIC 3", "NIC 4"]
    nics = {c.name: c for c in payload.components or [] if c.type == "nic"}
    assert nics["NIC 1"].link_up is True and nics["NIC 3"].link_up is False
    drive = next(c for c in payload.components or [] if c.name == "Disk 0")
    assert drive.capacity == 960.2 and drive.capacity_unit == "GB" and drive.extra["media"] == "SSD"

    fw = {f.component_key: f for f in payload.firmware or []}
    assert fw["BIOS"].version == "1.15.2"  # Installed-, not the Previous- 1.13.2 image
    assert fw["BMC"].version == "7.10.70.00"
    assert {"CPLD", "PSU", "NIC", "RAID", "DRIVE:MZ7L3960HCJR0D3"} <= set(fw)
    assert len([f for f in payload.firmware or [] if f.component_key == "BIOS"]) == 1


async def test_dell_both_layouts_never_reads_legacy() -> None:
    bmc = TreeBmc(DELL)
    poller = tree_poller(bmc)
    await poller.poll(ALL_KINDS)
    result = await poller.poll(HEALTH)
    assert_no_duplicates(result.payload)
    legacy = bmc.get_count(lambda p: p.endswith(("/Thermal", "/Power")))
    assert legacy == 0
    await poller.close()


async def test_dell_falls_back_to_legacy_when_new_layout_missing() -> None:
    bmc = TreeBmc(DELL)
    path = "/redfish/v1/Chassis/System.Embedded.1"
    chassis = copy.deepcopy(bmc.load(path))
    assert chassis is not None
    for key in ("ThermalSubsystem", "PowerSubsystem", "EnvironmentMetrics", "Sensors"):
        chassis.pop(key)
    bmc.overrides[path] = chassis
    payload = await poll_all(bmc)
    m = by_metric(payload)
    assert set(m) == COMMON_CODES | {"fan_rpm"}
    assert set(m["fan_rpm"]) == {f"Fan {n}" for n in range(1, 7)}
    assert set(m["psu_input_v"]) == {"PSU 1", "PSU 2"}
    assert m["power_w"][""][0] == 320.0
    assert_no_duplicates(payload)


async def test_dell_sensor_poll_is_cheap() -> None:
    bmc = TreeBmc(DELL)
    poller = tree_poller(bmc)
    await poller.poll(ALL_KINDS)
    before = len(bmc.requests)
    result = await poller.poll(SENSORS)
    # System, Manager, and the Sensors collection in one $expand call.
    assert len(bmc.requests) - before == 3
    assert {r.metric for r in result.payload.readings or []} == {
        "power_state",
        "system_health",
        "bmc_health",
        "inlet_temp_c",
        "exhaust_temp_c",
        "cpu_temp_c",
        "dimm_temp_c",
        "fan_rpm",
        "power_w",
        "psu_input_v",
        "bmc_reachable",
    }
    assert result.payload.identity is None and result.payload.events is None
    await poller.close()


async def test_power_limit_from_environment_metrics() -> None:
    bmc = TreeBmc(DELL)
    path = "/redfish/v1/Chassis/System.Embedded.1/EnvironmentMetrics"
    env = copy.deepcopy(bmc.load(path))
    assert env is not None
    env["PowerLimitWatts"] = {"SetPoint": 1100, "ControlMode": "Automatic"}
    bmc.overrides[path] = env
    m = by_metric(await poll_all(bmc))
    assert m["power_limit_w"] == {"": (1100.0, None)}


# ------------------------------------------------------------------------------------------------- HPE


async def test_hpe_legacy_layout_and_percent_fans() -> None:
    bmc = TreeBmc(HPE)
    payload = await poll_all(bmc)
    m = by_metric(payload)
    assert set(m) == COMMON_CODES | {"fan_pct"}
    assert_no_duplicates(payload)
    assert bmc.get_count(lambda p: p.endswith("/Chassis/1/Thermal")) >= 1
    assert bmc.get_count(lambda p: "ThermalSubsystem" in p or "Sensors" in p) == 0
    assert not any("expand" in str(r.url) for r in bmc.requests)

    assert m["inlet_temp_c"] == {"": (22.0, "OK")}
    assert m["exhaust_temp_c"] == {"": (37.0, "OK")}
    assert set(m["cpu_temp_c"]) == {"CPU1", "CPU2"}
    assert set(m["dimm_temp_c"]) == {"P1 DIMM 1-6", "P2 DIMM 1-6"}
    assert m["fan_pct"]["Fan 1"] == (32.0, "OK")
    assert set(m["fan_pct"]) == {f"Fan {n}" for n in range(1, 7)}
    assert m["power_w"] == {"": (280.0, None)}
    assert m["power_capacity_w"] == {"": (800.0, None)}
    assert m["psu_input_v"] == {"PSU 1": (230.0, "OK"), "PSU 2": (230.0, "OK")}  # from Oem.Hpe.BayNumber
    assert m["fan_redundancy"] == {"": (0, "OK")}
    assert m["psu_redundancy"] == {"": (0, "OK")}
    assert set(m["memory_health"]) == {f"PROC {p} DIMM {s}" for p in (1, 2) for s in (1, 3, 5, 8, 10, 12)}
    assert m["storage_health"] == {"DE00A000": (0, "OK")}
    assert set(m["drive_health"]) == {f"Disk {n}" for n in range(4)}
    assert m["volume_health"] == {"Volume 1": (0, "OK")}
    assert m["nic_link"] == {
        "NIC 1": (1, "Up"),
        "NIC 2": (1, "Up"),
        "NIC 3": (0, "Down"),
        "NIC 4": (0, "Down"),
    }

    limits = {(lim.metric, lim.component): lim for lim in payload.bmc_limits or []}
    assert limits[("cpu_temp_c", "CPU1")].upper_warning == 70.0
    assert limits[("cpu_temp_c", "CPU1")].upper_critical is None
    assert [e.entry_id for e in payload.events or []] == ["IML/1", "IML/2"]

    identity = payload.identity
    assert identity is not None
    assert (identity.vendor, identity.bmc_model, identity.bmc_firmware) == ("HPE", "iLO 5", "3.08")
    assert components(payload, "psu") == ["PSU 1", "PSU 2"]
    assert [c.location for c in payload.components or [] if c.type == "psu"] == ["Bay 1", "Bay 2"]
    assert components(payload, "fan") == [f"Fan {n}" for n in range(1, 7)]
    fw = {f.component: f for f in payload.firmware or []}
    assert fw["System ROM"].component_key == "BIOS"
    assert "Redundant System ROM" not in fw
    assert fw["iLO 5"].component_key == "BMC"
    assert fw["Power Supply Firmware"].component_key == "PSU"
    assert fw["HPE Smart Array P408i-a SR Gen10"].component_type == "storage_controller"


async def test_hpe_power_limit_from_legacy_power() -> None:
    bmc = TreeBmc(HPE)
    path = "/redfish/v1/Chassis/1/Power"
    power = copy.deepcopy(bmc.load(path))
    assert power is not None
    power["PowerControl"][0]["PowerLimit"]["LimitInWatts"] = 650
    bmc.overrides[path] = power
    m = by_metric(await poll_all(bmc))
    assert m["power_limit_w"] == {"": (650.0, None)}


# ---------------------------------------------------------------------------------------------- Lenovo


async def test_lenovo_new_layout() -> None:
    bmc = TreeBmc(LENOVO)
    payload = await poll_all(bmc)
    m = by_metric(payload)
    assert set(m) == COMMON_CODES | {"fan_rpm"}
    assert_no_duplicates(payload)
    assert m["inlet_temp_c"] == {"": (23.0, "OK")}
    assert set(m["cpu_temp_c"]) == {"CPU1", "CPU2"}
    assert set(m["dimm_temp_c"]) == {"DIMM 1", "DIMM 17"}
    assert set(m["fan_rpm"]) == {f"Fan {n}" for n in range(1, 7)}
    assert m["power_w"] == {"": (340.0, "OK")}
    assert set(m["psu_input_v"]) == {"PSU 1", "PSU 2"}
    assert m["storage_health"] == {"RAID_Slot1": (0, "OK")}
    assert m["volume_health"] == {"Volume 0": (0, "OK")}
    assert "DIMM 32" in m["memory_health"]
    assert [e.entry_id for e in payload.events or []] == ["PlatformLog/1", "PlatformLog/2"]  # not AuditLog
    identity = payload.identity
    assert identity is not None
    assert (identity.vendor, identity.bmc_model) == ("Lenovo", "XCC2")
    fw = {f.component: f for f in payload.firmware or []}
    assert fw["UEFI"].component_key == "BIOS"
    assert fw["XCC Primary Firmware"].component_key == "BMC"
    assert "XCC Backup Firmware" not in fw
    assert components(payload, "dimm")[0] == "DIMM 1"


# ------------------------------------------------------------------------------------------- behaviour


@pytest.mark.parametrize(
    ("tree", "adapter"), [(DELL, DellAdapter), (HPE, HpeAdapter), (LENOVO, LenovoAdapter)]
)
def test_vendor_detection(tree: str, adapter: type) -> None:
    bmc = TreeBmc(tree)
    root, systems = bmc.load("/redfish/v1"), bmc.load("/redfish/v1/Systems")
    assert root is not None and systems is not None
    system = bmc.load(systems["Members"][0]["@odata.id"])
    assert system is not None
    assert type(detect_adapter(root, system)) is adapter


async def test_generic_adapter_for_unknown_vendor() -> None:
    bmc = TreeBmc(LENOVO)
    root = copy.deepcopy(bmc.load("/redfish/v1"))
    system = copy.deepcopy(bmc.load("/redfish/v1/Systems/1"))
    assert root is not None and system is not None
    root.pop("Oem")
    root["Vendor"] = "Supermicro"
    system["Manufacturer"] = "Supermicro"
    bmc.overrides["/redfish/v1"] = root
    bmc.overrides["/redfish/v1/Systems/1"] = system
    assert isinstance(detect_adapter(root, system), GenericAdapter)
    payload = await poll_all(bmc)
    assert payload.identity is not None and payload.identity.vendor == "Supermicro"
    m = by_metric(payload)
    # Standard PhysicalContext rules still find every temperature.
    assert {"inlet_temp_c", "exhaust_temp_c", "cpu_temp_c", "dimm_temp_c", "fan_rpm", "power_w"} <= set(m)


async def test_health_states_and_events_are_incremental() -> None:
    bmc = TreeBmc(DELL)
    poller = tree_poller(bmc)
    await poller.poll(ALL_KINDS)

    fan_path = "/redfish/v1/Chassis/System.Embedded.1/ThermalSubsystem/Fans/Fan.Embedded.3A"
    fan = copy.deepcopy(bmc.load(fan_path))
    assert fan is not None
    fan["Status"]["Health"] = "Critical"
    bmc.overrides[fan_path] = fan
    entries_path = "/redfish/v1/Managers/iDRAC.Embedded.1/LogServices/Sel/Entries"
    entries = copy.deepcopy(bmc.load(entries_path))
    assert entries is not None
    entries["Members"].append(
        {
            "@odata.id": f"{entries_path}/3",
            "Id": "3",
            "Created": "2026-10-22T09:59:00+05:30",
            "Severity": "Critical",
            "Message": "Fan 3 failed.",
            "MessageId": "FAN0001",
        }
    )
    bmc.overrides[entries_path] = entries

    result = await poller.poll(HEALTH)
    m = by_metric(result.payload)
    assert m["fan_health"]["Fan 3"] == (2, "Critical")
    events = result.payload.events or []
    assert [e.entry_id for e in events] == ["Sel/3"]
    assert events[0].severity == "Critical"
    assert events[0].time.isoformat() == "2026-10-22T04:29:00+00:00"

    again = await poller.poll(HEALTH)
    assert again.payload.events is None  # nothing new
    await poller.close()


async def test_events_fetched_individually_when_not_inlined() -> None:
    bmc = TreeBmc(HPE)
    poller = tree_poller(bmc)
    result = await poller.poll(ALL_KINDS)
    assert [e.message_id for e in result.payload.events or []] == [
        "IML.0.0.IMLCleared",
        "IML.0.0.FirmwareFlashed",
    ]
    before = bmc.get_count(lambda p: "/IML/Entries/" in p)
    await poller.poll(HEALTH)
    assert bmc.get_count(lambda p: "/IML/Entries/" in p) == before  # seen entries are not re-fetched
    await poller.close()


async def test_unreachable_bmc_sends_single_reading() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    async def no_sleep(_: float) -> None:
        return None

    client = RedfishClient("http://bmc.test", creds(), transport=httpx.MockTransport(handler), sleep=no_sleep)
    poller = ServerPoller(ServerConfig(id=7, bmc_host="http://bmc.test", vendor="HPE"), client)
    result: PollResult = await poller.poll(ALL_KINDS)
    assert not result.ok
    assert result.vendor == "HPE"
    readings = result.payload.readings or []
    assert [(r.metric, r.component, r.value, r.status) for r in readings] == [
        ("bmc_reachable", "", 0, "Unreachable")
    ]
    assert result.payload.identity is None and result.payload.components is None
    await poller.close()


async def test_soft_errors_skip_one_section() -> None:
    bmc = TreeBmc(LENOVO)
    inner = bmc.transport()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/redfish/v1/Systems/1/Storage"):
            return httpx.Response(500)
        return await inner.handle_async_request(request)

    async def no_sleep(_: float) -> None:
        return None

    client = RedfishClient("http://bmc.test", creds(), transport=httpx.MockTransport(handler), sleep=no_sleep)
    poller = ServerPoller(ServerConfig(id=1, bmc_host="http://bmc.test"), client)
    result = await poller.poll(ALL_KINDS)
    assert result.ok
    m = by_metric(result.payload)
    assert "drive_health" not in m and "storage_health" not in m
    assert "fan_rpm" in m and "nic_link" in m
    await poller.close()
