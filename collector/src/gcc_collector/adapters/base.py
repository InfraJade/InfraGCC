"""Vendor adapter base: turns Redfish resources into contract readings, limits, events and inventory.

Every vendor shares the walk (it is all standard Redfish); subclasses only supply naming tables and a few
hooks (sensor names -> metric codes, part names per D13, which logs and firmware entries count).

Sensor layouts: the newer ``Sensors`` / ``ThermalSubsystem`` / ``PowerSubsystem`` / ``EnvironmentMetrics``
resources are preferred. The legacy ``Thermal`` / ``Power`` resources are read only when the newer layout
is absent or leaves a whole group (temperatures, fans, power) empty. Readings are keyed by
``(metric, component)`` and the first source wins, so a BMC that exposes both layouts (Dell) never
produces duplicates.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

from gcc_collector.redfish.client import (
    AuthError,
    InvalidResponse,
    Json,
    NotFound,
    RedfishClient,
    RedfishHTTPError,
)
from gcc_collector.redfish.discovery import BmcMap, ChassisMap, LogServiceRef, link, links
from gcc_collector.schema import (
    BmcLimit,
    Component,
    Event,
    Firmware,
    FirmwareType,
    Identity,
    Reading,
)

log = logging.getLogger("gcc.collector.adapters")

PollKind = Literal["sensors", "health", "inventory"]
ALL_KINDS: frozenset[PollKind] = frozenset({"sensors", "health", "inventory"})

HEALTH_VALUES: dict[str, int] = {"OK": 0, "Warning": 1, "Critical": 2}
TEMP_METRICS = ("inlet_temp_c", "exhaust_temp_c", "cpu_temp_c", "dimm_temp_c")
FAN_SPEED_METRICS = ("fan_rpm", "fan_pct")
SKIP_STATES = frozenset({"Absent", "Disabled", "UnavailableOffline"})
MAX_EVENT_FETCHES = 50  # per log per poll when entries are links (the rest come next poll)
TempRule = tuple[re.Pattern[str], str, str]


# ------------------------------------------------------------------------------------------ helpers


def num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def text(value: Any) -> str | None:
    if value is None or isinstance(value, dict | list):
        return None
    out = str(value).strip()
    return out or None


def health_of(resource: Json | None, *, rollup: bool = False) -> str | None:
    if not isinstance(resource, dict):
        return None
    status = resource.get("Status")
    if not isinstance(status, dict):
        return None
    value = status.get("HealthRollup") if rollup else None
    value = value or status.get("Health")
    return value if isinstance(value, str) else None


def state_of(resource: Json | None) -> str | None:
    if not isinstance(resource, dict):
        return None
    status = resource.get("Status")
    value = status.get("State") if isinstance(status, dict) else None
    return value if isinstance(value, str) else None


def is_absent(resource: Json) -> bool:
    return state_of(resource) == "Absent"


def gauge_status(resource: Json | None) -> str | None:
    health = health_of(resource)
    return health if health in HEALTH_VALUES else None


def first_int(*values: Any) -> int | None:
    for value in values:
        if value is None:
            continue
        match = re.search(r"\d+", str(value))
        if match:
            return int(match.group())
    return None


def dig(resource: Any, *keys: str) -> Any:
    node = resource
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def parse_time(value: Any) -> datetime | None:
    raw = text(value)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_mac(value: Any) -> str | None:
    raw = text(value)
    if raw is None:
        return None
    hexdigits = re.sub(r"[^0-9A-Fa-f]", "", raw)
    if len(hexdigits) != 12 or set(hexdigits) == {"0"}:
        return None
    return ":".join(hexdigits[i : i + 2] for i in range(0, 12, 2)).upper()


def normalize_manufacturer(value: Any) -> str | None:
    raw = text(value)
    if raw is None:
        return None
    lower = raw.lower()
    for needle, name in (("intel", "Intel"), ("advanced micro", "AMD"), ("amd", "AMD"), ("ampere", "Ampere")):
        if needle in lower:
            return name
    return raw


def severity_of(value: Any) -> Literal["OK", "Warning", "Critical"]:
    if value == "Critical":
        return "Critical"
    if value == "Warning":
        return "Warning"
    return "OK"


# ------------------------------------------------------------------------------------- collected data


class Collected:
    """Readings and limits of one poll, de-duplicated by (metric, component); the first source wins."""

    def __init__(self, now: datetime) -> None:
        self.now = now
        self._readings: dict[tuple[str, str], Reading] = {}
        self.limits: dict[tuple[str, str], BmcLimit] = {}

    @property
    def readings(self) -> list[Reading]:
        return list(self._readings.values())

    def has(self, *metrics: str) -> bool:
        return any(key[0] in metrics for key in self._readings)

    def _put(self, metric: str, component: str, value: float | int | None, status: str | None) -> None:
        key = (metric, component)
        if key in self._readings:
            return
        self._readings[key] = Reading.model_validate(
            {"time": self.now, "metric": metric, "component": component, "value": value, "status": status}
        )

    def gauge(self, metric: str, component: str, value: Any, status: str | None = None) -> None:
        number = num(value)
        if number is None:
            return
        self._put(metric, component, round(number, 2), status if status in HEALTH_VALUES else None)

    def state(self, metric: str, component: str, health: str | None) -> None:
        if health in HEALTH_VALUES:
            self._put(metric, component, HEALTH_VALUES[health], health)
        else:
            self._put(metric, component, None, "Unknown")

    def power_state(self, raw: Any) -> None:
        value = text(raw)
        if value is None:
            return
        self._put("power_state", "", 1 if value == "On" else 0, value)

    def nic_link(self, component: str, raw: Any) -> None:
        value = text(raw)
        if value is None:
            return
        up = value in ("LinkUp", "Up")
        self._put("nic_link", component, 1 if up else 0, "Up" if up else "Down")

    def bmc_reachable(self, reachable: bool) -> None:
        self._put("bmc_reachable", "", 1 if reachable else 0, "Reachable" if reachable else "Unreachable")

    def limit(
        self,
        metric: str,
        component: str,
        *,
        lower_critical: Any = None,
        lower_warning: Any = None,
        upper_warning: Any = None,
        upper_critical: Any = None,
    ) -> None:
        values = {
            "lower_critical": num(lower_critical),
            "lower_warning": num(lower_warning),
            "upper_warning": num(upper_warning),
            "upper_critical": num(upper_critical),
        }
        if all(v is None for v in values.values()) or (metric, component) in self.limits:
            return
        self.limits[(metric, component)] = BmcLimit.model_validate(
            {"metric": metric, "component": component, **values}
        )


@dataclass
class ServerState:
    """What an adapter remembers about one server between polls."""

    seen_events: dict[str, set[str]] = field(default_factory=dict)
    limits: dict[tuple[str, str], BmcLimit] = field(default_factory=dict)


@dataclass
class PollOutput:
    readings: list[Reading] = field(default_factory=list)
    bmc_limits: list[BmcLimit] | None = None
    events: list[Event] | None = None
    identity: Identity | None = None
    components: list[Component] | None = None
    firmware: list[Firmware] | None = None
    soft_errors: list[str] = field(default_factory=list)


class PollContext:
    """One poll of one BMC: memoises GETs so health and inventory share responses."""

    def __init__(self, client: RedfishClient, bmc: BmcMap, now: datetime, *, strict_404: bool = True) -> None:
        self.client = client
        self.bmc = bmc
        self.now = now
        self.strict_404 = strict_404
        self.soft_errors: list[str] = []
        self._docs: dict[str, Json] = {}
        self._colls: dict[str, list[Json]] = {}

    async def get(self, path: str) -> Json:
        if path not in self._docs:
            self._docs[path] = await self.client.get(path)
        return self._docs[path]

    async def members(self, path: str | None) -> list[Json]:
        if path is None:
            return []
        if path not in self._colls:
            self._colls[path] = await self.client.get_collection(path)
        return self._colls[path]

    @contextmanager
    def soft(self, what: str) -> Iterator[None]:
        """Skip one section when the BMC errors on it; transport and auth failures still fail the poll."""
        try:
            yield
        except AuthError:
            raise
        except NotFound as exc:
            if self.strict_404:
                raise
            self.soft_errors.append(f"{what}: {exc}")
            log.info("%s: %s missing (%s)", self.client.bmc_host, what, exc)
        except (RedfishHTTPError, InvalidResponse) as exc:
            self.soft_errors.append(f"{what}: {exc}")
            log.info("%s: skipping %s (%s)", self.client.bmc_host, what, exc)


# -------------------------------------------------------------------------------------------- adapter


class VendorAdapter:
    """Standard-Redfish behaviour. Vendors override the class attributes and hooks below."""

    vendor: ClassVar[str] = "Generic"
    # (pattern on the sensor name, metric, component template using the match groups).
    TEMP_RULES: ClassVar[list[TempRule]] = []
    FAN_NAME = re.compile(r"Fan[\s_.\-]*(\d+)", re.IGNORECASE)
    PSU_NAME = re.compile(r"(?:PSU|PS|Power Supply)[\s_.\-]*(?:Slot[\s_.\-]*)?(\d+)", re.IGNORECASE)
    INCLUDE_LOGS: ClassVar[tuple[str, ...]] = ()  # LogService Ids to read; empty = default rule
    EXCLUDE_LOG_WORDS: ClassVar[tuple[str, ...]] = ("audit", "lifecycle", "lclog", "security")

    def __init__(self, manufacturer: str | None = None) -> None:
        self.manufacturer = manufacturer

    @property
    def vendor_name(self) -> str:
        return self.vendor

    # ------------------------------------------------------------------------------ naming hooks
    def classify_temperature(self, name: str, context: str | None) -> tuple[str, str] | None:
        for pattern, metric, template in self.TEMP_RULES:
            match = pattern.search(name)
            if match:
                return metric, template.format(*match.groups())
        return self._generic_temperature(name, context)

    @staticmethod
    def _generic_temperature(name: str, context: str | None) -> tuple[str, str] | None:
        lower = name.lower()
        ctx = (context or "").lower()
        cleaned = re.sub(r"^\d+-", "", name).removesuffix(" Temp").strip()
        if ctx in ("intake", "room") or (not ctx and ("inlet" in lower or "ambient" in lower)):
            return "inlet_temp_c", ""
        if ctx == "exhaust" or (not ctx and ("exhaust" in lower or "outlet" in lower)):
            return "exhaust_temp_c", ""
        if ctx == "cpu" or (not ctx and re.search(r"\bcpu|\bproc", lower)):
            n = first_int(cleaned)
            return "cpu_temp_c", f"CPU{n}" if n is not None else "CPU"
        if ctx == "memory":
            return "dimm_temp_c", cleaned
        return None

    def fan_name(self, name: str | None, member_id: str | None, index: int) -> str:
        for candidate in (name, member_id):
            if candidate:
                match = self.FAN_NAME.search(candidate)
                if match:
                    return f"Fan {int(match.group(1))}"
        return name or member_id or f"Fan {index + 1}"

    def psu_name(self, psu: Json, index: int) -> str:
        bay = dig(psu, "Location", "PartLocation", "LocationOrdinalValue")
        if isinstance(bay, int) and not isinstance(bay, bool):
            return f"PSU {bay}"
        label = text(dig(psu, "Location", "PartLocation", "ServiceLabel"))
        for candidate in (label, text(psu.get("MemberId")), text(psu.get("Id")), text(psu.get("Name"))):
            if candidate:
                match = self.PSU_NAME.search(candidate)
                if match:
                    return f"PSU {int(match.group(1))}"
        return f"PSU {index + 1}"

    def psu_name_from_sensor(self, name: str) -> str | None:
        match = self.PSU_NAME.search(name)
        return f"PSU {int(match.group(1))}" if match else None

    def cpu_name(self, cpu: Json, index: int) -> str:
        n = first_int(text(cpu.get("Socket")), text(cpu.get("Id")))
        return f"CPU{n if n is not None else index + 1}"

    def dimm_name(self, dimm: Json, index: int) -> str:
        locator = text(dimm.get("DeviceLocator")) or text(dimm.get("Name")) or text(dimm.get("Id"))
        return locator or f"DIMM {index + 1}"

    def drive_name(self, drive: Json, index: int) -> str:
        bay = dig(drive, "PhysicalLocation", "PartLocation", "LocationOrdinalValue")
        if not isinstance(bay, int) or isinstance(bay, bool):
            drive_id = text(drive.get("Id")) or ""
            match = re.search(r"Bay\.?(\d+)", drive_id)
            bay = int(match.group(1)) if match else first_int(drive_id)
        return f"Disk {bay if bay is not None else index}"

    def volume_name(self, volume: Json, index: int) -> str:
        volume_id = text(volume.get("Id")) or ""
        match = re.search(r"Virtual\.(\d+)", volume_id)
        n = int(match.group(1)) if match else first_int(volume_id)
        return f"Volume {n if n is not None else index}"

    def controller_name(self, storage: Json) -> str:
        return text(storage.get("Id")) or text(storage.get("Name")) or "Storage"

    def nic_names(self, nics: list[Json]) -> list[str]:
        """``NIC <n>``: the number in the Id (``1``, ``NIC1``) when every Id has one, else position by Id."""
        numbers = []
        for nic in nics:
            match = re.fullmatch(r"(?:NIC)?\s*(\d+)", text(nic.get("Id")) or "", re.IGNORECASE)
            numbers.append(int(match.group(1)) if match else None)
        if all(n is not None for n in numbers) and len(set(numbers)) == len(numbers):
            return [f"NIC {n}" for n in numbers]
        order = sorted(range(len(nics)), key=lambda i: text(nics[i].get("Id")) or "")
        names = [""] * len(nics)
        for pos, i in enumerate(order, start=1):
            names[i] = f"NIC {pos}"
        return names

    def bmc_model(self, manager: Json | None, root: Json) -> str | None:
        return text(dig(manager, "Model")) or text(root.get("Product"))

    def include_log(self, ref: LogServiceRef) -> bool:
        if self.INCLUDE_LOGS:
            return ref.id in self.INCLUDE_LOGS
        label = f"{ref.id} {ref.name}".lower()
        return not any(word in label for word in self.EXCLUDE_LOG_WORDS)

    def firmware_active(self, entry: Json) -> bool:
        entry_id = text(entry.get("Id")) or ""
        if entry_id.lower().startswith(("previous", "available", "pending")):
            return False
        return state_of(entry) not in ("StandbySpare", "StandbyOffline", "Disabled")

    def firmware_kind(self, name: str, entry_id: str) -> tuple[str, FirmwareType]:
        label = f"{name} {entry_id}".lower()
        rules: list[tuple[str, str, FirmwareType]] = [
            (
                r"idrac|remote access controller|\bilo\b|\bxcc\b|xclarity|\bbmc\b|baseboard management",
                "BMC",
                "bmc",
            ),
            (r"\bbios\b|system rom|\buefi\b", "BIOS", "bios"),
            (r"\bcpld\b", "CPLD", "cpld"),
            (r"power supply|pwr sply|\bpsu", "PSU", "psu"),
            (r"raid|\bperc\b|smart array|storage controller|\bhba\b|\bboss\b", "RAID", "storage_controller"),
            (r"ethernet|\bnic\b|network|connectx|\b\d+\s?gbe?\b", "NIC", "nic"),
            (r"\bdisk\b|\bdrive\b|\bssd\b|\bhdd\b", "DRIVE", "drive"),
        ]
        for pattern, key, kind in rules:
            if re.search(pattern, label):
                return key, kind
        return name, "other"

    def identity_serial(self, system: Json) -> str | None:
        return text(system.get("SerialNumber"))

    # ----------------------------------------------------------------------------------- polling
    async def poll(self, ctx: PollContext, state: ServerState, kinds: frozenset[PollKind]) -> PollOutput:
        out = PollOutput()
        col = Collected(ctx.now)
        if "sensors" in kinds:
            await self.collect_sensors(ctx, col)
            state.limits.update(col.limits)
        if "health" in kinds:
            await self.collect_health(ctx, col)
            out.events = await self.collect_events(ctx, state)
        if "health" in kinds or "inventory" in kinds:
            state.limits.update(col.limits)
            out.bmc_limits = list(state.limits.values()) or None
        if "inventory" in kinds:
            out.identity = await self.collect_identity(ctx)
            out.components = await self.collect_components(ctx)
            out.firmware = await self.collect_firmware(ctx)
        col.bmc_reachable(True)
        out.readings = col.readings
        out.soft_errors = ctx.soft_errors
        return out

    # ----------------------------------------------------------------------- 60 s: sensor readings
    async def collect_sensors(self, ctx: PollContext, col: Collected) -> None:
        system = await ctx.get(ctx.bmc.system_path)
        col.power_state(system.get("PowerState"))
        col.state("system_health", "", health_of(system, rollup=True))
        if ctx.bmc.manager_path is not None:
            with ctx.soft("manager"):
                col.state("bmc_health", "", health_of(await ctx.get(ctx.bmc.manager_path)))
        for chassis in ctx.bmc.chassis:
            await self._chassis_sensors(ctx, col, chassis)

    async def _chassis_sensors(self, ctx: PollContext, col: Collected, ch: ChassisMap) -> None:
        if ch.sensors is not None:
            with ctx.soft("sensors"):
                for sensor in await ctx.members(ch.sensors):
                    self._sensor(col, sensor)
        if ch.thermal_subsystem is not None and not (col.has(*TEMP_METRICS) and col.has(*FAN_SPEED_METRICS)):
            with ctx.soft("thermal subsystem"):
                ts = await ctx.get(ch.thermal_subsystem)
                metrics_path = link(ts, "ThermalMetrics")
                if metrics_path is not None and not col.has(*TEMP_METRICS):
                    self._thermal_metrics(col, await ctx.get(metrics_path))
                if not col.has(*FAN_SPEED_METRICS):
                    for i, fan in enumerate(await ctx.members(link(ts, "Fans"))):
                        self._fan_speed_new(col, fan, i)
        if ch.environment_metrics is not None and not col.has("power_w"):
            with ctx.soft("environment metrics"):
                env = await ctx.get(ch.environment_metrics)
                col.gauge("power_w", "", dig(env, "PowerWatts", "Reading"))
        if ch.power_subsystem is not None and not col.has("psu_input_v"):
            with ctx.soft("power supply metrics"):
                ps = await ctx.get(ch.power_subsystem)
                for i, psu in enumerate(await ctx.members(link(ps, "PowerSupplies"))):
                    metrics_path = link(psu, "Metrics")
                    if metrics_path is None or is_absent(psu):
                        continue
                    metrics = await ctx.get(metrics_path)
                    col.gauge(
                        "psu_input_v",
                        self.psu_name(psu, i),
                        dig(metrics, "InputVoltage", "Reading"),
                        gauge_status(metrics) or gauge_status(psu),
                    )
        # Legacy layout: only for groups the newer layout did not cover.
        if ch.thermal is not None and not (col.has(*TEMP_METRICS) and col.has(*FAN_SPEED_METRICS)):
            with ctx.soft("thermal"):
                self._legacy_thermal_sensors(col, await ctx.get(ch.thermal))
        if ch.power is not None and not (col.has("power_w") and col.has("psu_input_v")):
            with ctx.soft("power"):
                self._legacy_power_sensors(col, await ctx.get(ch.power))

    def _sensor(self, col: Collected, sensor: Json) -> None:
        if state_of(sensor) in SKIP_STATES:
            return
        name = text(sensor.get("Name")) or text(sensor.get("Id")) or ""
        kind = text(sensor.get("ReadingType")) or ""
        units = text(sensor.get("ReadingUnits")) or ""
        context = text(sensor.get("PhysicalContext"))
        reading = sensor.get("Reading")
        status = gauge_status(sensor)
        th = sensor.get("Thresholds") if isinstance(sensor.get("Thresholds"), dict) else {}
        limits = {
            "lower_critical": dig(th, "LowerCritical", "Reading"),
            "lower_warning": dig(th, "LowerCaution", "Reading"),
            "upper_warning": dig(th, "UpperCaution", "Reading"),
            "upper_critical": dig(th, "UpperCritical", "Reading"),
        }
        target: tuple[str, str] | None = None
        if kind == "Temperature" or units == "Cel":
            target = self.classify_temperature(name, context)
        elif kind == "Rotational" or units == "RPM":
            target = ("fan_rpm", self.fan_name(name, text(sensor.get("Id")), 0))
        elif kind == "Percent" and context == "Fan":
            target = ("fan_pct", self.fan_name(name, text(sensor.get("Id")), 0))
        elif kind == "Power" or units == "W":
            if context in (None, "Chassis", "SystemBoard", "Rack") or re.search(
                r"system power|total power|power consumption|pwr consumption", name, re.IGNORECASE
            ):
                target = ("power_w", "")
        elif kind == "Voltage" or units == "V":
            psu = self.psu_name_from_sensor(name)
            if psu is not None and (context in (None, "PowerSupply") or "input" in name.lower()):
                target = ("psu_input_v", psu)
        if target is None:
            return
        col.gauge(target[0], target[1], reading, status)
        col.limit(target[0], target[1], **limits)

    def _thermal_metrics(self, col: Collected, metrics: Json) -> None:
        for item in metrics.get("TemperatureReadingsCelsius") or []:
            if not isinstance(item, dict):
                continue
            name = text(item.get("DeviceName")) or ""
            target = self.classify_temperature(name, text(item.get("PhysicalContext")))
            if target is not None:
                col.gauge(target[0], target[1], item.get("Reading"))
        summary = metrics.get("TemperatureSummaryCelsius")
        if isinstance(summary, dict):
            col.gauge("inlet_temp_c", "", dig(summary, "Intake", "Reading"))
            col.gauge("exhaust_temp_c", "", dig(summary, "Exhaust", "Reading"))

    def _fan_speed_new(self, col: Collected, fan: Json, index: int) -> None:
        if state_of(fan) in SKIP_STATES:
            return
        name = self.fan_name(text(fan.get("Name")), text(fan.get("Id")), index)
        status = gauge_status(fan)
        rpm = dig(fan, "SpeedPercent", "SpeedRPM")
        if num(rpm) is not None:
            col.gauge("fan_rpm", name, rpm, status)
        else:
            col.gauge("fan_pct", name, dig(fan, "SpeedPercent", "Reading"), status)

    def _legacy_thermal_sensors(self, col: Collected, thermal: Json) -> None:
        for t in thermal.get("Temperatures") or []:
            if not isinstance(t, dict) or state_of(t) in SKIP_STATES:
                continue
            name = text(t.get("Name")) or text(t.get("MemberId")) or ""
            target = self.classify_temperature(name, text(t.get("PhysicalContext")))
            if target is None:
                continue
            col.gauge(target[0], target[1], t.get("ReadingCelsius"), gauge_status(t))
            col.limit(
                target[0],
                target[1],
                lower_critical=t.get("LowerThresholdCritical"),
                lower_warning=t.get("LowerThresholdNonCritical"),
                upper_warning=t.get("UpperThresholdNonCritical"),
                upper_critical=t.get("UpperThresholdCritical"),
            )
        for i, f in enumerate(thermal.get("Fans") or []):
            if not isinstance(f, dict) or state_of(f) in SKIP_STATES:
                continue
            name = self.fan_name(text(f.get("Name")) or text(f.get("FanName")), text(f.get("MemberId")), i)
            units = text(f.get("ReadingUnits")) or "RPM"
            metric = "fan_pct" if units.lower() in ("percent", "%") else "fan_rpm"
            col.gauge(metric, name, f.get("Reading"), gauge_status(f))
            col.limit(
                metric,
                name,
                lower_critical=f.get("LowerThresholdCritical"),
                lower_warning=f.get("LowerThresholdNonCritical"),
                upper_warning=f.get("UpperThresholdNonCritical"),
                upper_critical=f.get("UpperThresholdCritical"),
            )

    def _legacy_power_sensors(self, col: Collected, power: Json) -> None:
        controls = [c for c in power.get("PowerControl") or [] if isinstance(c, dict)]
        if controls:
            col.gauge("power_w", "", controls[0].get("PowerConsumedWatts"))
        for i, psu in enumerate(power.get("PowerSupplies") or []):
            if not isinstance(psu, dict) or state_of(psu) in SKIP_STATES:
                continue
            col.gauge("psu_input_v", self.psu_name(psu, i), psu.get("LineInputVoltage"), gauge_status(psu))

    # ------------------------------------------------------------------------- 5 min: health
    async def collect_health(self, ctx: PollContext, col: Collected) -> None:
        with ctx.soft("fans"):
            for name, fan in await self.fans(ctx):
                col.state("fan_health", name, health_of(fan))
        with ctx.soft("fan redundancy"):
            healths = await self._redundancy(ctx, "thermal")
            if healths:
                col.state("fan_redundancy", "", _worst(healths))
        with ctx.soft("power supplies"):
            for name, psu in await self.psus(ctx):
                col.state("psu_health", name, health_of(psu))
        with ctx.soft("power redundancy"):
            healths = await self._redundancy(ctx, "power")
            if healths:
                col.state("psu_redundancy", "", _worst(healths))
        with ctx.soft("power capacity"):
            await self._power_budget(ctx, col)
        with ctx.soft("processors"):
            for name, cpu in await self.cpus(ctx):
                col.state("cpu_health", name, health_of(cpu))
        with ctx.soft("memory"):
            for name, dimm in await self.dimms(ctx):
                col.state("memory_health", name, health_of(dimm))
        with ctx.soft("storage"):
            for ctl in await self.storage(ctx):
                col.state("storage_health", ctl.name, ctl.health)
                for name, drive in ctl.drives:
                    col.state("drive_health", name, health_of(drive))
                    col.gauge("drive_life_pct", name, drive.get("PredictedMediaLifeLeftPercent"))
                for name, volume in ctl.volumes:
                    col.state("volume_health", name, health_of(volume))
        with ctx.soft("network"):
            for name, nic in await self.nics(ctx):
                col.nic_link(name, nic.get("LinkStatus"))

    async def _redundancy(self, ctx: PollContext, kind: Literal["thermal", "power"]) -> list[str | None]:
        healths: list[str | None] = []
        for ch in ctx.bmc.chassis:
            sub = ch.thermal_subsystem if kind == "thermal" else ch.power_subsystem
            key = "FanRedundancy" if kind == "thermal" else "PowerSupplyRedundancy"
            legacy = ch.thermal if kind == "thermal" else ch.power
            if sub is not None:
                for group in (await ctx.get(sub)).get(key) or []:
                    if isinstance(group, dict):
                        healths.append(health_of(group))
            elif legacy is not None:
                for group in (await ctx.get(legacy)).get("Redundancy") or []:
                    if isinstance(group, dict) and state_of(group) not in SKIP_STATES:
                        healths.append(health_of(group))
        return healths

    async def _power_budget(self, ctx: PollContext, col: Collected) -> None:
        for ch in ctx.bmc.chassis:
            if ch.power_subsystem is not None:
                ps = await ctx.get(ch.power_subsystem)
                col.gauge("power_capacity_w", "", ps.get("CapacityWatts"))
            if ch.environment_metrics is not None:
                env = await ctx.get(ch.environment_metrics)
                if dig(env, "PowerLimitWatts", "ControlMode") != "Disabled":
                    col.gauge("power_limit_w", "", dig(env, "PowerLimitWatts", "SetPoint"))
            if ch.power is not None and not (ch.power_subsystem or ch.environment_metrics):
                power = await ctx.get(ch.power)
                controls = [c for c in power.get("PowerControl") or [] if isinstance(c, dict)]
                if controls:
                    col.gauge("power_capacity_w", "", controls[0].get("PowerCapacityWatts"))
                    col.gauge("power_limit_w", "", dig(controls[0], "PowerLimit", "LimitInWatts"))

    # ------------------------------------------------------------------------------- parts lists
    async def fans(self, ctx: PollContext) -> list[tuple[str, Json]]:
        out: list[tuple[str, Json]] = []
        for ch in ctx.bmc.chassis:
            if ch.thermal_subsystem is not None:
                ts = await ctx.get(ch.thermal_subsystem)
                for i, fan in enumerate(await ctx.members(link(ts, "Fans"))):
                    if not is_absent(fan):
                        out.append((self.fan_name(text(fan.get("Name")), text(fan.get("Id")), i), fan))
            elif ch.thermal is not None:
                for i, fan in enumerate((await ctx.get(ch.thermal)).get("Fans") or []):
                    if isinstance(fan, dict) and not is_absent(fan):
                        name = text(fan.get("Name")) or text(fan.get("FanName"))
                        out.append((self.fan_name(name, text(fan.get("MemberId")), i), fan))
        return _unique(out)

    async def psus(self, ctx: PollContext) -> list[tuple[str, Json]]:
        out: list[tuple[str, Json]] = []
        for ch in ctx.bmc.chassis:
            if ch.power_subsystem is not None:
                ps = await ctx.get(ch.power_subsystem)
                for i, psu in enumerate(await ctx.members(link(ps, "PowerSupplies"))):
                    if not is_absent(psu):
                        out.append((self.psu_name(psu, i), psu))
            elif ch.power is not None:
                for i, psu in enumerate((await ctx.get(ch.power)).get("PowerSupplies") or []):
                    if isinstance(psu, dict) and not is_absent(psu):
                        out.append((self.psu_name(psu, i), psu))
        return _unique(out)

    async def cpus(self, ctx: PollContext) -> list[tuple[str, Json]]:
        procs = [
            p
            for p in await ctx.members(ctx.bmc.processors)
            if not is_absent(p) and (text(p.get("ProcessorType")) or "CPU") == "CPU"
        ]
        return _unique([(self.cpu_name(p, i), p) for i, p in enumerate(procs)])

    async def dimms(self, ctx: PollContext) -> list[tuple[str, Json]]:
        mems = [m for m in await ctx.members(ctx.bmc.memory) if not is_absent(m)]
        return _unique([(self.dimm_name(m, i), m) for i, m in enumerate(mems)])

    async def nics(self, ctx: PollContext) -> list[tuple[str, Json]]:
        nics = [n for n in await ctx.members(ctx.bmc.system_ethernet) if not is_absent(n)]
        return _unique(list(zip(self.nic_names(nics), nics, strict=True)))

    async def storage(self, ctx: PollContext) -> list[StorageInfo]:
        out: list[StorageInfo] = []
        drive_names: set[str] = set()
        volume_names: set[str] = set()
        for storage in await ctx.members(ctx.bmc.storage):
            name = self.controller_name(storage)
            controllers = [c for c in storage.get("StorageControllers") or [] if isinstance(c, dict)]
            health = health_of(storage) or (health_of(controllers[0]) if controllers else None)
            info = StorageInfo(name=name, resource=storage, controller=controllers[0] if controllers else {})
            info.health = health
            for i, path in enumerate(links(storage, "Drives")):
                drive = await ctx.get(path)
                if is_absent(drive):
                    continue
                drive_name = self.drive_name(drive, i)
                if drive_name in drive_names:
                    drive_name = f"{drive_name} ({name})"
                drive_names.add(drive_name)
                info.drives.append((drive_name, drive))
            for i, volume in enumerate(await ctx.members(link(storage, "Volumes"))):
                volume_name = self.volume_name(volume, i)
                if volume_name in volume_names:
                    volume_name = f"{volume_name} ({name})"
                volume_names.add(volume_name)
                info.volumes.append((volume_name, volume))
            out.append(info)
        return out

    # ----------------------------------------------------------------------------- 5 min: events
    async def collect_events(self, ctx: PollContext, state: ServerState) -> list[Event] | None:
        events: list[Event] = []
        for ref in ctx.bmc.log_services:
            if ref.entries is None or not self.include_log(ref):
                continue
            with ctx.soft(f"log {ref.id}"):
                events += await self._log_events(ctx, state, ref)
        return events or None

    async def _log_events(self, ctx: PollContext, state: ServerState, ref: LogServiceRef) -> list[Event]:
        assert ref.entries is not None
        coll = await ctx.client.get(ref.entries)
        seen = state.seen_events.setdefault(ref.path, set())
        current: set[str] = set()
        fresh: list[tuple[str, Json]] = []
        fetches = 0
        for member in coll.get("Members") or []:
            if not isinstance(member, dict):
                continue
            path = text(member.get("@odata.id")) or ""
            entry_id = text(member.get("Id")) or path.rstrip("/").rsplit("/", 1)[-1]
            if not entry_id or entry_id in current:
                continue
            if entry_id in seen:
                current.add(entry_id)
                continue
            if all(k.startswith("@odata.") for k in member):
                if fetches >= MAX_EVENT_FETCHES or not path:
                    continue  # not seen yet: fetched on a later poll
                fetches += 1
                member = await ctx.client.get(path)
            current.add(entry_id)
            fresh.append((entry_id, member))
        # Ids that rotated out of the log are forgotten, so the set stays bounded by the log size.
        state.seen_events[ref.path] = current
        out = []
        for entry_id, entry in fresh:
            message = text(entry.get("Message")) or text(entry.get("Name")) or ""
            out.append(
                Event.model_validate(
                    {
                        "entry_id": f"{ref.id}/{entry_id}",
                        "time": parse_time(entry.get("Created")) or ctx.now,
                        "severity": severity_of(entry.get("Severity")),
                        "message": message,
                        "message_id": text(entry.get("MessageId")),
                    }
                )
            )
        return out

    # ----------------------------------------------------------------------------- daily: inventory
    async def collect_identity(self, ctx: PollContext) -> Identity:
        system = await ctx.get(ctx.bmc.system_path)
        manager: Json | None = None
        if ctx.bmc.manager_path is not None:
            with ctx.soft("manager"):
                manager = await ctx.get(ctx.bmc.manager_path)
        bmc_mac: str | None = None
        with ctx.soft("manager network"):
            for nic in await ctx.members(ctx.bmc.manager_ethernet):
                bmc_mac = normalize_mac(nic.get("MACAddress")) or normalize_mac(
                    nic.get("PermanentMACAddress")
                )
                if bmc_mac:
                    break
        host_ips: list[str] = []
        with ctx.soft("network"):
            for _, nic in await self.nics(ctx):
                for addr in nic.get("IPv4Addresses") or []:
                    ip = text(dig(addr, "Address"))
                    if ip and ip != "0.0.0.0" and ip not in host_ips:  # noqa: S104 - an address, not a bind
                        host_ips.append(ip)
        uuid = text(system.get("UUID"))
        return Identity(
            vendor=self.vendor_name,
            model=text(system.get("Model")),
            serial=self.identity_serial(system),
            sku=text(system.get("SKU")),
            hostname=text(system.get("HostName")),
            uuid=uuid.lower() if uuid else None,
            asset_tag=text(system.get("AssetTag")),
            bmc_model=self.bmc_model(manager, ctx.bmc.root),
            bmc_firmware=text(dig(manager, "FirmwareVersion")),
            bmc_mac=bmc_mac or self.fallback_bmc_mac(ctx.bmc.root),
            system_path=ctx.bmc.system_path,
            host_ips=host_ips,
        )

    def fallback_bmc_mac(self, root: Json) -> str | None:
        return None

    async def collect_components(self, ctx: PollContext) -> list[Component]:
        parts: list[Component] = []
        with ctx.soft("processors"):
            for name, cpu in await self.cpus(ctx):
                parts.append(
                    Component(
                        type="cpu",
                        name=name,
                        model=text(cpu.get("Model")),
                        manufacturer=normalize_manufacturer(cpu.get("Manufacturer")),
                        serial=text(cpu.get("SerialNumber")),
                        capacity=num(cpu.get("TotalCores")),
                        capacity_unit="cores",
                        location=text(cpu.get("Socket")),
                        extra=_extra(threads=cpu.get("TotalThreads"), max_speed_mhz=cpu.get("MaxSpeedMHz")),
                    )
                )
        with ctx.soft("memory"):
            for name, dimm in await self.dimms(ctx):
                mib = num(dimm.get("CapacityMiB"))
                parts.append(
                    Component(
                        type="dimm",
                        name=name,
                        model=text(dimm.get("PartNumber")),
                        manufacturer=text(dimm.get("Manufacturer")),
                        serial=text(dimm.get("SerialNumber")),
                        capacity=round(mib / 1024, 2) if mib is not None else None,
                        capacity_unit="GiB",
                        location=text(dimm.get("DeviceLocator")) or text(dimm.get("Id")),
                        extra=_extra(
                            type=dimm.get("MemoryDeviceType"), speed_mhz=dimm.get("OperatingSpeedMhz")
                        ),
                    )
                )
        with ctx.soft("storage"):
            for ctl in await self.storage(ctx):
                parts.append(
                    Component(
                        type="storage_controller",
                        name=ctl.name,
                        model=text(ctl.controller.get("Model")) or text(ctl.resource.get("Name")),
                        manufacturer=text(ctl.controller.get("Manufacturer")),
                        serial=text(ctl.controller.get("SerialNumber")),
                        firmware_version=text(ctl.controller.get("FirmwareVersion")),
                        location=text(ctl.resource.get("Id")),
                    )
                )
                for name, drive in ctl.drives:
                    size = num(drive.get("CapacityBytes"))
                    bay = dig(drive, "PhysicalLocation", "PartLocation", "LocationOrdinalValue")
                    parts.append(
                        Component(
                            type="drive",
                            name=name,
                            model=text(drive.get("Model")),
                            manufacturer=text(drive.get("Manufacturer")),
                            serial=text(drive.get("SerialNumber")),
                            capacity=round(size / 1e9, 1) if size is not None else None,
                            capacity_unit="GB",
                            firmware_version=text(drive.get("Revision")),
                            location=f"Bay {bay}" if isinstance(bay, int) else text(drive.get("Id")),
                            extra=_extra(
                                media=drive.get("MediaType"),
                                protocol=drive.get("Protocol"),
                                controller=ctl.name,
                            ),
                        )
                    )
                for name, volume in ctl.volumes:
                    size = num(volume.get("CapacityBytes"))
                    parts.append(
                        Component(
                            type="volume",
                            name=name,
                            model=text(volume.get("Name")),
                            capacity=round(size / 1e9, 1) if size is not None else None,
                            capacity_unit="GB",
                            location=text(volume.get("Id")),
                            extra=_extra(
                                raid=volume.get("RAIDType") or volume.get("VolumeType"), controller=ctl.name
                            ),
                        )
                    )
        with ctx.soft("power supplies"):
            for name, psu in await self.psus(ctx):
                bay = dig(psu, "Location", "PartLocation", "LocationOrdinalValue")
                if not isinstance(bay, int) or isinstance(bay, bool):
                    bay = first_int(name)  # "PSU <bay>" from the vendor's naming hook
                parts.append(
                    Component(
                        type="psu",
                        name=name,
                        model=text(psu.get("Model")),
                        manufacturer=text(psu.get("Manufacturer")),
                        serial=text(psu.get("SerialNumber")),
                        capacity=num(psu.get("PowerCapacityWatts")),
                        capacity_unit="W",
                        firmware_version=text(psu.get("FirmwareVersion")),
                        location=f"Bay {bay}" if bay is not None else text(psu.get("Id")),
                    )
                )
        with ctx.soft("fans"):
            for name, fan in await self.fans(ctx):
                parts.append(
                    Component(
                        type="fan",
                        name=name,
                        model=text(fan.get("Model")),
                        manufacturer=text(fan.get("Manufacturer")),
                        serial=text(fan.get("SerialNumber")),
                        location=text(fan.get("Id") or fan.get("MemberId")),
                    )
                )
        with ctx.soft("network"):
            for name, nic in await self.nics(ctx):
                link_status = text(nic.get("LinkStatus"))
                speed = num(nic.get("SpeedMbps"))
                parts.append(
                    Component(
                        type="nic",
                        name=name,
                        model=text(nic.get("Name")),
                        manufacturer=text(nic.get("Manufacturer")),
                        capacity=speed if speed else None,
                        capacity_unit="Mbps",
                        location=text(nic.get("Id")),
                        link_up=(link_status in ("LinkUp", "Up")) if link_status else None,
                        extra=_extra(
                            mac=normalize_mac(nic.get("MACAddress") or nic.get("PermanentMACAddress"))
                        ),
                    )
                )
        return parts

    async def collect_firmware(self, ctx: PollContext) -> list[Firmware] | None:
        items: list[Firmware] = []
        names: set[str] = set()
        if ctx.bmc.firmware_inventory is not None:
            with ctx.soft("firmware inventory"):
                for entry in await ctx.members(ctx.bmc.firmware_inventory):
                    version = text(entry.get("Version"))
                    name = text(entry.get("Name")) or text(entry.get("Id"))
                    if not version or not name or not self.firmware_active(entry):
                        continue
                    key, kind = self.firmware_kind(name, text(entry.get("Id")) or "")
                    if kind == "drive":
                        continue  # drive firmware comes from the Drive resources (keyed by model)
                    unique = name
                    n = 2
                    while unique in names:
                        unique = f"{name} #{n}"
                        n += 1
                    names.add(unique)
                    items.append(
                        Firmware(component=unique, component_key=key, component_type=kind, version=version)
                    )
        with ctx.soft("drive firmware"):
            for ctl in await self.storage(ctx):
                for name, drive in ctl.drives:
                    version = text(drive.get("Revision"))
                    model = text(drive.get("Model"))
                    if version and model and name not in names:
                        names.add(name)
                        items.append(
                            Firmware(
                                component=name,
                                component_key=f"DRIVE:{model}",
                                component_type="drive",
                                version=version,
                            )
                        )
        return items or None


@dataclass
class StorageInfo:
    name: str
    resource: Json
    controller: Json
    health: str | None = None
    drives: list[tuple[str, Json]] = field(default_factory=list)
    volumes: list[tuple[str, Json]] = field(default_factory=list)


def _worst(healths: list[str | None]) -> str | None:
    known = [h for h in healths if h in HEALTH_VALUES]
    if not known:
        return None
    return max(known, key=lambda h: HEALTH_VALUES[h])


def _unique(items: list[tuple[str, Json]]) -> list[tuple[str, Json]]:
    """Keep the first part for each name (names must be unique per server and type)."""
    seen: set[str] = set()
    out = []
    for name, item in items:
        if name in seen:
            continue
        seen.add(name)
        out.append((name, item))
    return out


def _extra(**values: Any) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None and v != ""}
