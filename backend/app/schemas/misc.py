"""Current user, global search and Superset embedding."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Health
from app.schemas.common import ApiModel, SiteRef


class MeOut(ApiModel):
    sub: str
    username: str
    name: str
    email: str | None
    roles: list[str]
    primary_role: str | None
    site_limited: bool
    # None = all sites.
    sites: list[SiteRef] | None
    capabilities: dict[str, bool]
    token_expires_at: datetime


class SearchServer(ApiModel):
    id: int
    name: str
    bmc_host: str
    serial: str | None
    asset_tag: str | None
    model: str | None
    site_code: str
    rack_name: str | None
    position_u: int | None
    health: Health


class SearchRack(ApiModel):
    id: int
    name: str
    room_name: str
    site_id: int
    site_code: str


class SearchSite(SiteRef):
    city: str


class SearchOut(ApiModel):
    query: str
    servers: list[SearchServer]
    racks: list[SearchRack]
    sites: list[SearchSite]


class DashboardOut(BaseModel):
    slug: str
    title: str
    embedded_uuid: str
    refresh_s: int


class GuestTokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dashboard: str = Field(min_length=1, max_length=64, description="Embedded dashboard UUID.")


class GuestTokenOut(BaseModel):
    token: str
    expires_at: datetime
    superset_url: str
