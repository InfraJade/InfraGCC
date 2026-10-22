"""Render a server's Redfish resource tree from its state, in the style of each vendor's BMC.

Coverage by design (see mockups/README.md):
  Dell iDRAC9  — newer layout (ThermalSubsystem/PowerSubsystem/Sensors) AND legacy Thermal/Power;
                 $expand up to 1 level; SEL under the Manager with log entries inlined in Members.
  HPE iLO 5    — legacy Thermal/Power only; no $expand; fans reported in percent; PSUs identified by
                 Oem.Hpe.BayNumber; Integrated Management Log (IML) under the System.
  Lenovo XCC2  — newer layout only; $expand up to 2 levels; PlatformLog under the System.

Resource IDs avoid ':' (real iDRAC drive IDs contain colons) so trees check out on Windows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gcc_redfish_sim.model import (
    OK,
    Controller,
    Fan,
    Psu,
    ServerState,
    Temp,
    worst,
)

Json = dict[str, Any]
R = "/redfish/v1"


@dataclass(frozen=True)
class Style:
    vendor: str
    manufacturer: str
    product: str
    system_id: str
    chassis_id: str
    manager_id: str
    manager_model: str
    new_layout: bool
    legacy_layout: bool
    expand: Json | None
    fan_units: str  # "RPM" or "Percent" (legacy Thermal.Fans)
    log_on_system: bool
    log_id: str
    log_name: str
    log_entry_type: str
    inline_log_members: bool
    other_logs: tuple[tuple[str, str], ...]  # (id, name) of logs the collector should ignore
    bmc_fw_id: str
    bmc_fw_name: str
    bios_fw_id: str
    bios_fw_name: str
    cpu_socket: Callable[[int], str]
    cpu_name: Callable[[int], str]
    memory_type: str
    oem_system: Callable[[ServerState], Json]
    oem_root: Callable[[ServerState], Json]


STYLES: dict[str, Style] = {
    "dell": Style(
        vendor="Dell",
        manufacturer="Dell Inc.",
        product="Integrated Dell Remote Access Controller",
        system_id="System.Embedded.1",
        chassis_id="System.Embedded.1",
        manager_id="iDRAC.Embedded.1",
        manager_model="15G Monolithic",
        new_layout=True,
        legacy_layout=True,
        expand={"ExpandAll": True, "Levels": True, "Links": True, "MaxLevels": 1, "NoLinks": True},
        fan_units="RPM",
        log_on_system=False,
        log_id="Sel",
        log_name="SEL Log",
        log_entry_type="SEL",
        inline_log_members=True,
        other_logs=(("Lclog", "Lifecycle Controller Log"),),
        bmc_fw_id="Installed-25227-{version}__iDRAC.Embedded.1-1",
        bmc_fw_name="Integrated Dell Remote Access Controller",
        bios_fw_id="Installed-159-{version}__BIOS.Setup.1-1",
        bios_fw_name="BIOS",
        cpu_socket=lambda n: f"CPU.Socket.{n}",
        cpu_name=lambda n: f"CPU {n}",
        memory_type="DDR4",
        oem_system=lambda s: {
            "Dell": {
                "DellSystem": {
                    "@odata.type": "#DellSystem.v1_4_0.DellSystem",
                    "ChassisServiceTag": s.sku,
                    "NodeID": s.sku,
                    "SystemGeneration": "15G Monolithic",
                }
            }
        },
        oem_root=lambda s: {"Dell": {"ServiceTag": s.sku, "ManagerMACAddress": s.bmc_mac.lower()}},
    ),
    "hpe": Style(
        vendor="HPE",
        manufacturer="HPE",
        product="ProLiant",
        system_id="1",
        chassis_id="1",
        manager_id="1",
        manager_model="iLO 5",
        new_layout=False,
        legacy_layout=True,
        expand=None,
        fan_units="Percent",
        log_on_system=True,
        log_id="IML",
        log_name="Integrated Management Log",
        log_entry_type="Oem",
        inline_log_members=False,
        other_logs=(),
        bmc_fw_id="1",
        bmc_fw_name="iLO 5",
        bios_fw_id="2",
        bios_fw_name="System ROM",
        cpu_socket=lambda n: f"Proc {n}",
        cpu_name=lambda n: f"Processors {n}",
        memory_type="DDR4",
        oem_system=lambda s: {
            "Hpe": {
                "@odata.type": "#HpeComputerSystemExt.v2_12_0.HpeComputerSystemExt",
                "PostState": "FinishedPost",
                "ServerSignature": 1234567,
            }
        },
        oem_root=lambda s: {
            "Hpe": {"Manager": [{"ManagerType": "iLO 5", "ManagerFirmwareVersion": s.bmc_version}]}
        },
    ),
    "lenovo": Style(
        vendor="Lenovo",
        manufacturer="Lenovo",
        product="ThinkSystem",
        system_id="1",
        chassis_id="1",
        manager_id="1",
        manager_model="Lenovo XClarity Controller 2",
        new_layout=True,
        legacy_layout=False,
        expand={"ExpandAll": True, "Levels": True, "Links": True, "MaxLevels": 2, "NoLinks": True},
        fan_units="RPM",
        log_on_system=True,
        log_id="PlatformLog",
        log_name="Platform Event Log",
        log_entry_type="Event",
        inline_log_members=False,
        other_logs=(("AuditLog", "Audit Event Log"),),
        bmc_fw_id="BMC-Primary",
        bmc_fw_name="XCC Primary Firmware",
        bios_fw_id="UEFI",
        bios_fw_name="UEFI",
        cpu_socket=lambda n: f"CPU {n}",
        cpu_name=lambda n: f"CPU {n}",
        memory_type="DDR5",
        oem_system=lambda s: {
            "Lenovo": {"@odata.type": "#LenovoComputerSystem.v1_0_0.LenovoSystemProperties", "FrontPanelUSB": {}}
        },
        oem_root=lambda s: {"Lenovo": {"MachineType": s.sku[:4], "Product": s.model}},
    ),
}


def link(path: str) -> Json:
    return {"@odata.id": path}


def status(health: str, state: str = "Enabled", rollup: str | None = None) -> Json:
    out: Json = {"State": state, "Health": health}
    if rollup is not None:
        out["HealthRollup"] = rollup
    return out


def _clean(d: Json) -> Json:
    return {k: v for k, v in d.items() if v is not None}


def _collection(path: str, odata_type: str, name: str, members: list[Json]) -> Json:
    return {
        "@odata.id": path,
        "@odata.type": f"#{odata_type}Collection.{odata_type}Collection",
        "Name": name,
        "Members": members,
        "Members@odata.count": len(members),
    }


class TreeBuilder:
    def __init__(self, state: ServerState) -> None:
        self.s = state
        self.st = STYLES[state.profile]
        self.out: dict[str, Json] = {}
        self.sys = f"{R}/Systems/{self.st.system_id}"
        self.chassis = f"{R}/Chassis/{self.st.chassis_id}"
        self.mgr = f"{R}/Managers/{self.st.manager_id}"

    def put(self, path: str, odata_type: str, body: Json) -> None:
        self.out[path] = {"@odata.id": path, "@odata.type": odata_type, **body}

    def put_collection(self, path: str, odata_type: str, name: str, member_paths: list[str]) -> None:
        self.out[path] = _collection(path, odata_type, name, [link(p) for p in member_paths])

    # ------------------------------------------------------------------ root and services
    def root(self) -> None:
        body: Json = {
            "Id": "RootService",
            "Name": "Root Service",
            "RedfishVersion": "1.17.0",
            "UUID": self.s.uuid,
            "Vendor": self.st.vendor,
            "Product": self.st.product,
            "Systems": link(f"{R}/Systems"),
            "Chassis": link(f"{R}/Chassis"),
            "Managers": link(f"{R}/Managers"),
            "SessionService": link(f"{R}/SessionService"),
            "AccountService": link(f"{R}/AccountService"),
            "UpdateService": link(f"{R}/UpdateService"),
            "Links": {"Sessions": link(f"{R}/SessionService/Sessions")},
            "Oem": self.st.oem_root(self.s),
        }
        if self.st.expand is not None:
            body["ProtocolFeaturesSupported"] = {
                "ExpandQuery": self.st.expand,
                "FilterQuery": False,
                "SelectQuery": True,
                "OnlyMemberQuery": True,
            }
        self.put(R, "#ServiceRoot.v1_15_0.ServiceRoot", body)
        self.put(f"{R}/SessionService", "#SessionService.v1_1_9.SessionService", {
            "Id": "SessionService", "Name": "Session Service", "ServiceEnabled": True, "SessionTimeout": 1800,
            "Sessions": link(f"{R}/SessionService/Sessions"),
        })
        self.out[f"{R}/SessionService/Sessions"] = _collection(
            f"{R}/SessionService/Sessions", "Session", "Session Collection", []
        )
        self.put(f"{R}/AccountService", "#AccountService.v1_13_0.AccountService", {
            "Id": "AccountService", "Name": "Account Service", "ServiceEnabled": True,
        })

    # ---------------------------------------------------------------------------- system
    def system(self) -> None:
        s, st = self.s, self.st
        health = s.system_health()
        self.put_collection(f"{R}/Systems", "#ComputerSystemCollection.ComputerSystemCollection",
                            "Computer System Collection", [self.sys])
        self.put(self.sys, "#ComputerSystem.v1_20_0.ComputerSystem", {
            "Id": st.system_id,
            "Name": "System",
            "SystemType": "Physical",
            "Manufacturer": st.manufacturer,
            "Model": s.model,
            "SKU": s.sku,
            "SerialNumber": s.serial,
            "HostName": s.hostname,
            "UUID": s.uuid,
            "AssetTag": s.asset_tag,
            "PowerState": s.power_state,
            "BiosVersion": s.bios_version,
            "Status": status(health, rollup=health),
            "ProcessorSummary": {
                "Count": len(s.cpus),
                "Model": s.cpus[0].model,
                "Status": status(s.component_health("processors"), rollup=s.component_health("processors")),
            },
            "MemorySummary": {
                "TotalSystemMemoryGiB": sum(d.capacity_mib for d in s.dimms) // 1024,
                "Status": status(s.component_health("memory"), rollup=s.component_health("memory")),
            },
            "Processors": link(f"{self.sys}/Processors"),
            "Memory": link(f"{self.sys}/Memory"),
            "Storage": link(f"{self.sys}/Storage"),
            "EthernetInterfaces": link(f"{self.sys}/EthernetInterfaces"),
            "LogServices": link(f"{self.sys}/LogServices"),
            "Links": {"Chassis": [link(self.chassis)], "ManagedBy": [link(self.mgr)]},
            "Oem": st.oem_system(s),
        })
        cpu_paths = []
        for cpu in s.cpus:
            path = f"{self.sys}/Processors/{cpu.key}"
            cpu_paths.append(path)
            self.put(path, "#Processor.v1_18_0.Processor", {
                "Id": cpu.key,
                "Name": st.cpu_name(cpu.socket),
                "Socket": st.cpu_socket(cpu.socket),
                "ProcessorType": "CPU",
                "ProcessorArchitecture": "x86",
                "Manufacturer": "Intel(R) Corporation",
                "Model": cpu.model,
                "TotalCores": cpu.cores,
                "TotalThreads": cpu.cores * 2,
                "MaxSpeedMHz": cpu.speed_mhz,
                "Status": status(cpu.health),
            })
        self.put_collection(f"{self.sys}/Processors", "#ProcessorCollection.ProcessorCollection",
                            "Processors Collection", cpu_paths)
        dimm_paths = []
        for d in s.dimms:
            path = f"{self.sys}/Memory/{d.key}"
            dimm_paths.append(path)
            self.put(path, "#Memory.v1_17_0.Memory", {
                "Id": d.key,
                "Name": d.locator if s.profile != "dell" else f"DIMM {d.locator.split('.')[-1]}",
                "DeviceLocator": d.locator,
                "CapacityMiB": d.capacity_mib,
                "Manufacturer": d.manufacturer,
                "PartNumber": d.part,
                "SerialNumber": d.serial,
                "OperatingSpeedMhz": d.speed_mhz,
                "MemoryDeviceType": st.memory_type,
                "Status": status(d.health),
            })
        self.put_collection(f"{self.sys}/Memory", "#MemoryCollection.MemoryCollection", "Memory Collection",
                            dimm_paths)
        self.storage()
        nic_paths = []
        for nic in s.nics:
            path = f"{self.sys}/EthernetInterfaces/{nic.key}"
            nic_paths.append(path)
            self.put(path, "#EthernetInterface.v1_9_0.EthernetInterface", {
                "Id": nic.key,
                "Name": nic.name,
                "MACAddress": nic.mac,
                "PermanentMACAddress": nic.mac,
                "SpeedMbps": nic.speed_mbps if nic.link_up else 0,
                "LinkStatus": "LinkUp" if nic.link_up else "LinkDown",
                "InterfaceEnabled": True,
                "Status": status(OK),
                "IPv4Addresses": [
                    {"Address": ip, "SubnetMask": "255.255.255.0", "AddressOrigin": "Static"} for ip in nic.ipv4
                ],
            })
        self.put_collection(f"{self.sys}/EthernetInterfaces",
                            "#EthernetInterfaceCollection.EthernetInterfaceCollection",
                            "System Ethernet Interface Collection", nic_paths)

    def storage(self) -> None:
        paths = []
        for ctl in self.s.controllers:
            path = f"{self.sys}/Storage/{ctl.key}"
            paths.append(path)
            self._controller(path, ctl)
        self.put_collection(f"{self.sys}/Storage", "#StorageCollection.StorageCollection", "Storage Collection",
                            paths)

    def _controller(self, path: str, ctl: Controller) -> None:
        drive_paths = {d.key: f"{path}/Drives/{d.key}" for d in ctl.drives}
        rollup = worst([ctl.health] + [d.health for d in ctl.drives] + [v.health for v in ctl.volumes])
        self.put(path, "#Storage.v1_15_0.Storage", {
            "Id": ctl.key,
            "Name": ctl.name,
            "Status": status(ctl.health, rollup=rollup),
            "StorageControllers": [
                {
                    "@odata.id": f"{path}#/StorageControllers/0",
                    "MemberId": "0",
                    "Name": ctl.name,
                    "Model": ctl.model,
                    "FirmwareVersion": ctl.firmware,
                    "Status": status(ctl.health),
                }
            ],
            "Drives": [link(p) for p in drive_paths.values()],
            "Drives@odata.count": len(drive_paths),
            "Volumes": link(f"{path}/Volumes"),
        })
        for d in ctl.drives:
            self.put(drive_paths[d.key], "#Drive.v1_17_0.Drive", _clean({
                "Id": d.key,
                "Name": d.name,
                "Model": d.model,
                "SerialNumber": d.serial,
                "Revision": d.revision,
                "CapacityBytes": d.capacity_bytes,
                "MediaType": d.media,
                "Protocol": d.protocol,
                "PredictedMediaLifeLeftPercent": round(d.life_left_pct, 1) if d.life_left_pct is not None else None,
                "PhysicalLocation": {"PartLocation": {"LocationOrdinalValue": d.bay, "LocationType": "Bay"}},
                "Status": status(d.health),
            }))
        vol_paths = []
        for v in ctl.volumes:
            vpath = f"{path}/Volumes/{v.key}"
            vol_paths.append(vpath)
            self.put(vpath, "#Volume.v1_9_0.Volume", {
                "Id": v.key,
                "Name": v.name,
                "RAIDType": v.raid,
                "CapacityBytes": v.capacity_bytes,
                "Status": status(v.health),
                "Links": {"Drives": [link(drive_paths[k]) for k in v.drive_keys]},
            })
        self.put_collection(f"{path}/Volumes", "#VolumeCollection.VolumeCollection", "Volume Collection", vol_paths)

    # --------------------------------------------------------------------------- chassis
    def chassis_tree(self) -> None:
        s, st = self.s, self.st
        members = [self.chassis]
        body: Json = {
            "Id": st.chassis_id,
            "Name": "Computer System Chassis",
            "ChassisType": "RackMount",
            "Manufacturer": st.manufacturer,
            "Model": s.model,
            "SerialNumber": s.serial,
            "SKU": s.sku,
            "PartNumber": f"{s.sku}-PN",
            "HeightMm": s.height_mm,
            "PowerState": s.power_state,
            "Status": status(s.system_health(), rollup=s.system_health()),
            "Links": {"ComputerSystems": [link(self.sys)], "ManagedBy": [link(self.mgr)]},
        }
        if st.legacy_layout:
            body["Thermal"] = link(f"{self.chassis}/Thermal")
            body["Power"] = link(f"{self.chassis}/Power")
            self.legacy_thermal()
            self.legacy_power()
        if st.new_layout:
            body["ThermalSubsystem"] = link(f"{self.chassis}/ThermalSubsystem")
            body["PowerSubsystem"] = link(f"{self.chassis}/PowerSubsystem")
            body["EnvironmentMetrics"] = link(f"{self.chassis}/EnvironmentMetrics")
            body["Sensors"] = link(f"{self.chassis}/Sensors")
            self.new_thermal()
            self.new_power()
            self.sensors()
        self.put(self.chassis, "#Chassis.v1_23_0.Chassis", body)
        if s.profile == "dell":
            # A second chassis (the drive backplane) proves the collector follows System.Links.Chassis.
            backplane = f"{R}/Chassis/Enclosure.Internal.0-1"
            members.append(backplane)
            self.put(backplane, "#Chassis.v1_23_0.Chassis", {
                "Id": "Enclosure.Internal.0-1",
                "Name": "BP_PSV16 0:1",
                "ChassisType": "Enclosure",
                "Status": status(OK),
                "Links": {"ContainedBy": link(self.chassis)},
            })
        self.put_collection(f"{R}/Chassis", "#ChassisCollection.ChassisCollection", "Chassis Collection", members)

    def _temp_legacy(self, i: int, t: Temp) -> Json:
        return _clean({
            "@odata.id": f"{self.chassis}/Thermal#/Temperatures/{i}",
            "MemberId": t.key if self.s.profile != "dell" else f"iDRAC.Embedded.1#{t.key}",
            "Name": t.name,
            "SensorNumber": i + 1,
            "ReadingCelsius": round(t.reading, 1),
            "UpperThresholdNonCritical": t.upper_caution,
            "UpperThresholdCritical": t.upper_critical,
            "PhysicalContext": t.context,
            "Status": status(t.health),
        })

    def _fan_legacy(self, i: int, f: Fan) -> Json:
        reading: float = round(f.rpm) if self.st.fan_units == "RPM" else round(f.pct)
        return _clean({
            "@odata.id": f"{self.chassis}/Thermal#/Fans/{i}",
            "MemberId": f.key,
            "Name": f.name,
            "Reading": reading,
            "ReadingUnits": self.st.fan_units,
            "LowerThresholdNonCritical": f.lower_caution if self.st.fan_units == "RPM" else None,
            "LowerThresholdCritical": f.lower_critical if self.st.fan_units == "RPM" else None,
            "PhysicalContext": "SystemBoard",
            "Status": status(f.health),
        })

    def legacy_thermal(self) -> None:
        s = self.s
        fans = [self._fan_legacy(i, f) for i, f in enumerate(s.fans)]
        self.put(f"{self.chassis}/Thermal", "#Thermal.v1_7_0.Thermal", {
            "Id": "Thermal",
            "Name": "Thermal",
            "Temperatures": [self._temp_legacy(i, t) for i, t in enumerate(s.temps)],
            "Fans": fans,
            "Redundancy": [
                {
                    "@odata.id": f"{self.chassis}/Thermal#/Redundancy/0",
                    "MemberId": "0",
                    "Name": "System Board Fan Redundancy",
                    "Mode": "N+m",
                    "MinNumNeeded": len(s.fans) - 1,
                    "MaxNumSupported": len(s.fans),
                    "RedundancySet": [link(f["@odata.id"]) for f in fans],
                    "Status": status(s.fan_redundancy_health()),
                }
            ],
        })

    def legacy_power(self) -> None:
        s = self.s
        supplies = []
        for i, p in enumerate(s.psus):
            entry: Json = _clean({
                "@odata.id": f"{self.chassis}/Power#/PowerSupplies/{i}",
                "MemberId": p.key,
                "Name": p.name,
                "Model": p.model,
                "SerialNumber": p.serial,
                "FirmwareVersion": p.firmware,
                "PowerCapacityWatts": p.capacity_w,
                "LineInputVoltage": round(p.input_v),
                "LineInputVoltageType": "ACMidLine",
                "PowerOutputWatts": round(p.output_w),
                "Status": status(p.health),
            })
            if s.profile == "hpe":
                entry["Oem"] = {"Hpe": {"BayNumber": p.bay, "PowerSupplyStatus": {"State": "Ok"}}}
            supplies.append(entry)
        self.put(f"{self.chassis}/Power", "#Power.v1_6_0.Power", {
            "Id": "Power",
            "Name": "Power",
            "PowerControl": [
                {
                    "@odata.id": f"{self.chassis}/Power#/PowerControl/0",
                    "MemberId": "0",
                    "Name": "System Power Control",
                    "PowerConsumedWatts": round(s.power_w),
                    "PowerCapacityWatts": s.power_capacity_w,
                    "PowerLimit": {"LimitInWatts": s.power_limit_w, "LimitException": "NoAction"},
                    "PowerMetrics": {"IntervalInMin": 60, "AverageConsumedWatts": round(s.power_w)},
                }
            ],
            "PowerSupplies": supplies,
            "Redundancy": [
                {
                    "@odata.id": f"{self.chassis}/Power#/Redundancy/0",
                    "MemberId": "0",
                    "Name": "System Board PS Redundancy",
                    "Mode": "Failover",
                    "MinNumNeeded": 1,
                    "MaxNumSupported": len(s.psus),
                    "RedundancySet": [link(p["@odata.id"]) for p in supplies],
                    "Status": status(s.psu_redundancy_health()),
                }
            ],
        })

    def _fan_sensor_id(self, f: Fan) -> str:
        return f"{f.key.replace('.', '')}Speed"

    def new_thermal(self) -> None:
        s, c = self.s, self.chassis
        fan_paths = [f"{c}/ThermalSubsystem/Fans/{f.key}" for f in s.fans]
        self.put(f"{c}/ThermalSubsystem", "#ThermalSubsystem.v1_3_1.ThermalSubsystem", {
            "Id": "ThermalSubsystem",
            "Name": "Thermal Subsystem",
            "Fans": link(f"{c}/ThermalSubsystem/Fans"),
            "ThermalMetrics": link(f"{c}/ThermalSubsystem/ThermalMetrics"),
            "FanRedundancy": [
                {
                    "RedundancyType": "NPlusM",
                    "MaxSupportedInGroup": len(s.fans),
                    "MinNeededInGroup": len(s.fans) - 1,
                    "RedundancyGroup": [link(p) for p in fan_paths],
                    "Status": status(s.fan_redundancy_health()),
                }
            ],
            "Status": status(s.component_health("thermal"), rollup=s.component_health("thermal")),
        })
        by_context = {t.context: t for t in s.temps}
        self.put(f"{c}/ThermalSubsystem/ThermalMetrics", "#ThermalMetrics.v1_3_1.ThermalMetrics", {
            "Id": "ThermalMetrics",
            "Name": "Chassis Thermal Metrics",
            "TemperatureSummaryCelsius": {
                ctx: {"Reading": round(t.reading, 1), "DataSourceUri": f"{c}/Sensors/{t.key}"}
                for ctx, t in by_context.items()
                if ctx in ("Intake", "Exhaust")
            },
            "TemperatureReadingsCelsius": [
                {
                    "DataSourceUri": f"{c}/Sensors/{t.key}",
                    "DeviceName": t.name,
                    "PhysicalContext": t.context,
                    "Reading": round(t.reading, 1),
                }
                for t in s.temps
            ],
        })
        for f, path in zip(s.fans, fan_paths, strict=True):
            self.put(path, "#Fan.v1_5_1.Fan", {
                "Id": f.key,
                "Name": f.name,
                "PhysicalContext": "Chassis",
                "HotPluggable": True,
                "Status": status(f.health),
                "SpeedPercent": {
                    "Reading": f.pct,
                    "SpeedRPM": round(f.rpm),
                    "DataSourceUri": f"{c}/Sensors/{self._fan_sensor_id(f)}",
                },
            })
        self.put_collection(f"{c}/ThermalSubsystem/Fans", "#FanCollection.FanCollection", "Fan Collection",
                            fan_paths)

    def _psu_path(self, p: Psu) -> str:
        return f"{self.chassis}/PowerSubsystem/PowerSupplies/{p.key}"

    def new_power(self) -> None:
        s, c = self.s, self.chassis
        psu_paths = [self._psu_path(p) for p in s.psus]
        self.put(f"{c}/PowerSubsystem", "#PowerSubsystem.v1_1_1.PowerSubsystem", {
            "Id": "PowerSubsystem",
            "Name": "Power Subsystem",
            "CapacityWatts": s.power_capacity_w,
            "Allocation": {"RequestedWatts": round(s.power_w), "AllocatedWatts": s.power_capacity_w},
            "PowerSupplies": link(f"{c}/PowerSubsystem/PowerSupplies"),
            "PowerSupplyRedundancy": [
                {
                    "RedundancyType": "Failover",
                    "MaxSupportedInGroup": len(s.psus),
                    "MinNeededInGroup": 1,
                    "RedundancyGroup": [link(p) for p in psu_paths],
                    "Status": status(s.psu_redundancy_health()),
                }
            ],
            "Status": status(s.component_health("power"), rollup=s.component_health("power")),
        })
        for p, path in zip(s.psus, psu_paths, strict=True):
            self.put(path, "#PowerSupply.v1_5_3.PowerSupply", {
                "Id": p.key,
                "Name": p.name,
                "Model": p.model,
                "SerialNumber": p.serial,
                "FirmwareVersion": p.firmware,
                "PowerCapacityWatts": p.capacity_w,
                "InputNominalVoltageType": "AC200To240V",
                "LineInputStatus": "Normal" if p.input_v > 1 else "LossOfInput",
                "HotPluggable": True,
                "Location": {
                    "PartLocation": {"ServiceLabel": f"PSU {p.bay}", "LocationType": "Bay",
                                     "LocationOrdinalValue": p.bay}
                },
                "Status": status(p.health),
                "Metrics": link(f"{path}/Metrics"),
            })
            self.put(f"{path}/Metrics", "#PowerSupplyMetrics.v1_1_1.PowerSupplyMetrics", {
                "Id": "Metrics",
                "Name": f"Metrics for {p.name}",
                "Status": status(p.health),
                "InputVoltage": {"Reading": round(p.input_v, 1), "DataSourceUri": f"{c}/Sensors/PS{p.bay}InputVoltage"},
                "OutputPowerWatts": {"Reading": round(p.output_w, 1)},
            })
        self.put_collection(f"{c}/PowerSubsystem/PowerSupplies", "#PowerSupplyCollection.PowerSupplyCollection",
                            "Power Supply Collection", psu_paths)
        self.put(f"{c}/EnvironmentMetrics", "#EnvironmentMetrics.v1_3_1.EnvironmentMetrics", {
            "Id": "EnvironmentMetrics",
            "Name": "Chassis Environment Metrics",
            "PowerWatts": {"Reading": round(s.power_w, 1), "DataSourceUri": f"{c}/Sensors/TotalPower"},
            "PowerLimitWatts": {
                "SetPoint": s.power_limit_w,
                "ControlMode": "Automatic" if s.power_limit_w else "Disabled",
            },
        })

    def sensors(self) -> None:
        s, c = self.s, self.chassis
        paths: list[str] = []

        def add(sensor_id: str, body: Json) -> None:
            path = f"{c}/Sensors/{sensor_id}"
            paths.append(path)
            self.put(path, "#Sensor.v1_8_1.Sensor", {"Id": sensor_id, **body})

        for t in s.temps:
            thresholds = _clean({
                "UpperCaution": {"Reading": t.upper_caution} if t.upper_caution is not None else None,
                "UpperCritical": {"Reading": t.upper_critical} if t.upper_critical is not None else None,
            })
            add(t.key, {
                "Name": t.name,
                "ReadingType": "Temperature",
                "ReadingUnits": "Cel",
                "Reading": round(t.reading, 1),
                "PhysicalContext": t.context,
                "Status": status(t.health),
                "Thresholds": thresholds,
            })
        for f in s.fans:
            add(self._fan_sensor_id(f), {
                "Name": f.name,
                "ReadingType": "Rotational",
                "ReadingUnits": "RPM",
                "Reading": round(f.rpm),
                "PhysicalContext": "Fan",
                "Status": status(f.health),
                "Thresholds": _clean({
                    "LowerCaution": {"Reading": f.lower_caution} if f.lower_caution is not None else None,
                    "LowerCritical": {"Reading": f.lower_critical} if f.lower_critical is not None else None,
                }),
            })
        add("TotalPower", {
            "Name": "System Power",
            "ReadingType": "Power",
            "ReadingUnits": "W",
            "Reading": round(s.power_w, 1),
            "PhysicalContext": "Chassis",
            "Status": status(OK),
        })
        for p in s.psus:
            add(f"PS{p.bay}InputVoltage", {
                "Name": f"PS{p.bay} Input Voltage",
                "ReadingType": "Voltage",
                "ReadingUnits": "V",
                "Reading": round(p.input_v, 1),
                "PhysicalContext": "PowerSupply",
                "Status": status(p.health),
            })
        self.put_collection(f"{c}/Sensors", "#SensorCollection.SensorCollection", "Sensor Collection", paths)

    # --------------------------------------------------------------------------- manager
    def manager(self) -> None:
        s, st = self.s, self.st
        self.put_collection(f"{R}/Managers", "#ManagerCollection.ManagerCollection", "Manager Collection",
                            [self.mgr])
        self.put(self.mgr, "#Manager.v1_17_0.Manager", {
            "Id": st.manager_id,
            "Name": "Manager",
            "ManagerType": "BMC",
            "Model": st.manager_model,
            "FirmwareVersion": s.bmc_version,
            "UUID": s.uuid,
            "PowerState": "On",
            "Status": status(s.bmc_health),
            "EthernetInterfaces": link(f"{self.mgr}/EthernetInterfaces"),
            "LogServices": link(f"{self.mgr}/LogServices"),
            "Links": {"ManagerForServers": [link(self.sys)], "ManagerForChassis": [link(self.chassis)]},
        })
        nic = f"{self.mgr}/EthernetInterfaces/NIC.1"
        self.put(nic, "#EthernetInterface.v1_9_0.EthernetInterface", {
            "Id": "NIC.1",
            "Name": "Manager Ethernet Interface",
            "MACAddress": s.bmc_mac,
            "PermanentMACAddress": s.bmc_mac,
            "LinkStatus": "LinkUp",
            "HostName": f"bmc-{s.hostname.split('.')[0]}",
            "IPv4Addresses": [{"Address": s.bmc_ip, "SubnetMask": "255.255.255.0", "AddressOrigin": "Static"}],
            "Status": status(OK),
        })
        self.put_collection(f"{self.mgr}/EthernetInterfaces",
                            "#EthernetInterfaceCollection.EthernetInterfaceCollection",
                            "Manager Ethernet Interface Collection", [nic])

    def logs(self) -> None:
        s, st = self.s, self.st
        owner = self.sys if st.log_on_system else self.mgr
        other_owner = self.mgr if st.log_on_system else self.sys
        main = f"{owner}/LogServices/{st.log_id}"
        self._log_service(main, st.log_id, st.log_name, st.log_entry_type)
        entries = []
        for e in s.sel:
            entry = {
                "@odata.id": f"{main}/Entries/{e.id}",
                "@odata.type": "#LogEntry.v1_15_0.LogEntry",
                "Id": e.id,
                "Name": f"Log Entry {e.id}",
                "Created": e.created,
                "EntryType": st.log_entry_type if st.log_entry_type != "Oem" else "Oem",
                "Severity": e.severity,
                "Message": e.message,
                "MessageId": e.message_id,
            }
            entries.append(entry)
            self.out[entry["@odata.id"]] = entry
        coll = _collection(f"{main}/Entries", "LogEntry", "Log Entry Collection",
                           entries if st.inline_log_members else [link(e["@odata.id"]) for e in entries])
        self.out[f"{main}/Entries"] = coll
        owner_members = [main]
        for log_id, name in st.other_logs:
            path = f"{owner}/LogServices/{log_id}"
            self._log_service(path, log_id, name, "Event")
            self.out[f"{path}/Entries"] = _collection(f"{path}/Entries", "LogEntry", "Log Entry Collection", [])
            owner_members.append(path)
        self.put_collection(f"{owner}/LogServices", "#LogServiceCollection.LogServiceCollection",
                            "Log Service Collection", owner_members)
        self.put_collection(f"{other_owner}/LogServices", "#LogServiceCollection.LogServiceCollection",
                            "Log Service Collection", [])

    def _log_service(self, path: str, log_id: str, name: str, entry_type: str) -> None:
        self.put(path, "#LogService.v1_5_0.LogService", {
            "Id": log_id,
            "Name": name,
            "LogEntryType": entry_type,
            "MaxNumberOfRecords": 1024,
            "OverWritePolicy": "WrapsWhenFull",
            "ServiceEnabled": True,
            "Entries": link(f"{path}/Entries"),
        })

    # -------------------------------------------------------------------------- firmware
    def firmware(self) -> None:
        s, st = self.s, self.st
        base = f"{R}/UpdateService/FirmwareInventory"
        entries = [
            (st.bios_fw_id.format(version=s.bios_version), st.bios_fw_name, s.bios_version, True),
            (st.bmc_fw_id.format(version=s.bmc_version), st.bmc_fw_name, s.bmc_version, True),
        ] + [(e.id, e.name, e.version, e.updateable) for e in s.firmware_extra]
        paths = []
        for fid, name, version, updateable in entries:
            path = f"{base}/{fid}"
            paths.append(path)
            self.put(path, "#SoftwareInventory.v1_10_0.SoftwareInventory", {
                "Id": fid,
                "Name": name,
                "Version": version,
                "Updateable": updateable,
                "Status": status(OK),
            })
        self.put(f"{R}/UpdateService", "#UpdateService.v1_11_0.UpdateService", {
            "Id": "UpdateService",
            "Name": "Update Service",
            "ServiceEnabled": True,
            "FirmwareInventory": link(base),
        })
        self.put_collection(base, "#SoftwareInventoryCollection.SoftwareInventoryCollection", "Firmware Inventory",
                            paths)


def build_tree(state: ServerState) -> dict[str, Json]:
    """Every resource of the server, keyed by its @odata.id path."""
    b = TreeBuilder(state)
    b.root()
    b.system()
    b.chassis_tree()
    b.manager()
    b.logs()
    b.firmware()
    return b.out
