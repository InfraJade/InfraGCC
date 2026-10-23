"""Pydantic models of the collector <-> ingest contract (docs/contracts/README.md, schema 1).

The collector owns its own copy of the contract (DECISIONS.md D7). Everything the collector *sends* uses
``extra="forbid"`` so a typo can never reach the cloud; what it *receives* (config, responses) ignores
unknown fields, so a newer cloud does not break an older collector.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_serializer

SCHEMA_VERSION = 1

MetricCode = Literal[
    "inlet_temp_c",
    "exhaust_temp_c",
    "cpu_temp_c",
    "dimm_temp_c",
    "fan_rpm",
    "fan_pct",
    "fan_health",
    "fan_redundancy",
    "power_w",
    "power_capacity_w",
    "power_limit_w",
    "psu_health",
    "psu_input_v",
    "psu_redundancy",
    "power_state",
    "system_health",
    "cpu_health",
    "memory_health",
    "drive_health",
    "drive_life_pct",
    "storage_health",
    "volume_health",
    "nic_link",
    "bmc_health",
    "bmc_reachable",
]

# The 25 reading codes (metric_definitions minus sel_event / firmware_version, which travel as
# events / firmware).
READING_METRICS: tuple[str, ...] = get_args(MetricCode)

# Which poll produces each reading (metric_definitions.interval_s).
SENSOR_METRICS = frozenset(
    {
        "inlet_temp_c",
        "exhaust_temp_c",
        "cpu_temp_c",
        "dimm_temp_c",
        "fan_rpm",
        "fan_pct",
        "power_w",
        "psu_input_v",
        "power_state",
        "system_health",
        "bmc_health",
        "bmc_reachable",
    }
)
HEALTH_METRICS = frozenset(READING_METRICS) - SENSOR_METRICS

Severity = Literal["OK", "Warning", "Critical"]
ComponentType = Literal["cpu", "dimm", "drive", "psu", "fan", "nic", "storage_controller", "volume"]
FirmwareType = Literal["bios", "bmc", "cpld", "psu", "nic", "storage_controller", "drive", "other"]


def _iso(value: datetime) -> str:
    """ISO 8601 in UTC with a ``Z`` suffix, as the contract shows."""
    text = value.isoformat()
    return text.removesuffix("+00:00") + "Z" if text.endswith("+00:00") else text


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Reading(_Out):
    time: datetime
    metric: MetricCode
    component: str = ""
    value: int | float | None
    status: str | None = None

    @field_serializer("time")
    def _ser_time(self, value: datetime) -> str:
        return _iso(value)


class BmcLimit(_Out):
    metric: MetricCode
    component: str = ""
    lower_critical: float | None = None
    lower_warning: float | None = None
    upper_warning: float | None = None
    upper_critical: float | None = None


class Event(_Out):
    entry_id: str
    time: datetime
    severity: Severity
    message: str
    message_id: str | None = None

    @field_serializer("time")
    def _ser_time(self, value: datetime) -> str:
        return _iso(value)


class Identity(_Out):
    vendor: str
    model: str | None = None
    serial: str | None = None
    sku: str | None = None
    hostname: str | None = None
    uuid: str | None = None
    asset_tag: str | None = None
    bmc_model: str | None = None
    bmc_firmware: str | None = None
    bmc_mac: str | None = None
    system_path: str | None = None
    host_ips: list[str] = Field(default_factory=list)


class Component(_Out):
    type: ComponentType
    name: str
    model: str | None = None
    manufacturer: str | None = None
    serial: str | None = None
    capacity: float | None = None
    capacity_unit: str | None = None
    firmware_version: str | None = None
    location: str | None = None
    link_up: bool | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Firmware(_Out):
    component: str
    component_key: str
    component_type: FirmwareType
    version: str


class ServerPayload(_Out):
    server_id: int
    polled_at: datetime
    readings: list[Reading] | None = None
    bmc_limits: list[BmcLimit] | None = None
    events: list[Event] | None = None
    identity: Identity | None = None
    components: list[Component] | None = None
    firmware: list[Firmware] | None = None

    @field_serializer("polled_at")
    def _ser_time(self, value: datetime) -> str:
        return _iso(value)


class Batch(_Out):
    schema_: int = Field(default=SCHEMA_VERSION, alias="schema")
    batch_id: str
    collector: str
    sent_at: datetime
    servers: list[ServerPayload]

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_serializer("sent_at")
    def _ser_time(self, value: datetime) -> str:
        return _iso(value)

    def to_json_dict(self) -> dict[str, Any]:
        """Wire form: aliases (``schema``), and lists the poll did not produce left out."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=False, exclude=_none_lists(self))


def _none_lists(batch: Batch) -> dict[str, Any]:
    # Omit list fields that are None ("nothing new of this kind") so bodies stay small.
    fields = ("readings", "bmc_limits", "events", "identity", "components", "firmware")
    out: dict[int, set[str]] = {}
    for i, server in enumerate(batch.servers):
        missing = {f for f in fields if getattr(server, f) is None}
        if missing:
            out[i] = missing
    return {"servers": out} if out else {}


class HeartbeatStats(_Out):
    servers_assigned: int
    servers_ok: int
    polls_ok_1m: int
    polls_failed_1m: int
    cycles_skipped_1m: int
    buffer_batches: int
    buffer_bytes: int
    last_batch_at: datetime | None = None
    errors_by_vendor: dict[str, int] = Field(default_factory=dict)

    @field_serializer("last_batch_at")
    def _ser_time(self, value: datetime | None) -> str | None:
        return _iso(value) if value is not None else None


class Heartbeat(_Out):
    collector: str
    version: str
    hostname: str
    sent_at: datetime
    config_version: str | None
    stats: HeartbeatStats

    @field_serializer("sent_at")
    def _ser_time(self, value: datetime) -> str:
        return _iso(value)


# ------------------------------------------------------------------------------------------ inbound


class _In(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CollectorInfo(_In):
    id: int
    name: str
    site_code: str | None = None


class CollectorSettings(_In):
    sensor_interval_s: int = 60
    health_interval_s: int = 300
    inventory_interval_s: int = 86400
    batch_interval_s: int = 12
    heartbeat_interval_s: int = 30
    config_refresh_s: int = 60
    max_parallel_bmcs: int = 50
    request_timeout_s: int = 20


class ServerConfig(_In):
    id: int
    bmc_host: str
    vendor: str | None = None
    status: str = "active"
    credential_ref: str = "default"
    takeover: bool = False


class CollectorConfig(_In):
    collector: CollectorInfo
    config_version: str
    settings: CollectorSettings = Field(default_factory=CollectorSettings)
    servers: list[ServerConfig] = Field(default_factory=list)


class BatchResponse(_In):
    batch_id: str | None = None
    duplicate: bool = False
    servers: int | None = None
    readings: int | None = None
    events: int | None = None


class HeartbeatResponse(_In):
    ok: bool = True
    config_version: str | None = None
