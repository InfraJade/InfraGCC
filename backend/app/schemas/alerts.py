"""Alerts, their activity, and the operator actions (acknowledge, comment, resolve)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.pagination import Page
from app.schemas.common import ApiModel, ServerRef, SiteRef


class AlertRuleRef(ApiModel):
    id: int
    name: str
    rule_type: str


class CollectorBrief(ApiModel):
    id: int
    name: str


class AlertOut(ApiModel):
    id: int
    rule: AlertRuleRef
    server: ServerRef | None
    site: SiteRef | None
    collector: CollectorBrief | None
    metric: str | None
    component: str
    state: str
    severity: str
    title: str
    message: str
    value: float | None
    threshold: float | None
    muted: bool
    occurrences: int
    opened_at: datetime
    last_seen_at: datetime
    acked_at: datetime | None
    acked_by: str | None
    resolved_at: datetime | None
    resolved_by: str | None
    notified_at: datetime | None
    escalated_at: datetime | None
    # Operators may resolve event and compliance alerts by hand; the others resolve when readings recover.
    manually_resolvable: bool


class AlertPage(Page[AlertOut]):
    pass


class AlertActivityOut(ApiModel):
    id: int
    time: datetime
    actor: str
    action: str
    from_state: str | None
    to_state: str | None
    note: str | None
    details: dict[str, Any]


class AlertDetail(AlertOut):
    activity: list[AlertActivityOut]


class AckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=4000)


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=4000)


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=4000)
