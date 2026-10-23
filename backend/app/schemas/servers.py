"""Servers: list rows, detail, onboarding/edit bodies, parts, events and reading history."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import Health, ServerStatus
from app.core.pagination import Page
from app.schemas.alerts import AlertOut
from app.schemas.common import ApiModel, CollectorRef, RackRef, RoomRef, SiteRef

# host | host:port | http(s)://host[:port]  (http:// is for simulators and mockups only).
_BMC_HOST = re.compile(
    r"^(?:(https?)://)?([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:]+\])(?::(\d{1,5}))?/?$"
)


def normalize_bmc_host(value: str) -> str:
    value = value.strip()
    match = _BMC_HOST.match(value)
    if not match:
        raise ValueError(
            "BMC address must be a host name or IP, optionally with :port or an http(s):// scheme"
        )
    port = match.group(3)
    if port is not None and not 0 < int(port) < 65536:
        raise ValueError("port must be between 1 and 65535")
    return value.rstrip("/")


class ServerListItem(ApiModel):
    id: int
    name: str
    hostname: str | None
    bmc_host: str
    vendor: str | None
    model: str | None
    serial: str | None
    asset_tag: str | None
    status: str
    health: Health
    site: SiteRef
    room: RoomRef | None
    rack: RackRef | None
    position_u: int | None
    height_u: int
    collector_id: int | None
    collector_name: str | None
    last_seen_at: datetime | None
    open_alerts: int


class ServerPage(Page[ServerListItem]):
    pass


class HealthPart(ApiModel):
    metric: str
    metric_name: str
    category: str
    component: str
    health: Health
    state: str | None
    since: datetime
    updated_at: datetime


class LatestReadingOut(ApiModel):
    metric: str
    metric_name: str
    unit: str
    type: str
    category: str
    component: str
    value: float | None
    status: str | None
    time: datetime
    age_s: int


class ComponentOut(ApiModel):
    id: int
    server_id: int
    type: str
    name: str
    model: str | None
    manufacturer: str | None
    serial: str | None
    capacity: float | None
    capacity_unit: str | None
    firmware_version: str | None
    location: str | None
    expected_link_up: bool | None
    extra: dict[str, Any]
    first_seen_at: datetime
    last_seen_at: datetime
    removed_at: datetime | None


class ComponentListItem(ComponentOut):
    server_name: str
    site_id: int
    site_code: str


class ComponentPage(Page[ComponentListItem]):
    pass


class FirmwareItem(ApiModel):
    component: str
    component_key: str
    component_type: str
    version: str
    approved_version: str | None
    compliant: bool | None
    collected_at: datetime


class EventOut(ApiModel):
    id: int
    server_id: int
    time: datetime
    severity: str
    message: str
    message_id: str | None
    entry_id: str


class EventPage(Page[EventOut]):
    pass


class ServerDetail(ServerListItem):
    bmc_mac: str | None
    bmc_model: str | None
    host_ips: list[str]
    system_path: str | None
    notes: str | None
    discovered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    collector: CollectorRef | None
    rack_height_u: int | None
    health_parts: list[HealthPart]
    latest_readings: list[LatestReadingOut]
    components: list[ComponentOut]
    firmware: list[FirmwareItem]
    recent_events: list[EventOut]
    active_alerts: list[AlertOut]


class ServerCreate(BaseModel):
    """Onboard a server the way an engineer would; vendor, model, serial and parts come from the BMC."""

    model_config = ConfigDict(extra="forbid")

    bmc_host: str = Field(min_length=1, max_length=255, examples=["10.20.1.11", "https://idrac-a01-07:443"])
    rack_id: int
    position_u: int = Field(ge=1, le=60, description="Lowest U the server occupies.")
    height_u: int = Field(default=1, ge=1, le=10)
    collector_id: int | None = Field(
        default=None, description="Preferred collector; defaults to the site's least-loaded collector."
    )
    name: str | None = Field(default=None, max_length=128)
    asset_tag: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "maintenance"] = "active"

    _host = field_validator("bmc_host")(normalize_bmc_host)


class ServerUpdate(BaseModel):
    """Only the fields present are changed. `rack_id: null` takes the server out of its rack."""

    model_config = ConfigDict(extra="forbid")

    rack_id: int | None = None
    position_u: int | None = Field(default=None, ge=1, le=60)
    height_u: int | None = Field(default=None, ge=1, le=10)
    status: ServerStatus | None = None
    name: str | None = Field(default=None, max_length=128)
    asset_tag: str | None = Field(default=None, max_length=64)
    collector_id: int | None = None
    notes: str | None = Field(default=None, max_length=4000)


class ReadingPoint(BaseModel):
    t: datetime
    v: float | None
    min: float | None = None
    max: float | None = None


class ReadingSeries(BaseModel):
    component: str
    points: list[ReadingPoint]


class ReadingsOut(BaseModel):
    server_id: int
    metric: str
    metric_name: str
    unit: str
    type: str
    start: datetime
    end: datetime
    resolution: Literal["raw", "5m", "1h"]
    step_s: int
    series: list[ReadingSeries]
