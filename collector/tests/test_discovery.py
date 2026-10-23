"""Discovery walks @odata.id links; the poller rediscovers when a cached path starts returning 404."""

from __future__ import annotations

import copy

from conftest import DELL, HPE, LENOVO, TreeBmc, tree_client, tree_poller

from gcc_collector.adapters import ALL_KINDS
from gcc_collector.redfish.discovery import discover


async def test_dell_discovery() -> None:
    bmc = TreeBmc(DELL)
    client = tree_client(bmc)
    found = await discover(client)
    assert found.system_path == "/redfish/v1/Systems/System.Embedded.1"
    assert found.processors == "/redfish/v1/Systems/System.Embedded.1/Processors"
    assert found.storage == "/redfish/v1/Systems/System.Embedded.1/Storage"
    # Only the chassis the system lives in (Links.Chassis), not the drive backplane.
    assert [c.path for c in found.chassis] == ["/redfish/v1/Chassis/System.Embedded.1"]
    chassis = found.chassis[0]
    assert chassis.sensors == "/redfish/v1/Chassis/System.Embedded.1/Sensors"
    assert chassis.thermal_subsystem and chassis.power_subsystem and chassis.environment_metrics
    assert chassis.thermal and chassis.power  # Dell also has the legacy layout
    assert found.manager_path == "/redfish/v1/Managers/iDRAC.Embedded.1"
    assert found.manager_ethernet == "/redfish/v1/Managers/iDRAC.Embedded.1/EthernetInterfaces"
    assert {(log.owner, log.id) for log in found.log_services} == {("manager", "Sel"), ("manager", "Lclog")}
    assert found.firmware_inventory == "/redfish/v1/UpdateService/FirmwareInventory"
    await client.close()


async def test_hpe_discovery_legacy_only() -> None:
    client = tree_client(TreeBmc(HPE))
    found = await discover(client)
    assert found.system_path == "/redfish/v1/Systems/1"
    (chassis,) = found.chassis
    assert not chassis.has_new_layout
    assert chassis.thermal == "/redfish/v1/Chassis/1/Thermal"
    assert chassis.power == "/redfish/v1/Chassis/1/Power"
    assert [(log.owner, log.id) for log in found.log_services] == [("system", "IML")]
    await client.close()


async def test_lenovo_discovery_new_only() -> None:
    client = tree_client(TreeBmc(LENOVO))
    found = await discover(client)
    (chassis,) = found.chassis
    assert chassis.has_new_layout
    assert chassis.thermal is None and chassis.power is None
    assert {log.id for log in found.log_services} == {"PlatformLog", "AuditLog"}
    await client.close()


async def test_ids_are_never_assumed() -> None:
    """Rename the system: discovery must find it from the Systems collection, not a guessed id."""
    bmc = TreeBmc(LENOVO)
    old = "/redfish/v1/Systems/1"
    new = "/redfish/v1/Systems/Node-A7"
    system = copy.deepcopy(bmc.load(old))
    assert system is not None
    system["@odata.id"] = new
    system["Id"] = "Node-A7"
    bmc.overrides[new] = system
    bmc.overrides["/redfish/v1/Systems"] = {"Members": [{"@odata.id": new}], "Members@odata.count": 1}
    bmc.missing.add(old)
    client = tree_client(bmc)
    found = await discover(client)
    assert found.system_path == new
    await client.close()


async def test_discovery_is_cached_and_redone_on_404() -> None:
    bmc = TreeBmc(DELL)
    poller = tree_poller(bmc)
    first = await poller.poll(ALL_KINDS)
    assert first.ok
    root_gets = bmc.get_count(lambda p: p == "/redfish/v1")
    # A sensor-only poll reuses the cached map: no walk from the root.
    second = await poller.poll(frozenset({"sensors"}))
    assert second.ok
    assert bmc.get_count(lambda p: p == "/redfish/v1") == root_gets

    # Firmware update moved the manager to a new id.
    old = "/redfish/v1/Managers/iDRAC.Embedded.1"
    new = "/redfish/v1/Managers/iDRAC.Embedded.2"
    manager = copy.deepcopy(bmc.load(old))
    system = copy.deepcopy(bmc.load("/redfish/v1/Systems/System.Embedded.1"))
    assert manager is not None and system is not None
    manager["@odata.id"] = new
    system["Links"]["ManagedBy"] = [{"@odata.id": new}]
    bmc.overrides[new] = manager
    bmc.overrides["/redfish/v1/Systems/System.Embedded.1"] = system
    bmc.missing.add(old)

    third = await poller.poll(frozenset({"sensors"}))
    assert third.ok
    assert bmc.get_count(lambda p: p == "/redfish/v1") == root_gets + 1
    assert poller.bmc is not None and poller.bmc.manager_path == new
    metrics = {r.metric for r in third.payload.readings or []}
    assert "bmc_health" in metrics
    await poller.close()
