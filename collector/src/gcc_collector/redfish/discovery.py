"""Walk a BMC's Redfish tree from the service root and remember where things are.

Nothing is assumed about IDs: every path comes from an ``@odata.id`` link (Systems -> the first system ->
its Processors / Memory / Storage / EthernetInterfaces / LogServices; the system's ``Links.Chassis`` ->
ThermalSubsystem / PowerSubsystem / EnvironmentMetrics / Sensors and the legacy Thermal / Power;
``Links.ManagedBy`` -> the manager, its EthernetInterfaces and LogServices; UpdateService ->
FirmwareInventory). The result is cached per BMC by the poller and rebuilt when a cached path returns 404.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from gcc_collector.redfish.client import Json, NotFound, RedfishClient, RedfishHTTPError

log = logging.getLogger("gcc.collector.discovery")

ROOT = "/redfish/v1"


def link(resource: Json | None, key: str) -> str | None:
    """``resource[key]["@odata.id"]`` if present."""
    if not isinstance(resource, dict):
        return None
    value = resource.get(key)
    if isinstance(value, dict):
        target = value.get("@odata.id")
        if isinstance(target, str) and target:
            return target.rstrip("/") or target
    return None


def links(resource: Json | None, *keys: str) -> list[str]:
    """``@odata.id`` values of an array of links at ``resource[keys[0]][keys[1]]...``."""
    node: Any = resource
    for key in keys:
        if not isinstance(node, dict):
            return []
        node = node.get(key)
    if not isinstance(node, list):
        return []
    out = []
    for item in node:
        if isinstance(item, dict) and isinstance(item.get("@odata.id"), str):
            out.append(item["@odata.id"].rstrip("/"))
    return out


@dataclass
class ChassisMap:
    path: str
    thermal_subsystem: str | None = None
    power_subsystem: str | None = None
    environment_metrics: str | None = None
    sensors: str | None = None
    thermal: str | None = None  # legacy
    power: str | None = None  # legacy

    @property
    def has_new_layout(self) -> bool:
        return any((self.thermal_subsystem, self.power_subsystem, self.sensors, self.environment_metrics))

    @property
    def has_any_sensors(self) -> bool:
        return self.has_new_layout or self.thermal is not None or self.power is not None


@dataclass
class LogServiceRef:
    path: str
    id: str
    name: str
    entries: str | None
    entry_type: str | None
    owner: str  # "system" or "manager"


@dataclass
class BmcMap:
    root: Json
    system_path: str
    system: Json
    processors: str | None = None
    memory: str | None = None
    storage: str | None = None
    system_ethernet: str | None = None
    chassis: list[ChassisMap] = field(default_factory=list)
    chassis_resources: dict[str, Json] = field(default_factory=dict)
    manager_path: str | None = None
    manager: Json | None = None
    manager_ethernet: str | None = None
    log_services: list[LogServiceRef] = field(default_factory=list)
    firmware_inventory: str | None = None
    discovered_at: float = field(default_factory=time.monotonic)


class DiscoveryError(RuntimeError):
    """The tree has no usable ComputerSystem."""


async def _first_member(client: RedfishClient, collection: str | None) -> str | None:
    if collection is None:
        return None
    coll = await client.get(collection)
    members = links(coll, "Members")
    return members[0] if members else None


async def _log_services(client: RedfishClient, collection: str | None, owner: str) -> list[LogServiceRef]:
    if collection is None:
        return []
    try:
        services = await client.get_collection(collection)
    except RedfishHTTPError as exc:
        log.info("%s: cannot list %s (%s)", client.bmc_host, collection, exc)
        return []
    out = []
    for svc in services:
        path = svc.get("@odata.id")
        if not isinstance(path, str):
            continue
        out.append(
            LogServiceRef(
                path=path.rstrip("/"),
                id=str(svc.get("Id") or path.rstrip("/").rsplit("/", 1)[-1]),
                name=str(svc.get("Name") or ""),
                entries=link(svc, "Entries"),
                entry_type=svc.get("LogEntryType") if isinstance(svc.get("LogEntryType"), str) else None,
                owner=owner,
            )
        )
    return out


def _chassis_map(path: str, body: Json) -> ChassisMap:
    return ChassisMap(
        path=path,
        thermal_subsystem=link(body, "ThermalSubsystem"),
        power_subsystem=link(body, "PowerSubsystem"),
        environment_metrics=link(body, "EnvironmentMetrics"),
        sensors=link(body, "Sensors"),
        thermal=link(body, "Thermal"),
        power=link(body, "Power"),
    )


async def discover(client: RedfishClient) -> BmcMap:
    """Walk the tree once. Raises DiscoveryError if there is no system; BMC errors propagate."""
    root = await client.get_root()
    system_path = await _first_member(client, link(root, "Systems"))
    if system_path is None:
        raise DiscoveryError(f"{client.bmc_host}: no ComputerSystem under {ROOT}/Systems")
    system = await client.get(system_path)
    bmc = BmcMap(
        root=root,
        system_path=system_path,
        system=system,
        processors=link(system, "Processors"),
        memory=link(system, "Memory"),
        storage=link(system, "Storage"),
        system_ethernet=link(system, "EthernetInterfaces"),
    )

    # Chassis: the ones the system says it lives in; all chassis only if none of those has sensors.
    candidates = links(system, "Links", "Chassis")
    for path in candidates:
        try:
            body = await client.get(path)
        except NotFound:
            continue
        bmc.chassis_resources[path] = body
        cmap = _chassis_map(path, body)
        if cmap.has_any_sensors:
            bmc.chassis.append(cmap)
    if not bmc.chassis:
        coll_path = link(root, "Chassis")
        if coll_path is not None:
            for body in await client.get_collection(coll_path):
                member_path = body.get("@odata.id")
                if not isinstance(member_path, str):
                    continue
                bmc.chassis_resources[member_path] = body
                cmap = _chassis_map(member_path.rstrip("/"), body)
                if cmap.has_any_sensors:
                    bmc.chassis.append(cmap)

    managers = links(system, "Links", "ManagedBy")
    bmc.manager_path = managers[0] if managers else await _first_member(client, link(root, "Managers"))
    if bmc.manager_path is not None:
        bmc.manager = await client.get(bmc.manager_path)
        bmc.manager_ethernet = link(bmc.manager, "EthernetInterfaces")

    bmc.log_services = await _log_services(client, link(system, "LogServices"), "system")
    bmc.log_services += await _log_services(client, link(bmc.manager, "LogServices"), "manager")

    update_service = link(root, "UpdateService")
    if update_service is not None:
        try:
            bmc.firmware_inventory = link(await client.get(update_service), "FirmwareInventory")
        except RedfishHTTPError as exc:
            log.info("%s: no UpdateService (%s)", client.bmc_host, exc)
    log.debug(
        "%s: discovered system %s, %d chassis, manager %s, %d log services",
        client.bmc_host,
        system_path,
        len(bmc.chassis),
        bmc.manager_path,
        len(bmc.log_services),
    )
    return bmc
