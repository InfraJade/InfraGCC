"""Collector ↔ ingest contract v1 (docs/contracts/README.md), as Pydantic models.

The collector owns its own copy of these models (DECISIONS.md D7); `docs/contracts/ingest-batch.example.json`
pins both sides together. Unknown fields are rejected (`extra="forbid"`): any addition is a contract change.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------------------------- batch


class ReadingIn(_Strict):
    time: AwareDatetime
    metric: str = Field(min_length=1, max_length=48)
    component: str = Field(default="", max_length=128)
    value: float | None
    status: str | None = Field(default=None, max_length=64)


class BmcLimitIn(_Strict):
    metric: str = Field(min_length=1, max_length=48)
    component: str = Field(default="", max_length=128)
    lower_critical: float | None = None
    lower_warning: float | None = None
    upper_warning: float | None = None
    upper_critical: float | None = None


class EventIn(_Strict):
    entry_id: str = Field(min_length=1, max_length=255)
    time: AwareDatetime
    severity: Literal["OK", "Warning", "Critical"]
    message: str = Field(max_length=8000)
    message_id: str | None = Field(default=None, max_length=128)


class IdentityIn(_Strict):
    vendor: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=128)
    serial: str | None = Field(default=None, max_length=64)
    sku: str | None = Field(default=None, max_length=128)
    hostname: str | None = Field(default=None, max_length=128)
    uuid: str | None = Field(default=None, max_length=64)
    asset_tag: str | None = Field(default=None, max_length=64)
    bmc_model: str | None = Field(default=None, max_length=64)
    bmc_firmware: str | None = Field(default=None, max_length=64)
    bmc_mac: str | None = Field(default=None, max_length=32)
    system_path: str | None = Field(default=None, max_length=255)
    host_ips: list[str] | None = Field(default=None, max_length=64)


class ComponentIn(_Strict):
    type: Literal["cpu", "dimm", "drive", "psu", "fan", "nic", "storage_controller", "volume"]
    name: str = Field(min_length=1, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    manufacturer: str | None = Field(default=None, max_length=128)
    serial: str | None = Field(default=None, max_length=128)
    capacity: float | None = None
    capacity_unit: str | None = Field(default=None, max_length=16)
    firmware_version: str | None = Field(default=None, max_length=64)
    location: str | None = Field(default=None, max_length=128)
    link_up: bool | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class FirmwareIn(_Strict):
    component: str = Field(min_length=1, max_length=255)
    component_key: str = Field(min_length=1, max_length=160)
    component_type: Literal["bios", "bmc", "cpld", "psu", "nic", "storage_controller", "drive", "other"]
    version: str = Field(min_length=1, max_length=128)


class ServerPayload(_Strict):
    server_id: int
    polled_at: AwareDatetime
    readings: list[ReadingIn] | None = None
    bmc_limits: list[BmcLimitIn] | None = None
    events: list[EventIn] | None = None
    identity: IdentityIn | None = None
    components: list[ComponentIn] | None = None
    firmware: list[FirmwareIn] | None = None


class BatchIn(_Strict):
    # `schema` shadows a BaseModel attribute name, hence the alias.
    schema_version: Literal[1] = Field(alias="schema")
    batch_id: str = Field(min_length=1, max_length=64)
    collector: str = Field(min_length=1, max_length=64)
    sent_at: AwareDatetime
    servers: list[ServerPayload] = Field(max_length=1000)


class BatchOut(BaseModel):
    batch_id: str
    duplicate: bool
    servers: int
    readings: int
    events: int


# --------------------------------------------------------------------------------------------- heartbeat


class HeartbeatStats(_Strict):
    servers_assigned: int | None = None
    servers_ok: int | None = None
    polls_ok_1m: int | None = None
    polls_failed_1m: int | None = None
    cycles_skipped_1m: int | None = None
    buffer_batches: int | None = None
    buffer_bytes: int | None = None
    last_batch_at: AwareDatetime | None = None
    errors_by_vendor: dict[str, int] = Field(default_factory=dict)


class HeartbeatIn(_Strict):
    collector: str = Field(min_length=1, max_length=64)
    version: str | None = Field(default=None, max_length=32)
    hostname: str | None = Field(default=None, max_length=255)
    sent_at: AwareDatetime
    config_version: str | None = Field(default=None, max_length=64)
    stats: HeartbeatStats = Field(default_factory=HeartbeatStats)


class HeartbeatOut(BaseModel):
    ok: bool = True
    config_version: str


# --------------------------------------------------------------------------------------------- config


class CollectorInfo(BaseModel):
    id: int
    name: str
    site_code: str


class CollectorSettings(BaseModel):
    sensor_interval_s: int = 60
    health_interval_s: int = 300
    inventory_interval_s: int = 86400
    batch_interval_s: int = 12
    heartbeat_interval_s: int = 30
    config_refresh_s: int = 60
    max_parallel_bmcs: int = 50
    request_timeout_s: int = 20


class AssignedServerOut(BaseModel):
    id: int
    bmc_host: str
    vendor: str | None
    status: str
    credential_ref: str
    takeover: bool


class ConfigOut(BaseModel):
    collector: CollectorInfo
    config_version: str
    settings: CollectorSettings
    servers: list[AssignedServerOut]
