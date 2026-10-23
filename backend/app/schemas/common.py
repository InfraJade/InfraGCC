"""Small shared shapes: references to related objects and health/alert counters."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import Health


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SiteRef(ApiModel):
    id: int
    code: str
    name: str


class RoomRef(ApiModel):
    id: int
    name: str


class RackRef(ApiModel):
    id: int
    name: str


class ServerRef(ApiModel):
    id: int
    name: str
    bmc_host: str


class CollectorRef(ApiModel):
    id: int
    name: str
    online: bool


class HealthCounts(ApiModel):
    """Servers per worst health. A server with no health data yet counts as Unknown."""

    ok: int = 0
    warning: int = 0
    critical: int = 0
    unknown: int = 0

    def add(self, health: Health, n: int = 1) -> None:
        field = health.value.lower()
        setattr(self, field, getattr(self, field) + n)

    def worst(self) -> Health:
        if self.critical:
            return Health.CRITICAL
        if self.warning:
            return Health.WARNING
        if self.unknown:
            return Health.UNKNOWN
        return Health.OK if self.ok else Health.UNKNOWN


class AlertCounts(ApiModel):
    """Unresolved alerts. Severity counts exclude muted alerts (maintenance windows)."""

    critical: int = 0
    warning: int = 0
    info: int = 0
    acknowledged: int = 0
    muted: int = 0

    @property
    def total(self) -> int:
        return self.critical + self.warning + self.info


class ReadingValue(ApiModel):
    value: float | None
    unit: str
    status: str | None
    time: datetime
    age_s: int


class ProblemError(BaseModel):
    loc: list[str]
    msg: str
    type: str


class ProblemOut(BaseModel):
    """RFC 9457 problem details (media type `application/problem+json`). Extra members may appear."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[ProblemError] | None = None
