"""Alert rules, alerts and their activity, routing, and maintenance windows."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    false,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AlertState, MaintenanceScope, RouteChannel, RuleType, Severity, check_in
from app.models.base import Base, TimestampMixin


class AlertRule(TimestampMixin, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint(check_in("rule_type", RuleType), name="rule_type_valid"),
        CheckConstraint(check_in("severity", Severity), name="severity_valid"),
        CheckConstraint("duration_s >= 0", name="duration_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    rule_type: Mapped[str] = mapped_column(String(16))
    metric_code: Mapped[int | None] = mapped_column(ForeignKey("metric_definitions.id"))
    # Rule-type specific settings, e.g. {"states": ["Warning", "Critical"]} or {"polls": 3}.
    condition: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    duration_s: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    severity: Mapped[str] = mapped_column(
        String(16), default=Severity.WARNING.value, server_default=Severity.WARNING.value
    )
    route: Mapped[str] = mapped_column(String(32), default="hardware", server_default="hardware")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    builtin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    updated_by: Mapped[str | None] = mapped_column(String(128))


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(check_in("state", AlertState), name="state_valid"),
        CheckConstraint(check_in("severity", Severity), name="severity_valid"),
        # "One alert per server, metric and part": at most one unresolved alert per dedupe key.
        Index(
            "uq_alerts_active_dedupe", "dedupe_key", unique=True, postgresql_where=text("state <> 'resolved'")
        ),
        Index("ix_alerts_state_severity", "state", "severity"),
        Index("ix_alerts_site_opened", "site_id", "opened_at"),
        Index("ix_alerts_opened", "opened_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id", ondelete="RESTRICT"), index=True)
    server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    collector_id: Mapped[int | None] = mapped_column(ForeignKey("collectors.id", ondelete="CASCADE"))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    metric_code: Mapped[int | None] = mapped_column(ForeignKey("metric_definitions.id"))
    component: Mapped[str] = mapped_column(Text, default="", server_default="")
    dedupe_key: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(
        String(16), default=AlertState.OPEN.value, server_default=AlertState.OPEN.value
    )
    severity: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text, default="", server_default="")
    value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    muted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    occurrences: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    opened_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    acked_at: Mapped[datetime | None]
    acked_by: Mapped[str | None] = mapped_column(String(128))
    resolved_at: Mapped[datetime | None]
    resolved_by: Mapped[str | None] = mapped_column(String(128))
    notified_at: Mapped[datetime | None]
    escalated_at: Mapped[datetime | None]

    rule: Mapped[AlertRule] = relationship()
    activity: Mapped[list[AlertActivity]] = relationship(
        back_populates="alert", order_by="AlertActivity.time", cascade="all, delete-orphan"
    )


class AlertActivity(Base):
    """Every state change, comment and notification on an alert, with who and when."""

    __tablename__ = "alert_activity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    time: Mapped[datetime] = mapped_column(server_default=func.now())
    actor: Mapped[str] = mapped_column(String(128), default="system", server_default="system")
    actor_sub: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(32))
    from_state: Mapped[str | None] = mapped_column(String(16))
    to_state: Mapped[str | None] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))

    alert: Mapped[Alert] = relationship(back_populates="activity")


class AlertRoute(TimestampMixin, Base):
    """Where alerts go: per route key (team), site and minimum severity."""

    __tablename__ = "alert_routes"
    __table_args__ = (
        CheckConstraint(check_in("channel", RouteChannel), name="channel_valid"),
        CheckConstraint(check_in("min_severity", Severity), name="min_severity_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    route: Mapped[str] = mapped_column(String(32), default="*", server_default="*")
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    min_severity: Mapped[str] = mapped_column(
        String(16), default=Severity.CRITICAL.value, server_default=Severity.CRITICAL.value
    )
    escalation_level: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    channel: Mapped[str] = mapped_column(String(16))
    # Email lists and Teams webhook URLs are encrypted at rest; `target_hint` is a masked preview.
    target_encrypted: Mapped[str] = mapped_column(Text)
    target_hint: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_windows"
    __table_args__ = (
        CheckConstraint(check_in("scope", MaintenanceScope), name="scope_valid"),
        CheckConstraint("ends_at > starts_at", name="ends_after_start"),
        CheckConstraint(
            "(scope = 'site' AND site_id IS NOT NULL) OR (scope = 'rack' AND rack_id IS NOT NULL)"
            " OR (scope = 'server' AND server_id IS NOT NULL)",
            name="scope_target",
        ),
        Index("ix_maintenance_windows_period", "starts_at", "ends_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    rack_id: Mapped[int | None] = mapped_column(ForeignKey("racks.id", ondelete="CASCADE"))
    server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"))
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
