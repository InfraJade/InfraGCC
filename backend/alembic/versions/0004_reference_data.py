"""Reference data: metric definitions for the 20 parameters, default thresholds and default alert rules.

The data is written out literally (not imported from app code) so this migration keeps meaning the same
thing as the code evolves.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (id, code, name, unit, interval_s, type, parameter_no, category, description)
METRICS: list[tuple[int, str, str, str, int, str, int, str, str]] = [
    (
        1,
        "inlet_temp_c",
        "Inlet temperature",
        "°C",
        60,
        "gauge",
        1,
        "thermal",
        "Ambient air entering the server (ThermalMetrics / Thermal.Temperatures).",
    ),
    (2, "exhaust_temp_c", "Exhaust temperature", "°C", 60, "gauge", 2, "thermal", "Air leaving the server."),
    (3, "cpu_temp_c", "CPU temperature", "°C", 60, "gauge", 3, "thermal", "Per CPU package."),
    (4, "dimm_temp_c", "Memory temperature", "°C", 60, "gauge", 4, "thermal", "Per DIMM or memory zone."),
    (5, "fan_rpm", "Fan speed", "RPM", 60, "gauge", 5, "cooling", "Per fan, when the BMC reports RPM."),
    (
        6,
        "fan_pct",
        "Fan speed (percent)",
        "%",
        60,
        "gauge",
        5,
        "cooling",
        "Per fan, when the BMC reports percent of maximum.",
    ),
    (7, "fan_health", "Fan health", "", 300, "state", 6, "cooling", "Fan Status.Health."),
    (8, "fan_redundancy", "Fan redundancy", "", 300, "state", 6, "cooling", "Thermal.Redundancy status."),
    (
        9,
        "power_w",
        "Power draw",
        "W",
        60,
        "gauge",
        7,
        "power",
        "Chassis power consumption (EnvironmentMetrics or Power.PowerControl).",
    ),
    (
        10,
        "power_capacity_w",
        "Power capacity",
        "W",
        300,
        "gauge",
        7,
        "power",
        "Available power capacity reported by the chassis.",
    ),
    (11, "power_limit_w", "Power cap", "W", 300, "gauge", 7, "power", "Configured power limit, if any."),
    (
        12,
        "psu_health",
        "Power supply health",
        "",
        300,
        "state",
        8,
        "power",
        "Per power supply Status.Health.",
    ),
    (
        13,
        "psu_input_v",
        "Power supply input voltage",
        "V",
        60,
        "gauge",
        9,
        "power",
        "Line input voltage per power supply.",
    ),
    (
        14,
        "psu_redundancy",
        "Power supply redundancy",
        "",
        300,
        "state",
        10,
        "power",
        "Power.Redundancy or PowerSubsystem redundancy status.",
    ),
    (15, "power_state", "Power state", "", 60, "state", 11, "power", "Systems PowerState: 1 = On, 0 = Off."),
    (
        16,
        "system_health",
        "Overall system health",
        "",
        60,
        "state",
        12,
        "health",
        "Systems Status.HealthRollup.",
    ),
    (17, "cpu_health", "CPU health", "", 300, "state", 13, "health", "Per processor Status.Health."),
    (18, "memory_health", "Memory health", "", 300, "state", 14, "health", "Per DIMM Status.Health."),
    (19, "drive_health", "Drive health", "", 300, "state", 15, "storage", "Per drive Status.Health."),
    (
        20,
        "drive_life_pct",
        "Drive life left",
        "%",
        300,
        "gauge",
        15,
        "storage",
        "PredictedMediaLifeLeftPercent per drive.",
    ),
    (
        21,
        "storage_health",
        "RAID controller health",
        "",
        300,
        "state",
        16,
        "storage",
        "Storage controller Status.Health.",
    ),
    (22, "volume_health", "Volume health", "", 300, "state", 16, "storage", "Per volume Status.Health."),
    (
        23,
        "nic_link",
        "NIC link status",
        "",
        300,
        "state",
        17,
        "network",
        "EthernetInterfaces LinkStatus: 1 = Up, 0 = Down.",
    ),
    (24, "bmc_health", "BMC health", "", 60, "state", 18, "bmc", "Managers Status.Health."),
    (
        25,
        "bmc_reachable",
        "BMC reachable",
        "",
        60,
        "state",
        18,
        "bmc",
        "1 when the poll succeeded, 0 when the BMC did not answer.",
    ),
    (26, "sel_event", "System event log", "", 300, "event", 19, "events", "New LogServices entries."),
    (
        27,
        "firmware_version",
        "Firmware version",
        "",
        86400,
        "version",
        20,
        "firmware",
        "UpdateService/FirmwareInventory versions (BIOS, BMC, drives and more).",
    ),
]

# (metric_id, direction, warning, critical) — the doc's explicit defaults. Metrics whose default is
# "BMC's own thresholds" have no global row; the BMC-reported limits apply to them.
THRESHOLDS: list[tuple[int, str, float | None, float | None]] = [
    (1, "above", 27.0, 35.0),  # ASHRAE recommended / common allowable
    (9, "pct_of_capacity", 90.0, 100.0),  # above 90 % of capacity or power cap
    (13, "deviation_pct", 10.0, None),  # more than 10 % from nominal
    (20, "below", 10.0, None),  # drive life left under 10 %
]

HEALTH: dict[str, Any] = {"match": "health", "levels": ["Warning", "Critical"]}

# (name, rule_type, metric_id, condition, duration_s, severity, route, description)
RULES: list[tuple[str, str, int | None, dict[str, Any], int, str, str, str]] = [
    (
        "Inlet temperature high",
        "threshold",
        1,
        {},
        180,
        "Warning",
        "facilities",
        "Inlet above the warning or critical limit for 3 minutes.",
    ),
    (
        "Exhaust temperature high",
        "threshold",
        2,
        {"bmc_limits": "upper"},
        180,
        "Warning",
        "hardware",
        "Exhaust above the BMC's limits (or an admin override) for 3 minutes.",
    ),
    (
        "CPU temperature high",
        "threshold",
        3,
        {"bmc_limits": "upper"},
        180,
        "Warning",
        "hardware",
        "CPU above the BMC's limits for 3 minutes.",
    ),
    (
        "Memory temperature high",
        "threshold",
        4,
        {"bmc_limits": "upper"},
        180,
        "Warning",
        "hardware",
        "DIMM above the BMC's limits for 3 minutes.",
    ),
    (
        "Fan speed low",
        "threshold",
        5,
        {"bmc_limits": "lower"},
        120,
        "Warning",
        "hardware",
        "Fan below the BMC's lower threshold for 2 minutes.",
    ),
    ("Fan failed", "state", 7, HEALTH, 0, "Warning", "hardware", "A fan reports Warning or Critical."),
    ("Fan redundancy lost", "state", 8, HEALTH, 0, "Warning", "hardware", "Fan redundancy is not OK."),
    (
        "Power draw near capacity",
        "threshold",
        9,
        {},
        300,
        "Warning",
        "facilities",
        "Power draw above 90 % of capacity or power cap for 5 minutes.",
    ),
    (
        "Power supply unhealthy",
        "state",
        12,
        HEALTH,
        0,
        "Warning",
        "hardware",
        "A power supply reports Warning or Critical.",
    ),
    (
        "Power supply voltage out of range",
        "threshold",
        13,
        {},
        180,
        "Warning",
        "facilities",
        "Input voltage more than 10 % from nominal for 3 minutes.",
    ),
    (
        "Power supply redundancy lost",
        "state",
        14,
        HEALTH,
        0,
        "Warning",
        "hardware",
        "Power supply redundancy is not OK.",
    ),
    (
        "Server powered off",
        "state",
        15,
        {"match": "value", "equals": 0, "outside_maintenance_only": True},
        120,
        "Critical",
        "hardware",
        "Power state is Off outside a maintenance window.",
    ),
    (
        "System health degraded",
        "state",
        16,
        HEALTH,
        120,
        "Warning",
        "hardware",
        "Systems HealthRollup is Warning or Critical for 2 minutes.",
    ),
    (
        "CPU unhealthy",
        "state",
        17,
        HEALTH,
        0,
        "Warning",
        "hardware",
        "A processor reports Warning or Critical.",
    ),
    (
        "Memory module unhealthy",
        "state",
        18,
        HEALTH,
        0,
        "Warning",
        "hardware",
        "A DIMM reports Warning or Critical.",
    ),
    (
        "Drive unhealthy",
        "state",
        19,
        HEALTH,
        0,
        "Warning",
        "hardware",
        "A drive reports Warning or Critical.",
    ),
    (
        "Drive wear-out",
        "threshold",
        20,
        {},
        0,
        "Warning",
        "hardware",
        "Predicted media life left under 10 %.",
    ),
    (
        "RAID controller degraded",
        "state",
        21,
        HEALTH,
        0,
        "Warning",
        "hardware",
        "A storage controller is degraded.",
    ),
    ("Volume degraded", "state", 22, HEALTH, 0, "Warning", "hardware", "A RAID volume is degraded."),
    (
        "NIC link down",
        "state",
        23,
        {"match": "value", "equals": 0, "expected_only": True},
        0,
        "Warning",
        "hardware",
        "A NIC port that is expected to be up reports link down.",
    ),
    (
        "BMC unreachable",
        "state",
        25,
        {"match": "value", "equals": 0, "consecutive": 3},
        0,
        "Critical",
        "platform",
        "Three failed polls in a row.",
    ),
    ("BMC unhealthy", "state", 24, HEALTH, 300, "Warning", "platform", "Managers Status is not OK."),
    (
        "Critical system event",
        "event",
        26,
        {"severities": ["Critical"]},
        0,
        "Critical",
        "hardware",
        "A new Critical entry in the system event log.",
    ),
    (
        "Server not reporting",
        "missing_data",
        None,
        {"target": "server", "polls": 3},
        180,
        "Critical",
        "platform",
        "No readings from a server for 3 polls.",
    ),
    (
        "Collector heartbeat missing",
        "missing_data",
        None,
        {"target": "collector", "after_s": 120},
        120,
        "Critical",
        "platform",
        "No collector heartbeat for 2 minutes.",
    ),
    (
        "Firmware off baseline",
        "compliance",
        27,
        {},
        0,
        "Warning",
        "hardware",
        "Installed firmware differs from the approved baseline (checked daily).",
    ),
]


def upgrade() -> None:
    metric_table = sa.table(
        "metric_definitions",
        sa.column("id", sa.SmallInteger),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("unit", sa.String),
        sa.column("interval_s", sa.Integer),
        sa.column("type", sa.String),
        sa.column("parameter_no", sa.SmallInteger),
        sa.column("category", sa.String),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(
        metric_table,
        [
            dict(
                zip(
                    (
                        "id",
                        "code",
                        "name",
                        "unit",
                        "interval_s",
                        "type",
                        "parameter_no",
                        "category",
                        "description",
                    ),
                    row,
                    strict=True,
                )
            )
            for row in METRICS
        ],
    )

    threshold_table = sa.table(
        "thresholds",
        sa.column("metric_code", sa.SmallInteger),
        sa.column("scope", sa.String),
        sa.column("direction", sa.String),
        sa.column("warning", sa.Float),
        sa.column("critical", sa.Float),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(
        threshold_table,
        [
            {
                "metric_code": m,
                "scope": "global",
                "direction": d,
                "warning": w,
                "critical": c,
                "updated_by": "system",
            }
            for m, d, w, c in THRESHOLDS
        ],
    )

    rule_table = sa.table(
        "alert_rules",
        sa.column("name", sa.String),
        sa.column("rule_type", sa.String),
        sa.column("metric_code", sa.SmallInteger),
        sa.column("condition", JSONB),
        sa.column("duration_s", sa.Integer),
        sa.column("severity", sa.String),
        sa.column("route", sa.String),
        sa.column("description", sa.Text),
        sa.column("builtin", sa.Boolean),
        sa.column("updated_by", sa.String),
    )
    op.bulk_insert(
        rule_table,
        [
            {
                "name": n,
                "rule_type": t,
                "metric_code": m,
                "condition": c,
                "duration_s": d,
                "severity": s,
                "route": r,
                "description": desc,
                "builtin": True,
                "updated_by": "system",
            }
            for n, t, m, c, d, s, r, desc in RULES
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM alert_rules WHERE builtin")
    op.execute("DELETE FROM thresholds WHERE scope = 'global' AND updated_by = 'system'")
    op.execute("DELETE FROM metric_definitions")
