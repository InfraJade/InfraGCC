"""The 30-day queries behind the Superset dashboards, run as `gcc_superset_ro` against the reporting views.

Superset builds its SQL from chart definitions; these are hand-written equivalents of the heaviest 30-day
charts on each time-series dashboard (DESIGN "Dashboards"), in the shape Superset emits: a time grain,
GROUP BY dimensions, a metric aggregate and a row limit. Charts at hour/day grain read `v_readings_1h`;
the 5-minute charts (server drill-down, site power at full resolution) read `v_readings_5m`, which is the
worst case. Two queries add the `site_id` filter a guest token's row-level security adds for site-scoped
users.

Parameters: $1 = range start (timestamptz). Site- and server-scoped queries also take $2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Scope = Literal["fleet", "site", "server"]


@dataclass(frozen=True)
class DashboardQuery:
    name: str
    dashboard: str
    description: str
    view: str
    scope: Scope
    sql: str


ROW_LIMIT = 10000

QUERIES: list[DashboardQuery] = [
    DashboardQuery(
        "dc_overview_temp_power_daily",
        "dc-overview",
        "Daily average inlet temperature and total power draw per site",
        "v_readings_1h",
        "fleet",
        f"""
        SELECT date_trunc('day', time) AS __timestamp, site_code, metric,
               avg(avg_value) AS avg_value, max(max_value) AS max_value
        FROM reporting.v_readings_1h
        WHERE time >= $1 AND metric IN ('inlet_temp_c', 'power_w')
        GROUP BY 1, 2, 3
        ORDER BY 1
        LIMIT {ROW_LIMIT}
        """,
    ),
    DashboardQuery(
        "thermal_inlet_by_site_hourly",
        "thermal",
        "Hourly inlet temperature (avg and max) per site and room",
        "v_readings_1h",
        "fleet",
        f"""
        SELECT time AS __timestamp, site_code, room_name,
               avg(avg_value) AS avg_inlet, max(max_value) AS max_inlet
        FROM reporting.v_readings_1h
        WHERE time >= $1 AND metric = 'inlet_temp_c'
        GROUP BY 1, 2, 3
        ORDER BY 1
        LIMIT {ROW_LIMIT}
        """,
    ),
    DashboardQuery(
        "thermal_hot_spots",
        "thermal",
        "Top 20 racks by peak inlet temperature",
        "v_readings_1h",
        "fleet",
        """
        SELECT site_code, room_name, rack_name,
               max(max_value) AS peak_inlet, avg(avg_value) AS avg_inlet
        FROM reporting.v_readings_1h
        WHERE time >= $1 AND metric = 'inlet_temp_c'
        GROUP BY 1, 2, 3
        ORDER BY peak_inlet DESC
        LIMIT 20
        """,
    ),
    DashboardQuery(
        "thermal_fan_speed_by_model",
        "thermal",
        "Daily average fan speed per vendor and model",
        "v_readings_1h",
        "fleet",
        f"""
        SELECT date_trunc('day', time) AS __timestamp, vendor, model, avg(avg_value) AS avg_rpm
        FROM reporting.v_readings_1h
        WHERE time >= $1 AND metric = 'fan_rpm'
        GROUP BY 1, 2, 3
        ORDER BY 1
        LIMIT {ROW_LIMIT}
        """,
    ),
    DashboardQuery(
        "power_rack_daily_peak",
        "power-capacity",
        "Daily peak rack power against rack capacity (headroom)",
        "v_readings_1h",
        "fleet",
        f"""
        WITH per_hour AS (
          SELECT time, site_code, rack_name, max(rack_power_capacity_w) AS capacity_w,
                 sum(avg_value) AS rack_w
          FROM reporting.v_readings_1h
          WHERE time >= $1 AND metric = 'power_w'
          GROUP BY 1, 2, 3
        )
        SELECT date_trunc('day', time) AS __timestamp, site_code, rack_name,
               max(rack_w) AS peak_w, max(capacity_w) AS capacity_w,
               max(capacity_w) - max(rack_w) AS headroom_w
        FROM per_hour
        GROUP BY 1, 2, 3
        ORDER BY 1
        LIMIT {ROW_LIMIT}
        """,
    ),
    DashboardQuery(
        "power_site_5m",
        "power-capacity",
        "Site power draw at 5-minute resolution over 30 days (full-resolution zoom)",
        "v_readings_5m",
        "fleet",
        f"""
        SELECT time AS __timestamp, site_code, sum(avg_value) AS site_w
        FROM reporting.v_readings_5m
        WHERE time >= $1 AND metric = 'power_w'
        GROUP BY 1, 2
        ORDER BY 1
        LIMIT {ROW_LIMIT}
        """,
    ),
    DashboardQuery(
        "thermal_site_scoped_hourly",
        "thermal",
        "Hourly inlet per rack for one site (guest-token row-level security)",
        "v_readings_1h",
        "site",
        f"""
        SELECT time AS __timestamp, rack_name, avg(avg_value) AS avg_inlet, max(max_value) AS max_inlet
        FROM reporting.v_readings_1h
        WHERE time >= $1 AND metric = 'inlet_temp_c' AND site_id = $2
        GROUP BY 1, 2
        ORDER BY 1
        LIMIT {ROW_LIMIT}
        """,
    ),
    DashboardQuery(
        "server_detail_5m",
        "hardware-health",
        "One server, every metric and part, 5-minute resolution over 30 days",
        "v_readings_5m",
        "server",
        f"""
        SELECT time AS __timestamp, metric, component, avg_value, min_value, max_value
        FROM reporting.v_readings_5m
        WHERE time >= $1 AND server_id = $2
        ORDER BY 1
        LIMIT {ROW_LIMIT * 10}
        """,
    ),
]
