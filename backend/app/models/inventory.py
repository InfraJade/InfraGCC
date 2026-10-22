"""Sites, rooms, racks, collectors, servers and their parts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
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
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ComponentType, ServerStatus, check_in
from app.models.base import Base, TimestampMixin


class Site(TimestampMixin, Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(80))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")

    rooms: Mapped[list[Room]] = relationship(back_populates="site", order_by="Room.name")


class Room(TimestampMixin, Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("site_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    floor: Mapped[str | None] = mapped_column(String(32))

    site: Mapped[Site] = relationship(back_populates="rooms")
    racks: Mapped[list[Rack]] = relationship(back_populates="room", order_by="Rack.name")


class Rack(TimestampMixin, Base):
    __tablename__ = "racks"
    __table_args__ = (
        UniqueConstraint("room_id", "name"),
        CheckConstraint("height_u BETWEEN 1 AND 60", name="height_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    row: Mapped[str | None] = mapped_column(String(32))
    height_u: Mapped[int] = mapped_column(SmallInteger, default=42, server_default="42")
    power_capacity_w: Mapped[int | None] = mapped_column(Integer)

    room: Mapped[Room] = relationship(back_populates="racks")
    servers: Mapped[list[Server]] = relationship(back_populates="rack", order_by="Server.position_u")


class Collector(TimestampMixin, Base):
    __tablename__ = "collectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[str | None] = mapped_column(String(32))
    hostname: Mapped[str | None] = mapped_column(String(255))
    last_heartbeat: Mapped[datetime | None]
    cert_fingerprint: Mapped[str | None] = mapped_column(String(128), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))

    site: Mapped[Site] = relationship()


class Server(TimestampMixin, Base):
    __tablename__ = "servers"
    __table_args__ = (
        CheckConstraint(check_in("status", ServerStatus), name="status_valid"),
        CheckConstraint("position_u IS NULL OR position_u >= 1", name="position_positive"),
        CheckConstraint("height_u BETWEEN 1 AND 10", name="height_range"),
        Index("ix_servers_vendor_model", "vendor", "model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    rack_id: Mapped[int | None] = mapped_column(ForeignKey("racks.id", ondelete="SET NULL"), index=True)
    position_u: Mapped[int | None] = mapped_column(SmallInteger)
    height_u: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    name: Mapped[str | None] = mapped_column(String(128), index=True)
    vendor: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    serial: Mapped[str | None] = mapped_column(String(64), index=True)
    asset_tag: Mapped[str | None] = mapped_column(String(64))
    bmc_host: Mapped[str] = mapped_column(String(255), unique=True)
    bmc_mac: Mapped[str | None] = mapped_column(String(32))
    bmc_model: Mapped[str | None] = mapped_column(String(64))
    host_ips: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list, server_default="{}")
    collector_id: Mapped[int | None] = mapped_column(
        ForeignKey("collectors.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default=ServerStatus.ACTIVE.value, server_default=ServerStatus.ACTIVE.value
    )
    system_path: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime | None]
    last_seen_at: Mapped[datetime | None]

    rack: Mapped[Rack | None] = relationship(back_populates="servers")
    site: Mapped[Site] = relationship()
    collector: Mapped[Collector | None] = relationship()
    components: Mapped[list[Component]] = relationship(
        back_populates="server", order_by="(Component.type, Component.name)"
    )

    @property
    def display_name(self) -> str:
        return self.name or self.bmc_host


class Component(Base):
    __tablename__ = "components"
    __table_args__ = (
        UniqueConstraint("server_id", "type", "name"),
        CheckConstraint(check_in("type", ComponentType), name="type_valid"),
        Index("ix_components_type_model", "type", "model"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(128))
    manufacturer: Mapped[str | None] = mapped_column(String(128))
    serial: Mapped[str | None] = mapped_column(String(128))
    capacity: Mapped[float | None] = mapped_column(Float)
    capacity_unit: Mapped[str | None] = mapped_column(String(16))
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(128))
    expected_link_up: Mapped[bool | None] = mapped_column(Boolean)
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    removed_at: Mapped[datetime | None]

    server: Mapped[Server] = relationship(back_populates="components")
