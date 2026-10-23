"""Fault kinds: what each one changes on a server and the log entries a real BMC would write.

A fault is an overlay on top of the drifting physics: `overlay()` runs after the readings and threshold
health are written, so removing the fault and re-rendering restores the state exactly. Health rollups
(System/Chassis/ThermalSubsystem/PowerSubsystem/Storage `Status.HealthRollup`) follow automatically
because the tree builders compute them from component health.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from gcc_redfish_sim.model import CRITICAL, OK, WARNING, ServerState
from gcc_redfish_sim.simulator.physics import Effects, temp_health


class FaultKind(StrEnum):
    FAN_SLOW = "fan_slow"
    PSU_WARNING = "psu_warning"
    INLET_SPIKE = "inlet_spike"
    DRIVE_WEAR = "drive_wear"
    NIC_DOWN = "nic_down"
    CRITICAL_SEL = "critical_sel"
    BMC_UNRESPONSIVE = "bmc_unresponsive"
    POWER_OFF = "power_off"


# Relative frequency of random faults.
RANDOM_WEIGHTS: dict[FaultKind, int] = {
    FaultKind.FAN_SLOW: 3,
    FaultKind.PSU_WARNING: 2,
    FaultKind.INLET_SPIKE: 2,
    FaultKind.DRIVE_WEAR: 1,
    FaultKind.NIC_DOWN: 2,
    FaultKind.CRITICAL_SEL: 2,
    FaultKind.BMC_UNRESPONSIVE: 1,
    FaultKind.POWER_OFF: 1,
}

DRIVE_WEAR_LIFE_LEFT_PCT = 5.0
FAN_FAILED_PCT_OF_MAX = 5.0  # fans without RPM thresholds (HPE reports percent)
INLET_SPIKE_MIN_C = 37.5


@dataclass
class Fault:
    id: int
    bmc: int
    kind: FaultKind
    target: str | None  # component key the fault applies to
    value: float | None  # e.g. the spiked inlet temperature
    source: str  # "manual" | "random"
    started_at: datetime
    expires_at: datetime | None

    def to_json(self, port: int | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "bmc": self.bmc,
            "kind": str(self.kind),
            "target": self.target,
            "source": self.source,
            "started_at": self.started_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
        if port is not None:
            out["port"] = port
        return out


# ------------------------------------------------------------------------------------- targets


def choose_target(kind: FaultKind, state: ServerState, rng: random.Random) -> tuple[str | None, float | None]:
    """Pick the component a new fault applies to (and a value, for the inlet spike)."""
    match kind:
        case FaultKind.FAN_SLOW:
            return rng.choice(state.fans).key, None
        case FaultKind.PSU_WARNING:
            return rng.choice(state.psus).key, None
        case FaultKind.DRIVE_WEAR:
            return rng.choice(state.drives()).key, None
        case FaultKind.NIC_DOWN:
            # A link that is expected up (it was up at first sighting); the last one, so the host IP stays.
            up = [n for n in state.nics if n.link_up]
            return (up[-1] if up else state.nics[-1]).key, None
        case FaultKind.CRITICAL_SEL:
            return rng.choice(state.dimms).key, None
        case FaultKind.INLET_SPIKE:
            inlet = next(t for t in state.temps if t.context == "Intake")
            caution = inlet.upper_caution if inlet.upper_caution is not None else 40.0
            return inlet.key, round(max(INLET_SPIKE_MIN_C, caution + 1.5) + rng.uniform(0.0, 0.5), 1)
        case FaultKind.BMC_UNRESPONSIVE | FaultKind.POWER_OFF:
            return None, None


# ------------------------------------------------------------------------------- state effects


def effects(faults: list[Fault]) -> Effects:
    kinds = {f.kind for f in faults}
    spike = next((f.value for f in faults if f.kind == FaultKind.INLET_SPIKE), None)
    return Effects(
        host_off=FaultKind.POWER_OFF in kinds,
        inlet_override_c=spike,
        fan_boost_pct=15.0 if FaultKind.FAN_SLOW in kinds else 0.0,
    )


def overlay(fault: Fault, state: ServerState) -> None:
    """Apply the fault to the rendered state (after readings and threshold health are set)."""
    match fault.kind:
        case FaultKind.FAN_SLOW:
            fan = next(f for f in state.fans if f.key == fault.target)
            if fan.lower_critical is not None:
                fan.rpm = fan.lower_critical * 0.6
            else:
                fan.rpm = fan.max_rpm * FAN_FAILED_PCT_OF_MAX / 100.0
            fan.health = CRITICAL
        case FaultKind.PSU_WARNING:
            next(p for p in state.psus if p.key == fault.target).health = WARNING
        case FaultKind.INLET_SPIKE:
            inlet = next(t for t in state.temps if t.key == fault.target)
            inlet.reading = fault.value if fault.value is not None else INLET_SPIKE_MIN_C
            inlet.health = temp_health(inlet)
        case FaultKind.DRIVE_WEAR:
            drive = next(d for d in state.drives() if d.key == fault.target)
            drive.life_left_pct = DRIVE_WEAR_LIFE_LEFT_PCT
            drive.health = WARNING
        case FaultKind.NIC_DOWN:
            next(n for n in state.nics if n.key == fault.target).link_up = False
        case FaultKind.POWER_OFF:
            state.power_state = "Off"
        case FaultKind.CRITICAL_SEL | FaultKind.BMC_UNRESPONSIVE:
            pass


# -------------------------------------------------------------------------------- log entries


@dataclass(frozen=True)
class LogSpec:
    severity: str
    message_id: str
    template: str  # str.format fields: name, bay, value


# (raised, cleared) per vendor and kind; None = a real BMC writes nothing.
_LOGS: dict[str, dict[FaultKind, tuple[LogSpec | None, LogSpec | None]]] = {
    "dell": {
        FaultKind.FAN_SLOW: (
            LogSpec(CRITICAL, "FAN0002", "The fan {name} RPM is less than the lower critical threshold."),
            LogSpec(OK, "FAN0000", "The fan {name} RPM is within the normal operating range."),
        ),
        FaultKind.PSU_WARNING: (
            LogSpec(WARNING, "PSU0044", "The power supply {name} is operating at reduced efficiency."),
            LogSpec(OK, "PSU0001", "The power supply {name} has returned to normal."),
        ),
        FaultKind.INLET_SPIKE: (
            LogSpec(
                WARNING,
                "TMP0119",
                "The system inlet temperature is greater than the upper warning threshold.",
            ),
            LogSpec(OK, "TMP0122", "The system inlet temperature is within range."),
        ),
        FaultKind.DRIVE_WEAR: (
            LogSpec(
                WARNING,
                "PDR1024",
                "Physical disk {name} has reached the rated write endurance warning level.",
            ),
            None,
        ),
        FaultKind.NIC_DOWN: (
            LogSpec(WARNING, "NIC100", "The {name} network link is down."),
            LogSpec(OK, "NIC101", "The {name} network link is up."),
        ),
        FaultKind.CRITICAL_SEL: (
            LogSpec(
                CRITICAL,
                "MEM0001",
                "Multi-bit memory errors detected on a memory device at location(s) {name}.",
            ),
            None,
        ),
        FaultKind.POWER_OFF: (
            LogSpec(OK, "SYS1001", "System is turning off."),
            LogSpec(OK, "SYS1000", "System is turning on."),
        ),
        FaultKind.BMC_UNRESPONSIVE: (
            None,
            LogSpec(
                OK, "RAC0182", "The iDRAC firmware was rebooted with the following reason: watchdog timeout."
            ),
        ),
    },
    "hpe": {
        FaultKind.FAN_SLOW: (
            LogSpec(CRITICAL, "IML.0.0.FanFailure", "System Fan Failure ({name}, Location System)"),
            LogSpec(OK, "IML.0.0.FanRepaired", "System Fan Repaired ({name}, Location System)"),
        ),
        FaultKind.PSU_WARNING: (
            LogSpec(WARNING, "IML.0.0.PowerSupplyDegraded", "Power Supply Degraded (Power Supply {bay})"),
            LogSpec(OK, "IML.0.0.PowerSupplyRepaired", "Power Supply Repaired (Power Supply {bay})"),
        ),
        FaultKind.INLET_SPIKE: (
            LogSpec(
                WARNING,
                "IML.0.0.TemperatureCaution",
                "Temperature Caution (Temperature Sensor 1, Location Ambient, Temperature {value:.0f}C)",
            ),
            LogSpec(
                OK, "IML.0.0.TemperatureNormal", "Temperature Normal (Temperature Sensor 1, Location Ambient)"
            ),
        ),
        FaultKind.DRIVE_WEAR: (
            LogSpec(
                WARNING,
                "IML.0.0.DriveWearAlert",
                "Smart Storage Drive Wear Alert (Port 1I, Box 1, Bay {bay}): "
                "5% of rated write endurance remaining",
            ),
            None,
        ),
        FaultKind.NIC_DOWN: (
            LogSpec(WARNING, "IML.0.0.NetworkLinkDown", "Network Adapter Link Down ({name})"),
            LogSpec(OK, "IML.0.0.NetworkLinkUp", "Network Adapter Link Up ({name})"),
        ),
        FaultKind.CRITICAL_SEL: (
            LogSpec(CRITICAL, "IML.0.0.UncorrectableMemoryError", "Uncorrectable Memory Error ({name})"),
            None,
        ),
        FaultKind.POWER_OFF: (
            LogSpec(OK, "IML.0.0.ServerPowerOff", "Server Power Off"),
            LogSpec(OK, "IML.0.0.ServerPowerOn", "Server Power On"),
        ),
        FaultKind.BMC_UNRESPONSIVE: (
            None,
            LogSpec(OK, "IML.0.0.iLOReset", "iLO 5 was reset (watchdog timeout)"),
        ),
    },
    "lenovo": {
        FaultKind.FAN_SLOW: (
            LogSpec(
                CRITICAL, "FQXSPFN0011N", "Numeric sensor {name} going low (lower critical) has asserted."
            ),
            LogSpec(OK, "FQXSPFN2011I", "Numeric sensor {name} going low (lower critical) has deasserted."),
        ),
        FaultKind.PSU_WARNING: (
            LogSpec(
                WARNING, "FQXSPPW0057J", "Sensor {name} has transitioned from normal to non-critical state."
            ),
            LogSpec(OK, "FQXSPPW2057I", "Sensor {name} has deasserted the transition to non-critical state."),
        ),
        FaultKind.INLET_SPIKE: (
            LogSpec(
                WARNING, "FQXSPTH0007J", "Numeric sensor {name} going high (upper non-critical) has asserted."
            ),
            LogSpec(
                OK, "FQXSPTH2007I", "Numeric sensor {name} going high (upper non-critical) has deasserted."
            ),
        ),
        FaultKind.DRIVE_WEAR: (
            LogSpec(WARNING, "FQXSPSD0002G", "Failure Predicted on drive {name} in the enclosure/chassis."),
            None,
        ),
        FaultKind.NIC_DOWN: (
            LogSpec(WARNING, "FQXSPNM4011W", "Ethernet link down on {name}."),
            LogSpec(OK, "FQXSPNM4012I", "Ethernet link up on {name}."),
        ),
        FaultKind.CRITICAL_SEL: (
            LogSpec(CRITICAL, "FQXSPMA0002N", "Uncorrectable error detected for {name} on Subsystem Memory."),
            None,
        ),
        FaultKind.POWER_OFF: (
            LogSpec(OK, "FQXSPPW0004I", "Host power has been turned off."),
            LogSpec(OK, "FQXSPPW0003I", "Host power has been turned on."),
        ),
        FaultKind.BMC_UNRESPONSIVE: (
            None,
            LogSpec(OK, "FQXSPBR4004I", "Management Controller was reset (watchdog timeout)."),
        ),
    },
}


def _target_fields(fault: Fault, state: ServerState) -> dict[str, Any]:
    name, bay = "", 0
    key = fault.target
    match fault.kind:
        case FaultKind.FAN_SLOW:
            fan = next(f for f in state.fans if f.key == key)
            name = fan.name
        case FaultKind.PSU_WARNING:
            psu = next(p for p in state.psus if p.key == key)
            bay = psu.bay
            name = f"PS{psu.bay}" if state.profile == "dell" else f"Power Supply {psu.bay}"
        case FaultKind.INLET_SPIKE:
            name = next(t for t in state.temps if t.key == key).name
        case FaultKind.DRIVE_WEAR:
            drive = next(d for d in state.drives() if d.key == key)
            name, bay = drive.name, drive.bay
        case FaultKind.NIC_DOWN:
            name = next(n for n in state.nics if n.key == key).name
        case FaultKind.CRITICAL_SEL:
            dimm = next(d for d in state.dimms if d.key == key)
            name = dimm.locator.removeprefix("DIMM.Socket.") if state.profile == "dell" else dimm.locator
        case FaultKind.BMC_UNRESPONSIVE | FaultKind.POWER_OFF:
            pass
    return {"name": name, "bay": bay, "value": fault.value or 0.0}


def log_entry(fault: Fault, state: ServerState, *, cleared: bool) -> tuple[str, str, str] | None:
    """(severity, message_id, message) a real BMC would log when the fault is raised or cleared."""
    spec = _LOGS[state.profile][fault.kind][1 if cleared else 0]
    if spec is None:
        return None
    return spec.severity, spec.message_id, spec.template.format(**_target_fields(fault, state))
