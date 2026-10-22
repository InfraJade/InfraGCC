"""Firmware inventory and baselines, audit log, users, and small app settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ARRAY, BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FirmwareInventory(Base):
    __tablename__ = "firmware_inventory"

    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True)
    # Instance name as the BMC reports it, e.g. "BIOS", "Integrated Dell Remote Access Controller", "Disk 0".
    component: Mapped[str] = mapped_column(Text, primary_key=True)
    # Normalized key used to match baselines, e.g. "BIOS", "BMC", "DRIVE:MZ7LH960HAJR0D3".
    component_key: Mapped[str] = mapped_column(String(160), index=True)
    component_type: Mapped[str] = mapped_column(String(24))
    version: Mapped[str] = mapped_column(String(128))
    collected_at: Mapped[datetime]


class FirmwareBaseline(Base):
    __tablename__ = "firmware_baselines"
    __table_args__ = (UniqueConstraint("vendor", "model", "component"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    component: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_time", "time"),
        Index("ix_audit_log_object", "object_type", "object_id"),
        Index("ix_audit_log_user", "user_sub"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    time: Mapped[datetime] = mapped_column(server_default=func.now())
    user_sub: Mapped[str | None] = mapped_column(String(128))
    user_name: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    object_type: Mapped[str] = mapped_column(String(48))
    object_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))


class User(Base):
    """People who have signed in. Roles and sites mirror the IdP groups in their latest token."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sub: Mapped[str] = mapped_column(String(128), unique=True)
    email: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list, server_default="{}")
    # NULL means unrestricted (all sites).
    sites: Mapped[list[str] | None] = mapped_column(ARRAY(String(16)))
    last_session: Mapped[str | None] = mapped_column(String(128))
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


__all__ = ["AppSetting", "AuditLog", "FirmwareBaseline", "FirmwareInventory", "User"]
