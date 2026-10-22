"""Metric definitions, thresholds, readings (hypertable), latest values, health and events."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Health, MetricType, ThresholdDirection, ThresholdScope, check_in
from app.models.base import Base


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"
    __table_args__ = (CheckConstraint(check_in("type", MetricType), name="type_valid"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(48), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(16), default="", server_default="")
    interval_s: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(16))
    parameter_no: Mapped[int] = mapped_column(SmallInteger)
    category: Mapped[str] = mapped_column(String(24))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")


class Threshold(Base):
    """Admin-set alert limits. Precedence: server > site > model > global (> BMC-reported limits)."""

    __tablename__ = "thresholds"
    __table_args__ = (
        CheckConstraint(check_in("scope", ThresholdScope), name="scope_valid"),
        CheckConstraint(check_in("direction", ThresholdDirection), name="direction_valid"),
        CheckConstraint(
            "(scope = 'global' AND site_id IS NULL AND server_id IS NULL AND model IS NULL)"
            " OR (scope = 'site' AND site_id IS NOT NULL AND server_id IS NULL)"
            " OR (scope = 'server' AND server_id IS NOT NULL)"
            " OR (scope = 'model' AND model IS NOT NULL AND server_id IS NULL AND site_id IS NULL)",
            name="scope_target",
        ),
        CheckConstraint("warning IS NOT NULL OR critical IS NOT NULL", name="has_limit"),
        Index(
            "uq_thresholds_target",
            "metric_code",
            "scope",
            text("coalesce(site_id, 0)"),
            text("coalesce(server_id, 0)"),
            text("coalesce(vendor, '')"),
            text("coalesce(model, '')"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_code: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), index=True)
    scope: Mapped[str] = mapped_column(String(16))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"))
    vendor: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    direction: Mapped[str] = mapped_column(
        String(24), default=ThresholdDirection.ABOVE.value, server_default=ThresholdDirection.ABOVE.value
    )
    warning: Mapped[float | None] = mapped_column(Float)
    critical: Mapped[float | None] = mapped_column(Float)
    nominal: Mapped[float | None] = mapped_column(Float)
    updated_by: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class BmcThreshold(Base):
    """Limits the BMC itself reports per sensor (UpperThresholdCritical and friends)."""

    __tablename__ = "bmc_thresholds"

    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True)
    metric_code: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), primary_key=True)
    component: Mapped[str] = mapped_column(Text, primary_key=True, default="", server_default="")
    lower_critical: Mapped[float | None] = mapped_column(Float)
    lower_warning: Mapped[float | None] = mapped_column(Float)
    upper_warning: Mapped[float | None] = mapped_column(Float)
    upper_critical: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


# The readings hypertable has no primary key, so it is mapped as a Core table (written with COPY).
readings = Table(
    "readings",
    Base.metadata,
    Column("time", TIMESTAMP(timezone=True), nullable=False),
    Column("server_id", Integer, ForeignKey("servers.id"), nullable=False),
    Column("metric_code", SmallInteger, ForeignKey("metric_definitions.id"), nullable=False),
    Column("component", Text, nullable=False, server_default=""),
    Column("value", Float),
    Column("status", Text),
)


class LatestReading(Base):
    __tablename__ = "latest_readings"

    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True)
    metric_code: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), primary_key=True)
    component: Mapped[str] = mapped_column(Text, primary_key=True, default="", server_default="")
    value: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(Text)
    time: Mapped[datetime]


class HealthStatus(Base):
    __tablename__ = "health_status"
    __table_args__ = (CheckConstraint(check_in("health", Health), name="health_valid"),)

    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True)
    metric_code: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), primary_key=True)
    component: Mapped[str] = mapped_column(Text, primary_key=True, default="", server_default="")
    health: Mapped[str] = mapped_column(String(16))
    state: Mapped[str | None] = mapped_column(String(64))
    since: Mapped[datetime]
    updated_at: Mapped[datetime]


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("server_id", "entry_id"),
        Index("ix_events_server_time", "server_id", "time"),
        Index("ix_events_time", "time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"))
    time: Mapped[datetime]
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String(128))
    entry_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
