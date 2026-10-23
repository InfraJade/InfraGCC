"""Admin screens: metrics, alert rules, thresholds, routes, maintenance, collectors, baselines, users and
audit."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    MaintenanceScope,
    RouteChannel,
    RuleType,
    Severity,
    ThresholdDirection,
    ThresholdScope,
)
from app.core.pagination import Page
from app.schemas.common import ApiModel


class MetricOut(ApiModel):
    id: int
    code: str
    name: str
    unit: str
    interval_s: int
    type: str
    parameter_no: int
    category: str
    description: str


# ---------------------------------------------------------------------------------------- alert rules


class AlertRuleOut(ApiModel):
    id: int
    name: str
    description: str
    rule_type: str
    metric: str | None
    condition: dict[str, Any]
    duration_s: int
    severity: str
    route: str
    enabled: bool
    builtin: bool
    updated_by: str | None
    updated_at: datetime


class AlertRulePage(Page[AlertRuleOut]):
    pass


class AlertRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    rule_type: RuleType
    metric: str | None = Field(default=None, description="Metric code; required except for missing_data.")
    condition: dict[str, Any] = Field(default_factory=dict)
    duration_s: int = Field(default=0, ge=0, le=86400)
    severity: Severity = Severity.WARNING
    route: str = Field(default="hardware", pattern=r"^[a-z0-9_-]{1,32}$")
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    """Built-in rules keep their type and metric; everything else can be tuned."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    condition: dict[str, Any] | None = None
    duration_s: int | None = Field(default=None, ge=0, le=86400)
    severity: Severity | None = None
    route: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,32}$")
    enabled: bool | None = None


class AlertRuleBulkItem(AlertRuleUpdate):
    id: int


class AlertRuleBulkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AlertRuleBulkItem] = Field(min_length=1, max_length=200)


# ----------------------------------------------------------------------------------------- thresholds


class ThresholdOut(ApiModel):
    id: int
    metric: str
    metric_name: str
    unit: str
    scope: str
    site_id: int | None
    server_id: int | None
    vendor: str | None
    model: str | None
    direction: str
    warning: float | None
    critical: float | None
    nominal: float | None
    updated_by: str | None
    updated_at: datetime


class BmcLimitOut(ApiModel):
    metric: str
    component: str
    lower_critical: float | None
    lower_warning: float | None
    upper_warning: float | None
    upper_critical: float | None
    updated_at: datetime


class EffectiveLimit(ApiModel):
    """The limit that applies to one sensor of a server, and where it comes from (D12 precedence)."""

    metric: str
    component: str
    source: Literal["server", "site", "model", "global", "bmc"]
    threshold_id: int | None
    direction: str
    warning: float | None
    critical: float | None
    nominal: float | None = None
    lower_warning: float | None = None
    lower_critical: float | None = None


class ThresholdPage(Page[ThresholdOut]):
    bmc_limits: list[BmcLimitOut] | None = None
    effective: list[EffectiveLimit] | None = None


class ThresholdLimits(BaseModel):
    direction: ThresholdDirection = ThresholdDirection.ABOVE
    warning: float | None = None
    critical: float | None = None
    nominal: float | None = None

    @model_validator(mode="after")
    def _has_limit(self) -> ThresholdLimits:
        if self.warning is None and self.critical is None:
            raise ValueError("set a warning or a critical limit (or both)")
        return self


class ThresholdIn(ThresholdLimits):
    """An override at one scope: model (vendor + model), site, or server. Global rows already exist."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    scope: ThresholdScope
    site_id: int | None = None
    server_id: int | None = None
    vendor: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _target(self) -> ThresholdIn:
        ok = {
            ThresholdScope.GLOBAL: self.site_id is None and self.server_id is None and self.model is None,
            ThresholdScope.SITE: self.site_id is not None and self.server_id is None and self.model is None,
            ThresholdScope.SERVER: self.server_id is not None and self.site_id is None and self.model is None,
            ThresholdScope.MODEL: self.model is not None and self.site_id is None and self.server_id is None,
        }[self.scope]
        if not ok:
            raise ValueError(
                "scope target mismatch: global → none; site → site_id; server → server_id; "
                "model → model (and optionally vendor)"
            )
        return self


class ThresholdUpdate(ThresholdLimits):
    model_config = ConfigDict(extra="forbid")


class ThresholdBulkIn(BaseModel):
    """Upsert several limits at once, matched by (metric, scope, site, server, vendor, model)."""

    model_config = ConfigDict(extra="forbid")

    items: list[ThresholdIn] = Field(min_length=1, max_length=200)


# ---------------------------------------------------------------------------------------- alert routes


class AlertRouteOut(ApiModel):
    id: int
    name: str
    route: str
    site_id: int | None
    min_severity: str
    escalation_level: int
    channel: str
    target_hint: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AlertRoutePage(Page[AlertRouteOut]):
    pass


class AlertRouteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    route: str = Field(default="*", pattern=r"^(\*|[a-z0-9_-]{1,32})$")
    site_id: int | None = None
    min_severity: Severity = Severity.CRITICAL
    escalation_level: int = Field(default=0, ge=0, le=5)
    channel: RouteChannel
    target: str = Field(
        min_length=3,
        max_length=2000,
        description="Comma-separated email addresses, or the Teams incoming-webhook URL. Stored encrypted.",
    )
    enabled: bool = True


class AlertRouteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    route: str | None = Field(default=None, pattern=r"^(\*|[a-z0-9_-]{1,32})$")
    site_id: int | None = None
    min_severity: Severity | None = None
    escalation_level: int | None = Field(default=None, ge=0, le=5)
    channel: RouteChannel | None = None
    target: str | None = Field(default=None, min_length=3, max_length=2000)
    enabled: bool | None = None


# --------------------------------------------------------------------------------- maintenance windows


class MaintenanceOut(ApiModel):
    id: int
    scope: str
    site_id: int | None
    rack_id: int | None
    server_id: int | None
    target_site_id: int
    target_name: str
    starts_at: datetime
    ends_at: datetime
    reason: str
    created_by: str | None
    created_at: datetime
    active: bool


class MaintenancePage(Page[MaintenanceOut]):
    pass


class MaintenanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: MaintenanceScope
    site_id: int | None = None
    rack_id: int | None = None
    server_id: int | None = None
    starts_at: datetime
    ends_at: datetime
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _check(self) -> MaintenanceCreate:
        target = {
            MaintenanceScope.SITE: self.site_id,
            MaintenanceScope.RACK: self.rack_id,
            MaintenanceScope.SERVER: self.server_id,
        }[self.scope]
        if target is None or sum(x is not None for x in (self.site_id, self.rack_id, self.server_id)) != 1:
            raise ValueError(f"scope '{self.scope.value}' needs exactly {self.scope.value}_id")
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("times need a UTC offset")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class MaintenanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=2000)


# ------------------------------------------------------------------------------------------ collectors


class CollectorOut(ApiModel):
    id: int
    site_id: int
    site_code: str
    name: str
    version: str | None
    hostname: str | None
    enabled: bool
    online: bool
    last_heartbeat: datetime | None
    heartbeat_age_s: int | None
    cert_fingerprint: str | None
    servers_preferred: int
    stats: dict[str, Any]
    created_at: datetime


class CollectorPage(Page[CollectorOut]):
    pass


class CollectorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: int
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    cert_fingerprint: str | None = Field(
        default=None, max_length=128, description="SHA-256 of the client certificate (mTLS mode)."
    )
    enabled: bool = True


class CollectorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cert_fingerprint: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None


# --------------------------------------------------------------------------------- firmware baselines


class BaselineOut(ApiModel):
    id: int
    vendor: str
    model: str
    component: str
    version: str
    notes: str | None
    updated_by: str | None
    updated_at: datetime


class BaselinePage(Page[BaselineOut]):
    pass


class BaselineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=128)
    component: str = Field(
        min_length=1,
        max_length=160,
        description="Firmware key: BIOS, BMC, CPLD, PSU, NIC, RAID or DRIVE:<model>.",
    )
    version: str = Field(min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class BaselineUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str | None = Field(default=None, min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class ComplianceDiff(ApiModel):
    component: str
    component_key: str
    component_type: str
    installed_version: str
    approved_version: str
    collected_at: datetime


class ComplianceServer(ApiModel):
    server_id: int
    server_name: str
    site_id: int
    site_code: str
    rack_name: str | None
    vendor: str | None
    model: str | None
    differences: list[ComplianceDiff]


class ComplianceSummary(ApiModel):
    servers_with_firmware: int
    servers_checked: int
    servers_compliant: int
    servers_off_baseline: int
    components_off_baseline: int
    models_without_baseline: int


class ComplianceOut(Page[ComplianceServer]):
    summary: ComplianceSummary


# --------------------------------------------------------------------------------------- users, audit


class UserOut(ApiModel):
    id: int
    sub: str
    email: str | None
    name: str
    roles: list[str]
    sites: list[str] | None
    last_login_at: datetime | None
    created_at: datetime


class UserPage(Page[UserOut]):
    pass


class AuditOut(ApiModel):
    id: int
    time: datetime
    user_sub: str | None
    user_name: str
    action: str
    object_type: str
    object_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None
    request_id: str | None


class AuditPage(Page[AuditOut]):
    pass
