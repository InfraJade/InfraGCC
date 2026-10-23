"""Sites, rooms, racks: summaries for the overview/site/rack screens and admin create/update bodies."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import Health
from app.core.pagination import Page
from app.schemas.common import (
    AlertCounts,
    ApiModel,
    CollectorRef,
    HealthCounts,
    ReadingValue,
    RoomRef,
    SiteRef,
)


class Freshness(ApiModel):
    """How current the live data is. A server is reporting if its newest reading is under 5 minutes old."""

    latest_reading_at: datetime | None = None
    oldest_server_reading_at: datetime | None = None
    servers_reporting: int = 0
    servers_stale: int = 0


class SiteSummary(ApiModel):
    id: int
    code: str
    name: str
    city: str
    country: str
    timezone: str
    room_count: int = 0
    rack_count: int = 0
    server_count: int = 0
    servers_in_maintenance: int = 0
    health: HealthCounts = Field(default_factory=HealthCounts)
    worst_health: Health = Health.UNKNOWN
    alerts: AlertCounts = Field(default_factory=AlertCounts)
    power_w: float | None = None
    rack_power_capacity_w: float | None = None
    inlet_avg_c: float | None = None
    inlet_max_c: float | None = None
    freshness: Freshness = Field(default_factory=Freshness)
    collectors_online: int = 0
    collectors_total: int = 0


class SitePage(Page[SiteSummary]):
    pass


class OverviewTotals(ApiModel):
    sites: int
    server_count: int
    health: HealthCounts
    worst_health: Health
    alerts: AlertCounts
    power_w: float | None
    freshness: Freshness
    collectors_online: int
    collectors_total: int


class OverviewOut(ApiModel):
    generated_at: datetime
    totals: OverviewTotals
    sites: list[SiteSummary]


class RackSummary(ApiModel):
    id: int
    name: str
    row: str | None
    height_u: int
    power_capacity_w: int | None
    server_count: int = 0
    used_u: int = 0
    health: HealthCounts = Field(default_factory=HealthCounts)
    worst_health: Health = Health.UNKNOWN
    open_alerts: int = 0
    power_w: float | None = None
    inlet_max_c: float | None = None


class RoomWithRacks(ApiModel):
    id: int
    name: str
    floor: str | None
    worst_health: Health
    racks: list[RackSummary]


class SiteDetail(SiteSummary):
    rooms: list[RoomWithRacks] = Field(default_factory=list)
    collectors: list[CollectorRef] = Field(default_factory=list)


class RackServer(ApiModel):
    id: int
    name: str
    bmc_host: str
    vendor: str | None
    model: str | None
    position_u: int | None
    height_u: int
    status: str
    health: Health
    inlet_temp: ReadingValue | None = None
    power: ReadingValue | None = None
    open_alerts: int = 0
    worst_alert_severity: str | None = None


class RackDetail(ApiModel):
    id: int
    name: str
    row: str | None
    height_u: int
    power_capacity_w: int | None
    site: SiteRef
    room: RoomRef
    used_u: int
    free_u: int
    power_w: float | None
    worst_health: Health
    servers: list[RackServer]


# ------------------------------------------------------------------------------------------ admin CRUD


class SiteOut(ApiModel):
    id: int
    code: str
    name: str
    city: str
    country: str
    timezone: str
    created_at: datetime
    updated_at: datetime


def _check_tz(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone {value!r}") from exc
    return value


class SiteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{1,15}$", description="Short code, e.g. PNQ1.")
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=120)
    country: str = Field(min_length=1, max_length=80)
    timezone: str = "UTC"

    _tz = field_validator("timezone")(_check_tz)


class SiteUpdate(BaseModel):
    """The code is fixed once created: site groups (`gcc-site-<CODE>`) refer to it."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    city: str | None = Field(default=None, min_length=1, max_length=120)
    country: str | None = Field(default=None, min_length=1, max_length=80)
    timezone: str | None = None

    _tz = field_validator("timezone")(_check_tz)


class RoomOut(ApiModel):
    id: int
    site_id: int
    site_code: str
    name: str
    floor: str | None
    rack_count: int


class RoomPage(Page[RoomOut]):
    pass


class RoomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: int
    name: str = Field(min_length=1, max_length=120)
    floor: str | None = Field(default=None, max_length=32)


class RoomUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    floor: str | None = Field(default=None, max_length=32)


class RackOut(ApiModel):
    id: int
    room_id: int
    room_name: str
    site_id: int
    site_code: str
    name: str
    row: str | None
    height_u: int
    power_capacity_w: int | None
    server_count: int
    used_u: int


class RackPage(Page[RackOut]):
    pass


class RackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: int
    name: str = Field(min_length=1, max_length=64)
    row: str | None = Field(default=None, max_length=32)
    height_u: int = Field(default=42, ge=1, le=60)
    power_capacity_w: int | None = Field(default=None, ge=0)


class RackUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=64)
    row: str | None = Field(default=None, max_length=32)
    height_u: int | None = Field(default=None, ge=1, le=60)
    power_capacity_w: int | None = Field(default=None, ge=0)
