"""The state of one simulated server. Tree builders render Redfish resources from it."""

from __future__ import annotations

from dataclasses import dataclass, field

OK = "OK"
WARNING = "Warning"
CRITICAL = "Critical"
_RANK = {OK: 0, WARNING: 1, CRITICAL: 2}


def worst(healths: list[str]) -> str:
    return max(healths, key=lambda h: _RANK[h], default=OK)


@dataclass
class Temp:
    key: str  # stable sensor id
    name: str  # vendor sensor name, e.g. "System Board Inlet Temp", "01-Inlet Ambient"
    context: str  # Redfish PhysicalContext: Intake, Exhaust, CPU, Memory, SystemBoard
    reading: float
    upper_caution: float | None
    upper_critical: float | None
    nominal: float  # where the simulator drifts around
    health: str = OK


@dataclass
class Fan:
    key: str
    name: str
    rpm: float
    max_rpm: float
    nominal_pct: float
    lower_caution: float | None
    lower_critical: float | None
    health: str = OK

    @property
    def pct(self) -> float:
        return round(100.0 * self.rpm / self.max_rpm, 1)


@dataclass
class Psu:
    key: str
    name: str
    bay: int
    model: str
    serial: str
    firmware: str
    capacity_w: int
    input_v: float
    nominal_v: float
    output_w: float = 0.0
    health: str = OK


@dataclass
class Cpu:
    key: str
    socket: int
    model: str
    cores: int
    speed_mhz: int
    health: str = OK


@dataclass
class Dimm:
    key: str
    locator: str
    capacity_mib: int
    manufacturer: str
    part: str
    serial: str
    speed_mhz: int
    health: str = OK


@dataclass
class Drive:
    key: str
    bay: int
    name: str
    model: str
    serial: str
    capacity_bytes: int
    media: str  # SSD / HDD
    protocol: str  # SAS / SATA / NVMe
    revision: str
    life_left_pct: float | None
    health: str = OK


@dataclass
class Volume:
    key: str
    name: str
    raid: str  # RAID1, RAID5, RAID10
    capacity_bytes: int
    drive_keys: list[str]
    health: str = OK


@dataclass
class Controller:
    key: str
    name: str
    model: str
    firmware: str
    drives: list[Drive]
    volumes: list[Volume]
    health: str = OK


@dataclass
class Nic:
    key: str
    name: str
    mac: str
    speed_mbps: int
    link_up: bool
    ipv4: list[str] = field(default_factory=list)


@dataclass
class LogEntry:
    id: str
    created: str  # ISO 8601
    severity: str  # OK / Warning / Critical
    message: str
    message_id: str


@dataclass
class FirmwareEntry:
    id: str
    name: str
    version: str
    updateable: bool = True


@dataclass
class ServerState:
    profile: str  # "dell" | "hpe" | "lenovo"
    model: str
    serial: str
    sku: str
    hostname: str
    uuid: str
    asset_tag: str
    height_mm: float
    bios_version: str
    bmc_version: str
    bmc_mac: str
    bmc_ip: str
    temps: list[Temp]
    fans: list[Fan]
    psus: list[Psu]
    power_w: float
    power_capacity_w: int
    cpus: list[Cpu]
    dimms: list[Dimm]
    controllers: list[Controller]
    nics: list[Nic]
    sel: list[LogEntry] = field(default_factory=list)
    firmware_extra: list[FirmwareEntry] = field(default_factory=list)
    power_limit_w: int | None = None
    power_state: str = "On"
    bmc_health: str = OK
    load: float = 0.45  # 0..1, drives CPU temperature, power and fans in the simulator

    def fan_redundancy_health(self) -> str:
        return OK if all(f.health == OK for f in self.fans) else WARNING

    def psu_redundancy_health(self) -> str:
        failed = [p for p in self.psus if p.health == CRITICAL or p.input_v < 1]
        return CRITICAL if failed else OK

    def drives(self) -> list[Drive]:
        return [d for c in self.controllers for d in c.drives]

    def system_health(self) -> str:
        parts = (
            [t.health for t in self.temps]
            + [f.health for f in self.fans]
            + [p.health for p in self.psus]
            + [c.health for c in self.cpus]
            + [d.health for d in self.dimms]
            + [c.health for c in self.controllers]
            + [d.health for d in self.drives()]
            + [v.health for c in self.controllers for v in c.volumes]
            + [self.fan_redundancy_health(), self.psu_redundancy_health()]
        )
        return worst(parts)

    def component_health(self, kind: str) -> str:
        groups: dict[str, list[str]] = {
            "processors": [c.health for c in self.cpus],
            "memory": [d.health for d in self.dimms],
            "storage": [c.health for c in self.controllers]
            + [d.health for d in self.drives()]
            + [v.health for c in self.controllers for v in c.volumes],
            "thermal": [t.health for t in self.temps] + [f.health for f in self.fans],
            "power": [p.health for p in self.psus],
        }
        return worst(groups[kind])
