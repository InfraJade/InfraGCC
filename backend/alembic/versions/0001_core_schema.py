"""Core schema: every table in the design doc except the readings hypertable (see 0002).

Revision ID: 0001
Revises:
Create Date: 2026-10-22 14:12:57.195237
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "time", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("user_sub", sa.String(length=128), nullable=True),
        sa.Column("user_name", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=48), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_object", "audit_log", ["object_type", "object_id"], unique=False)
    op.create_index("ix_audit_log_time", "audit_log", ["time"], unique=False)
    op.create_index("ix_audit_log_user", "audit_log", ["user_sub"], unique=False)
    op.create_table(
        "firmware_baselines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vendor", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("component", sa.String(length=160), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_firmware_baselines")),
        sa.UniqueConstraint(
            "vendor", "model", "component", name=op.f("uq_firmware_baselines_vendor_model_component")
        ),
    )
    op.create_table(
        "metric_definitions",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=16), server_default="", nullable=False),
        sa.Column("interval_s", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("parameter_no", sa.SmallInteger(), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.CheckConstraint(
            "type IN ('gauge', 'state', 'event', 'version')", name=op.f("ck_metric_definitions_type_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_definitions")),
        sa.UniqueConstraint("code", name=op.f("uq_metric_definitions_code")),
    )
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("country", sa.String(length=80), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sites")),
        sa.UniqueConstraint("code", name=op.f("uq_sites_code")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sub", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("roles", sa.ARRAY(sa.String(length=32)), server_default="{}", nullable=False),
        sa.Column("sites", sa.ARRAY(sa.String(length=16)), nullable=True),
        sa.Column("last_session", sa.String(length=128), nullable=True),
        sa.Column("last_login_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("sub", name=op.f("uq_users_sub")),
    )
    op.create_table(
        "alert_routes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("route", sa.String(length=32), server_default="*", nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("min_severity", sa.String(length=16), server_default="Critical", nullable=False),
        sa.Column("escalation_level", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("target_encrypted", sa.Text(), nullable=False),
        sa.Column("target_hint", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("channel IN ('email', 'teams')", name=op.f("ck_alert_routes_channel_valid")),
        sa.CheckConstraint(
            "min_severity IN ('Info', 'Warning', 'Critical')", name=op.f("ck_alert_routes_min_severity_valid")
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_alert_routes_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_routes")),
    )
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("rule_type", sa.String(length=16), nullable=False),
        sa.Column("metric_code", sa.SmallInteger(), nullable=True),
        sa.Column(
            "condition",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("duration_s", sa.Integer(), server_default="0", nullable=False),
        sa.Column("severity", sa.String(length=16), server_default="Warning", nullable=False),
        sa.Column("route", sa.String(length=32), server_default="hardware", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("builtin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "rule_type IN ('threshold', 'state', 'missing_data', 'event', 'compliance')",
            name=op.f("ck_alert_rules_rule_type_valid"),
        ),
        sa.CheckConstraint(
            "severity IN ('Info', 'Warning', 'Critical')", name=op.f("ck_alert_rules_severity_valid")
        ),
        sa.CheckConstraint("duration_s >= 0", name=op.f("ck_alert_rules_duration_positive")),
        sa.ForeignKeyConstraint(
            ["metric_code"],
            ["metric_definitions.id"],
            name=op.f("fk_alert_rules_metric_code_metric_definitions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_rules")),
        sa.UniqueConstraint("name", name=op.f("uq_alert_rules_name")),
    )
    op.create_table(
        "collectors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("last_heartbeat", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cert_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_collectors_site_id_sites"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collectors")),
        sa.UniqueConstraint("cert_fingerprint", name=op.f("uq_collectors_cert_fingerprint")),
        sa.UniqueConstraint("name", name=op.f("uq_collectors_name")),
    )
    op.create_index(op.f("ix_collectors_site_id"), "collectors", ["site_id"], unique=False)
    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("floor", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_rooms_site_id_sites"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rooms")),
        sa.UniqueConstraint("site_id", "name", name=op.f("uq_rooms_site_id_name")),
    )
    op.create_index(op.f("ix_rooms_site_id"), "rooms", ["site_id"], unique=False)
    op.create_table(
        "racks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("row", sa.String(length=32), nullable=True),
        sa.Column("height_u", sa.SmallInteger(), server_default="42", nullable=False),
        sa.Column("power_capacity_w", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("height_u BETWEEN 1 AND 60", name=op.f("ck_racks_height_range")),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], name=op.f("fk_racks_room_id_rooms"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_racks")),
        sa.UniqueConstraint("room_id", "name", name=op.f("uq_racks_room_id_name")),
    )
    op.create_index(op.f("ix_racks_room_id"), "racks", ["room_id"], unique=False)
    op.create_table(
        "servers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("rack_id", sa.Integer(), nullable=True),
        sa.Column("position_u", sa.SmallInteger(), nullable=True),
        sa.Column("height_u", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("vendor", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("serial", sa.String(length=64), nullable=True),
        sa.Column("asset_tag", sa.String(length=64), nullable=True),
        sa.Column("bmc_host", sa.String(length=255), nullable=False),
        sa.Column("bmc_mac", sa.String(length=32), nullable=True),
        sa.Column("bmc_model", sa.String(length=64), nullable=True),
        sa.Column("host_ips", sa.ARRAY(sa.String(length=64)), server_default="{}", nullable=False),
        sa.Column("collector_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("system_path", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("discovered_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'maintenance', 'decommissioned')", name=op.f("ck_servers_status_valid")
        ),
        sa.CheckConstraint("height_u BETWEEN 1 AND 10", name=op.f("ck_servers_height_range")),
        sa.CheckConstraint(
            "position_u IS NULL OR position_u >= 1", name=op.f("ck_servers_position_positive")
        ),
        sa.ForeignKeyConstraint(
            ["collector_id"],
            ["collectors.id"],
            name=op.f("fk_servers_collector_id_collectors"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rack_id"], ["racks.id"], name=op.f("fk_servers_rack_id_racks"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_servers_site_id_sites"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_servers")),
        sa.UniqueConstraint("bmc_host", name=op.f("uq_servers_bmc_host")),
    )
    op.create_index(op.f("ix_servers_collector_id"), "servers", ["collector_id"], unique=False)
    op.create_index(op.f("ix_servers_name"), "servers", ["name"], unique=False)
    op.create_index(op.f("ix_servers_rack_id"), "servers", ["rack_id"], unique=False)
    op.create_index(op.f("ix_servers_serial"), "servers", ["serial"], unique=False)
    op.create_index(op.f("ix_servers_site_id"), "servers", ["site_id"], unique=False)
    op.create_index("ix_servers_vendor_model", "servers", ["vendor", "model"], unique=False)
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=True),
        sa.Column("collector_id", sa.Integer(), nullable=True),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("metric_code", sa.SmallInteger(), nullable=True),
        sa.Column("component", sa.Text(), server_default="", nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("muted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "opened_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "last_seen_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("acked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("acked_by", sa.String(length=128), nullable=True),
        sa.Column("resolved_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.Column("notified_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("escalated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "severity IN ('Info', 'Warning', 'Critical')", name=op.f("ck_alerts_severity_valid")
        ),
        sa.CheckConstraint(
            "state IN ('open', 'acknowledged', 'resolved')", name=op.f("ck_alerts_state_valid")
        ),
        sa.ForeignKeyConstraint(
            ["collector_id"],
            ["collectors.id"],
            name=op.f("fk_alerts_collector_id_collectors"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["metric_code"], ["metric_definitions.id"], name=op.f("fk_alerts_metric_code_metric_definitions")
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["alert_rules.id"], name=op.f("fk_alerts_rule_id_alert_rules"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], name=op.f("fk_alerts_server_id_servers"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_alerts_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index("ix_alerts_opened", "alerts", ["opened_at"], unique=False)
    op.create_index(op.f("ix_alerts_rule_id"), "alerts", ["rule_id"], unique=False)
    op.create_index(op.f("ix_alerts_server_id"), "alerts", ["server_id"], unique=False)
    op.create_index("ix_alerts_site_opened", "alerts", ["site_id", "opened_at"], unique=False)
    op.create_index("ix_alerts_state_severity", "alerts", ["state", "severity"], unique=False)
    op.create_index(
        "uq_alerts_active_dedupe",
        "alerts",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("state <> 'resolved'"),
    )
    op.create_table(
        "bmc_thresholds",
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.SmallInteger(), nullable=False),
        sa.Column("component", sa.Text(), server_default="", nullable=False),
        sa.Column("lower_critical", sa.Float(), nullable=True),
        sa.Column("lower_warning", sa.Float(), nullable=True),
        sa.Column("upper_warning", sa.Float(), nullable=True),
        sa.Column("upper_critical", sa.Float(), nullable=True),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["metric_code"],
            ["metric_definitions.id"],
            name=op.f("fk_bmc_thresholds_metric_code_metric_definitions"),
        ),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            name=op.f("fk_bmc_thresholds_server_id_servers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("server_id", "metric_code", "component", name=op.f("pk_bmc_thresholds")),
    )
    op.create_table(
        "components",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("manufacturer", sa.String(length=128), nullable=True),
        sa.Column("serial", sa.String(length=128), nullable=True),
        sa.Column("capacity", sa.Float(), nullable=True),
        sa.Column("capacity_unit", sa.String(length=16), nullable=True),
        sa.Column("firmware_version", sa.String(length=64), nullable=True),
        sa.Column("location", sa.String(length=128), nullable=True),
        sa.Column("expected_link_up", sa.Boolean(), nullable=True),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "first_seen_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("removed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('cpu', 'dimm', 'drive', 'psu', 'fan', 'nic', 'storage_controller', 'volume')",
            name=op.f("ck_components_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], name=op.f("fk_components_server_id_servers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_components")),
        sa.UniqueConstraint("server_id", "type", "name", name=op.f("uq_components_server_id_type_name")),
    )
    op.create_index(op.f("ix_components_server_id"), "components", ["server_id"], unique=False)
    op.create_index("ix_components_type_model", "components", ["type", "model"], unique=False)
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("time", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("message_id", sa.String(length=128), nullable=True),
        sa.Column("entry_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], name=op.f("fk_events_server_id_servers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint("server_id", "entry_id", name=op.f("uq_events_server_id_entry_id")),
    )
    op.create_index("ix_events_server_time", "events", ["server_id", "time"], unique=False)
    op.create_index("ix_events_time", "events", ["time"], unique=False)
    op.create_table(
        "firmware_inventory",
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("component", sa.Text(), nullable=False),
        sa.Column("component_key", sa.String(length=160), nullable=False),
        sa.Column("component_type", sa.String(length=24), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("collected_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            name=op.f("fk_firmware_inventory_server_id_servers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("server_id", "component", name=op.f("pk_firmware_inventory")),
    )
    op.create_index(
        op.f("ix_firmware_inventory_component_key"), "firmware_inventory", ["component_key"], unique=False
    )
    op.create_table(
        "health_status",
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.SmallInteger(), nullable=False),
        sa.Column("component", sa.Text(), server_default="", nullable=False),
        sa.Column("health", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=True),
        sa.Column("since", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "health IN ('OK', 'Warning', 'Critical', 'Unknown')", name=op.f("ck_health_status_health_valid")
        ),
        sa.ForeignKeyConstraint(
            ["metric_code"],
            ["metric_definitions.id"],
            name=op.f("fk_health_status_metric_code_metric_definitions"),
        ),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], name=op.f("fk_health_status_server_id_servers"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("server_id", "metric_code", "component", name=op.f("pk_health_status")),
    )
    op.create_table(
        "latest_readings",
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.SmallInteger(), nullable=False),
        sa.Column("component", sa.Text(), server_default="", nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("time", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["metric_code"],
            ["metric_definitions.id"],
            name=op.f("fk_latest_readings_metric_code_metric_definitions"),
        ),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            name=op.f("fk_latest_readings_server_id_servers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("server_id", "metric_code", "component", name=op.f("pk_latest_readings")),
    )
    op.create_table(
        "maintenance_windows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("rack_id", sa.Integer(), nullable=True),
        sa.Column("server_id", sa.Integer(), nullable=True),
        sa.Column("starts_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ends_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "(scope = 'site' AND site_id IS NOT NULL) OR (scope = 'rack' AND rack_id IS NOT NULL) OR (scope = 'server' AND server_id IS NOT NULL)",
            name=op.f("ck_maintenance_windows_scope_target"),
        ),
        sa.CheckConstraint(
            "scope IN ('site', 'rack', 'server')", name=op.f("ck_maintenance_windows_scope_valid")
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_maintenance_windows_ends_after_start")),
        sa.ForeignKeyConstraint(
            ["rack_id"], ["racks.id"], name=op.f("fk_maintenance_windows_rack_id_racks"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            name=op.f("fk_maintenance_windows_server_id_servers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_maintenance_windows_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_windows")),
    )
    op.create_index(
        "ix_maintenance_windows_period", "maintenance_windows", ["starts_at", "ends_at"], unique=False
    )
    op.create_table(
        "thresholds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.SmallInteger(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("server_id", sa.Integer(), nullable=True),
        sa.Column("vendor", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("direction", sa.String(length=24), server_default="above", nullable=False),
        sa.Column("warning", sa.Float(), nullable=True),
        sa.Column("critical", sa.Float(), nullable=True),
        sa.Column("nominal", sa.Float(), nullable=True),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND site_id IS NULL AND server_id IS NULL AND model IS NULL) OR (scope = 'site' AND site_id IS NOT NULL AND server_id IS NULL) OR (scope = 'server' AND server_id IS NOT NULL) OR (scope = 'model' AND model IS NOT NULL AND server_id IS NULL AND site_id IS NULL)",
            name=op.f("ck_thresholds_scope_target"),
        ),
        sa.CheckConstraint(
            "direction IN ('above', 'below', 'deviation_pct', 'pct_of_capacity')",
            name=op.f("ck_thresholds_direction_valid"),
        ),
        sa.CheckConstraint(
            "scope IN ('global', 'model', 'site', 'server')", name=op.f("ck_thresholds_scope_valid")
        ),
        sa.CheckConstraint(
            "warning IS NOT NULL OR critical IS NOT NULL", name=op.f("ck_thresholds_has_limit")
        ),
        sa.ForeignKeyConstraint(
            ["metric_code"],
            ["metric_definitions.id"],
            name=op.f("fk_thresholds_metric_code_metric_definitions"),
        ),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], name=op.f("fk_thresholds_server_id_servers"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_thresholds_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_thresholds")),
    )
    op.create_index(op.f("ix_thresholds_metric_code"), "thresholds", ["metric_code"], unique=False)
    op.create_index(
        "uq_thresholds_target",
        "thresholds",
        [
            "metric_code",
            "scope",
            sa.literal_column("coalesce(site_id, 0)"),
            sa.literal_column("coalesce(server_id, 0)"),
            sa.literal_column("coalesce(vendor, '')"),
            sa.literal_column("coalesce(model, '')"),
        ],
        unique=True,
    )
    op.create_table(
        "alert_activity",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("alert_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "time", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor", sa.String(length=128), server_default="system", nullable=False),
        sa.Column("actor_sub", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("from_state", sa.String(length=16), nullable=True),
        sa.Column("to_state", sa.String(length=16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["alerts.id"], name=op.f("fk_alert_activity_alert_id_alerts"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_activity")),
    )
    op.create_index(op.f("ix_alert_activity_alert_id"), "alert_activity", ["alert_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_alert_activity_alert_id"), table_name="alert_activity")
    op.drop_table("alert_activity")
    op.drop_index("uq_thresholds_target", table_name="thresholds")
    op.drop_index(op.f("ix_thresholds_metric_code"), table_name="thresholds")
    op.drop_table("thresholds")
    op.drop_index("ix_maintenance_windows_period", table_name="maintenance_windows")
    op.drop_table("maintenance_windows")
    op.drop_table("latest_readings")
    op.drop_table("health_status")
    op.drop_index(op.f("ix_firmware_inventory_component_key"), table_name="firmware_inventory")
    op.drop_table("firmware_inventory")
    op.drop_index("ix_events_time", table_name="events")
    op.drop_index("ix_events_server_time", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_components_type_model", table_name="components")
    op.drop_index(op.f("ix_components_server_id"), table_name="components")
    op.drop_table("components")
    op.drop_table("bmc_thresholds")
    op.drop_index(
        "uq_alerts_active_dedupe", table_name="alerts", postgresql_where=sa.text("state <> 'resolved'")
    )
    op.drop_index("ix_alerts_state_severity", table_name="alerts")
    op.drop_index("ix_alerts_site_opened", table_name="alerts")
    op.drop_index(op.f("ix_alerts_server_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_rule_id"), table_name="alerts")
    op.drop_index("ix_alerts_opened", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_servers_vendor_model", table_name="servers")
    op.drop_index(op.f("ix_servers_site_id"), table_name="servers")
    op.drop_index(op.f("ix_servers_serial"), table_name="servers")
    op.drop_index(op.f("ix_servers_rack_id"), table_name="servers")
    op.drop_index(op.f("ix_servers_name"), table_name="servers")
    op.drop_index(op.f("ix_servers_collector_id"), table_name="servers")
    op.drop_table("servers")
    op.drop_index(op.f("ix_racks_room_id"), table_name="racks")
    op.drop_table("racks")
    op.drop_index(op.f("ix_rooms_site_id"), table_name="rooms")
    op.drop_table("rooms")
    op.drop_index(op.f("ix_collectors_site_id"), table_name="collectors")
    op.drop_table("collectors")
    op.drop_table("alert_rules")
    op.drop_table("alert_routes")
    op.drop_table("users")
    op.drop_table("sites")
    op.drop_table("metric_definitions")
    op.drop_table("firmware_baselines")
    op.drop_index("ix_audit_log_user", table_name="audit_log")
    op.drop_index("ix_audit_log_time", table_name="audit_log")
    op.drop_index("ix_audit_log_object", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("app_settings")
