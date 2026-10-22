"""Server models and the initial state of each simulated server.

The fleet order (FLEET) is mirrored by backend/app/seed.py: simulated BMC i (1-based) runs
FLEET[(i - 1) % len(FLEET)]. Each model's `bios` / `bmc` versions are the approved baseline; a fixed
share of servers run an older BIOS so firmware compliance has something to show.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from gcc_redfish_sim.model import (
    Controller,
    Cpu,
    Dimm,
    Drive,
    Fan,
    FirmwareEntry,
    LogEntry,
    Nic,
    Psu,
    ServerState,
    Temp,
    Volume,
)

STATIC_EVENT_TIME = "2026-10-01T08:00:00+00:00"


@dataclass(frozen=True)
class ModelSpec:
    key: str
    profile: str
    model: str
    height_u: int
    bios: str
    bios_old: str
    bmc: str
    sku: str


MODELS: dict[str, ModelSpec] = {
    m.key: m
    for m in [
        ModelSpec("dell-r750", "dell", "PowerEdge R750", 2, "1.15.2", "1.13.2", "7.10.70.00", "R750"),
        ModelSpec("hpe-dl380-gen10", "hpe", "ProLiant DL380 Gen10", 2, "U30 v2.96 (06/24/2024)",
                  "U30 v2.80 (05/24/2023)", "3.08", "868703-B21"),
        ModelSpec("lenovo-sr650-v3", "lenovo", "ThinkSystem SR650 V3", 2, "ESE124B-3.10", "ESE118C-2.20",
                  "ESX320R-3.30", "7D76CTO1WW"),
        ModelSpec("dell-r650", "dell", "PowerEdge R650", 1, "1.15.2", "1.13.2", "7.10.70.00", "R650"),
        ModelSpec("hpe-dl360-gen10", "hpe", "ProLiant DL360 Gen10", 1, "U32 v2.96 (06/24/2024)",
                  "U32 v2.80 (05/24/2023)", "3.08", "867959-B21"),
        ModelSpec("lenovo-sr630-v3", "lenovo", "ThinkSystem SR630 V3", 1, "ESE124B-3.10", "ESE118C-2.20",
                  "ESX320R-3.30", "7D73CTO1WW"),
    ]
}

FLEET = ["dell-r750", "hpe-dl380-gen10", "lenovo-sr650-v3", "dell-r650", "hpe-dl360-gen10", "lenovo-sr630-v3"]

_OUI = {"dell": "D0:8E:79", "hpe": "94:40:C9", "lenovo": "08:94:EF"}


def model_for_index(index: int) -> ModelSpec:
    """Model of simulated BMC `index` (1-based)."""
    return MODELS[FLEET[(index - 1) % len(FLEET)]]


def _token(seed: str, length: int, alphabet: str = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") -> str:
    digest = hashlib.sha256(seed.encode()).digest()
    return "".join(alphabet[b % len(alphabet)] for b in digest[:length])


def _mac(profile: str, index: int, port: int) -> str:
    n = index * 16 + port
    return f"{_OUI[profile]}:{(n >> 16) & 0xFF:02X}:{(n >> 8) & 0xFF:02X}:{n & 0xFF:02X}"


def _ip(prefix: str, index: int) -> str:
    return f"{prefix}.{index // 200}.{index % 200 + 20}"


def _dimm_serial(rng: random.Random) -> str:
    return f"{rng.randrange(16**8):08X}"


# --------------------------------------------------------------------------------------------- Dell


def _dell(spec: ModelSpec, index: int, rng: random.Random) -> ServerState:
    one_u = spec.height_u == 1
    fan_count, max_rpm = (8, 25000.0) if one_u else (6, 17000.0)
    temps = [
        Temp("SystemBoardInletTemp", "System Board Inlet Temp", "Intake", 23.0, 42.0, 47.0, 23.0),
        Temp("SystemBoardExhaustTemp", "System Board Exhaust Temp", "Exhaust", 38.0, 70.0, 75.0, 38.0),
        Temp("CPU1Temp", "CPU1 Temp", "CPU", 55.0, 93.0, 98.0, 55.0),
        Temp("CPU2Temp", "CPU2 Temp", "CPU", 53.0, 93.0, 98.0, 53.0),
        Temp("DIMMA1Temp", "DIMM A1 Temp", "Memory", 38.0, 85.0, 90.0, 38.0),
        Temp("DIMMB1Temp", "DIMM B1 Temp", "Memory", 37.0, 85.0, 90.0, 37.0),
    ]
    fans = [
        Fan(f"Fan.Embedded.{n}A", f"System Board Fan{n}A", max_rpm * 0.4, max_rpm, 40.0, 960.0, 600.0)
        for n in range(1, fan_count + 1)
    ]
    psu_w = 800 if one_u else 1400
    psus = [
        Psu(f"PSU.Slot.{n}", f"PS{n} Status", n, f"PWR SPLY,{psu_w}W,RDNT,LTON", f"CNLOD00{_token(f'{index}psu{n}', 9)}",
            "00.1D.79", psu_w, 231.0, 230.0)
        for n in (1, 2)
    ]
    cpus = [Cpu(f"CPU.Socket.{n}", n, "Intel(R) Xeon(R) Gold 6338 CPU @ 2.00GHz", 32, 2000) for n in (1, 2)]
    dimms = [
        Dimm(f"DIMM.Socket.{bank}{slot}", f"DIMM.Socket.{bank}{slot}", 32768, "Hynix Semiconductor",
             "HMA84GR7DJR4N-XN", _dimm_serial(rng), 3200)
        for bank in "AB"
        for slot in range(1, 9)
    ]
    ctl_id = "RAID.SL.3-1"
    drive_count = 2 if one_u else 4
    drives = [
        Drive(f"Disk.Bay.{n}", n, f"Solid State Disk 0:1:{n}", "MZ7L3960HCJR0D3",
              f"S6{_token(f'{index}d{n}', 10)}", 960_197_124_096, "SSD", "SATA", "DSG8",
              float(rng.randint(80, 99)))
        for n in range(drive_count)
    ]
    volume = Volume(f"Disk.Virtual.0-{ctl_id}", "Virtual Disk 0", "RAID1" if one_u else "RAID10",
                    960_197_124_096 * drive_count // 2, [d.key for d in drives])
    controller = Controller(ctl_id, "PERC H755 Front", "PERC H755 Front", "52.26.0-5179", drives, [volume])
    nics = [
        Nic("NIC.Integrated.1-1-1", "Integrated NIC 1 Port 1 Partition 1", _mac("dell", index, 1), 25000, True,
            [_ip("10.30", index)]),
        Nic("NIC.Integrated.1-2-1", "Integrated NIC 1 Port 2 Partition 1", _mac("dell", index, 2), 25000, True),
        Nic("NIC.Slot.3-1-1", "NIC in Slot 3 Port 1 Partition 1", _mac("dell", index, 3), 10000, False),
        Nic("NIC.Slot.3-2-1", "NIC in Slot 3 Port 2 Partition 1", _mac("dell", index, 4), 10000, False),
    ]
    tag = _token(f"dell{index}", 7)
    firmware = [
        FirmwareEntry(f"Installed-25806-52.26.0-5179__{ctl_id}", "PERC H755 Front", "52.26.0-5179"),
        FirmwareEntry("Installed-108255-22.31.6__NIC.Integrated.1-1-1", "Broadcom Adv. Dual 25Gb Ethernet",
                      "22.31.6"),
        FirmwareEntry("Installed-104374-00.1D.79__PSU.Slot.1", "PWR SPLY,1400W,RDNT,LTON", "00.1D.79"),
        FirmwareEntry("Installed-27763-1.1.1__CPLD.Embedded.1", "System CPLD", "1.1.1"),
        FirmwareEntry("Previous-159-1.13.2__BIOS.Setup.1-1", "BIOS", spec.bios_old, updateable=False),
    ]
    sel = [
        LogEntry("1", STATIC_EVENT_TIME, "OK", "Log cleared.", "SEL9901"),
        LogEntry("2", STATIC_EVENT_TIME, "OK", "The system inventory was updated successfully.", "SYS1003"),
    ]
    return ServerState(
        profile="dell", model=spec.model, serial=f"CNIVC00{_token(f'dellsn{index}', 9)}", sku=tag,
        hostname=f"esx{index:03d}.gcc.local", uuid=str(uuid.UUID(int=rng.getrandbits(128))),
        asset_tag="", height_mm=43.0 if one_u else 86.8,
        bios_version=spec.bios_old if index % 5 == 2 else spec.bios, bmc_version=spec.bmc,
        bmc_mac=_mac("dell", index, 0), bmc_ip=_ip("10.20", index),
        temps=temps, fans=fans, psus=psus, power_w=320.0, power_capacity_w=psu_w,
        cpus=cpus, dimms=dimms, controllers=[controller], nics=nics, sel=sel, firmware_extra=firmware,
    )


# ---------------------------------------------------------------------------------------------- HPE


def _hpe(spec: ModelSpec, index: int, rng: random.Random) -> ServerState:
    one_u = spec.height_u == 1
    fan_count = 7 if one_u else 6
    temps = [
        Temp("01-Inlet Ambient", "01-Inlet Ambient", "Intake", 22.0, 42.0, 46.0, 22.0),
        Temp("02-CPU 1", "02-CPU 1", "CPU", 40.0, 70.0, None, 40.0),
        Temp("03-CPU 2", "03-CPU 2", "CPU", 40.0, 70.0, None, 40.0),
        Temp("04-P1 DIMM 1-6", "04-P1 DIMM 1-6", "Memory", 35.0, 90.0, None, 35.0),
        Temp("06-P2 DIMM 1-6", "06-P2 DIMM 1-6", "Memory", 35.0, 90.0, None, 35.0),
        Temp("14-Exhaust Sensor", "14-Exhaust Sensor", "Exhaust", 37.0, 65.0, 70.0, 37.0),
    ]
    fans = [Fan(f"Fan{n}", f"Fan {n}", 3200.0, 10000.0, 32.0, None, None) for n in range(1, fan_count + 1)]
    psus = [
        Psu(str(n - 1), "HpeServerPowerSupply", n, "865414-B21", f"5WBXK0{_token(f'{index}hpsu{n}', 8)}", "1.00",
            800, 230.0, 230.0)
        for n in (1, 2)
    ]
    cpus = [Cpu(str(n), n, "Intel(R) Xeon(R) Gold 6248R CPU @ 3.00GHz", 24, 3000) for n in (1, 2)]
    dimms = [
        Dimm(f"proc{p}dimm{s}", f"PROC {p} DIMM {s}", 32768, "HPE", "P00924-B21", _dimm_serial(rng), 2933)
        for p in (1, 2)
        for s in (1, 3, 5, 8, 10, 12)
    ]
    drive_count = 2 if one_u else 4
    drives = [
        Drive(str(n), n, f"Drive {n}", "VK000960GWSRT", f"S{_token(f'{index}hd{n}', 13)}", 960_197_124_096, "SSD",
              "SATA", "HPG4", float(rng.randint(80, 99)))
        for n in range(drive_count)
    ]
    volume = Volume("1", "Logical Drive 1", "RAID1" if one_u else "RAID5",
                    960_197_124_096 * (drive_count - 1) if not one_u else 960_197_124_096,
                    [d.key for d in drives])
    controller = Controller("DE00A000", "HPE Smart Array P408i-a SR Gen10", "HPE Smart Array P408i-a SR Gen10",
                            "7.43", drives, [volume])
    nics = [
        Nic(str(n), f"NIC {n}", _mac("hpe", index, n), 10000, n <= 2, [_ip("10.30", index)] if n == 1 else [])
        for n in range(1, 5)
    ]
    firmware = [
        FirmwareEntry("3", "Redundant System ROM", spec.bios_old, updateable=False),
        FirmwareEntry("4", "Intelligent Platform Abstraction Data", "13.2.0 Build 42"),
        FirmwareEntry("5", "Power Management Controller Firmware", "1.0.9"),
        FirmwareEntry("6", "Server Platform Services (SPS) Firmware", "4.1.4.804"),
        FirmwareEntry("7", "HPE Smart Array P408i-a SR Gen10", "7.43"),
        FirmwareEntry("8", "HPE Ethernet 10Gb 2-port 562FLR-SFP+ Adpt", "1.3016.0"),
        FirmwareEntry("9", "Power Supply Firmware", "1.00"),
    ]
    sel = [
        LogEntry("1", STATIC_EVENT_TIME, "OK", "IML Cleared (iLO 5 user:Administrator)", "IML.0.0.IMLCleared"),
        LogEntry("2", STATIC_EVENT_TIME, "OK", "Firmware flashed (System ROM)", "IML.0.0.FirmwareFlashed"),
    ]
    return ServerState(
        profile="hpe", model=spec.model, serial=f"CZJ{_token(f'hpesn{index}', 7)}", sku=spec.sku,
        hostname=f"esx{index:03d}.gcc.local", uuid=str(uuid.UUID(int=rng.getrandbits(128))),
        asset_tag="", height_mm=43.0 if one_u else 87.0,
        bios_version=spec.bios_old if index % 5 == 2 else spec.bios, bmc_version=spec.bmc,
        bmc_mac=_mac("hpe", index, 0), bmc_ip=_ip("10.20", index),
        temps=temps, fans=fans, psus=psus, power_w=280.0, power_capacity_w=800,
        cpus=cpus, dimms=dimms, controllers=[controller], nics=nics, sel=sel, firmware_extra=firmware,
    )


# ------------------------------------------------------------------------------------------- Lenovo


def _lenovo(spec: ModelSpec, index: int, rng: random.Random) -> ServerState:
    one_u = spec.height_u == 1
    fan_count, max_rpm = (8, 28000.0) if one_u else (6, 21000.0)
    temps = [
        Temp("Ambient_Temp", "Ambient Temp", "Intake", 23.0, 43.0, 47.0, 23.0),
        Temp("Exhaust_Temp", "Exhaust Temp", "Exhaust", 37.0, 70.0, 75.0, 37.0),
        Temp("CPU1_Temp", "CPU 1 Temp", "CPU", 50.0, 90.0, 95.0, 50.0),
        Temp("CPU2_Temp", "CPU 2 Temp", "CPU", 49.0, 90.0, 95.0, 49.0),
        Temp("DIMM1_Temp", "DIMM 1 Temp", "Memory", 36.0, 85.0, 90.0, 36.0),
        Temp("DIMM17_Temp", "DIMM 17 Temp", "Memory", 36.0, 85.0, 90.0, 36.0),
    ]
    fans = [
        Fan(f"Fan_{n}", f"Fan {n} Front Tach", max_rpm * 0.35, max_rpm, 35.0, 1000.0, 500.0)
        for n in range(1, fan_count + 1)
    ]
    psu_w = 750 if one_u else 1100
    psus = [
        Psu(str(n), f"Power Supply {n}", n, f"SP57A{_token(f'lpm{psu_w}', 5, '0123456789')}",
            f"D1DG{_token(f'{index}lpsu{n}', 8)}", "7.36", psu_w, 229.0, 230.0)
        for n in (1, 2)
    ]
    cpus = [Cpu(str(n), n, "Intel(R) Xeon(R) Gold 6430", 32, 2100) for n in (1, 2)]
    dimms = [
        Dimm(str(slot), f"DIMM {slot}", 65536, "Samsung", "M321R8GA0BB0-CQK", _dimm_serial(rng), 4400)
        for slot in (1, 3, 5, 7, 10, 12, 14, 16, 17, 19, 21, 23, 26, 28, 30, 32)
    ]
    drive_count = 2 if one_u else 4
    drives = [
        Drive(f"Disk.{n}", n, f"Drive {n}", "MZ7L3480HCHQ", f"S6K{_token(f'{index}ld{n}', 10)}", 480_103_981_056,
              "SSD", "SATA", "JXTC604Q", float(rng.randint(80, 99)))
        for n in range(drive_count)
    ]
    volume = Volume("Volume0", "Virtual Disk 0", "RAID1" if one_u else "RAID10",
                    480_103_981_056 * drive_count // 2, [d.key for d in drives])
    controller = Controller("RAID_Slot1", "RAID 940-8i", "ThinkSystem RAID 940-8i 4GB Flash PCIe Gen4 12Gb Adapter",
                            "52.24.0-4763", drives, [volume])
    nics = [
        Nic(f"NIC{n}", f"Broadcom 57414 Port {n}", _mac("lenovo", index, n), 25000, n <= 2,
            [_ip("10.30", index)] if n == 1 else [])
        for n in range(1, 5)
    ]
    firmware = [
        FirmwareEntry("BMC-Backup", "XCC Backup Firmware", "ESX316J-3.10", updateable=False),
        FirmwareEntry("LXPM", "LXPM Diagnostic Software", "EST312D-3.10"),
        FirmwareEntry("Slot_1.Bundle", "ThinkSystem RAID 940-8i", "52.24.0-4763"),
        FirmwareEntry("OCP.Bundle", "Broadcom 57414 10/25GbE SFP28 2-port OCP Ethernet Adapter", "229.1.123.0"),
        FirmwareEntry("PSU1", "Power Supply 1", "7.36"),
    ]
    sel = [
        LogEntry("1", STATIC_EVENT_TIME, "OK", "The event log was cleared.", "FQXSPEM4003I"),
        LogEntry("2", STATIC_EVENT_TIME, "OK", "System inventory collection completed.", "FQXSPSE4038I"),
    ]
    return ServerState(
        profile="lenovo", model=spec.model, serial=f"J30{_token(f'lensn{index}', 5)}", sku=spec.sku,
        hostname=f"esx{index:03d}.gcc.local", uuid=str(uuid.UUID(int=rng.getrandbits(128))),
        asset_tag="", height_mm=43.0 if one_u else 86.5,
        bios_version=spec.bios_old if index % 5 == 2 else spec.bios, bmc_version=spec.bmc,
        bmc_mac=_mac("lenovo", index, 0), bmc_ip=_ip("10.20", index),
        temps=temps, fans=fans, psus=psus, power_w=340.0, power_capacity_w=psu_w,
        cpus=cpus, dimms=dimms, controllers=[controller], nics=nics, sel=sel, firmware_extra=firmware,
    )


_FACTORIES: dict[str, Callable[[ModelSpec, int, random.Random], ServerState]] = {
    "dell": _dell,
    "hpe": _hpe,
    "lenovo": _lenovo,
}


def make_state(model_key: str, index: int) -> ServerState:
    """Initial state of simulated server `index` of the given model. Deterministic for (model, index)."""
    spec = MODELS[model_key]
    rng = random.Random(f"{model_key}-{index}")
    return _FACTORIES[spec.profile](spec, index, rng)
