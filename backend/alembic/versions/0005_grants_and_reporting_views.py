"""Least-privilege grants and the Superset reporting views.

Roles (created by infra/timescale/init, or by a DBA in staging/prod):
  gcc_app          app API, alert worker, scheduler: read/write on application tables
  gcc_ingest       ingest API: writes telemetry (readings, latest values, health, events, inventory, firmware);
                   may update only discovery columns on servers and heartbeat columns on collectors
  gcc_superset_ro  Superset: SELECT on the `reporting` views only, never the raw tables

Grants are skipped for roles that do not exist, so migrations also run on a bare database (CI).
The views read the rollups (readings_5m / readings_1h), never raw readings, per the design doc.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Common dimension columns for any row keyed by a server.
_SERVER_DIMS = """
    COALESCE(s.name, s.bmc_host) AS server_name,
    s.serial AS server_serial,
    s.site_id,
    st.code AS site_code,
    st.name AS site_name,
    rm.id AS room_id,
    rm.name AS room_name,
    r.id AS rack_id,
    r.name AS rack_name,
    s.position_u,
    s.vendor,
    s.model
"""

_SERVER_JOINS = """
    JOIN public.sites st ON st.id = s.site_id
    LEFT JOIN public.racks r ON r.id = s.rack_id
    LEFT JOIN public.rooms rm ON rm.id = r.room_id
"""

VIEWS: dict[str, str] = {
    "v_readings_5m": f"""
        SELECT a.bucket AS time,
               a.server_id,
               {_SERVER_DIMS},
               r.power_capacity_w AS rack_power_capacity_w,
               md.code AS metric,
               md.name AS metric_name,
               md.unit,
               md.category,
               a.component,
               a.avg_value,
               a.min_value,
               a.max_value,
               a.samples
        FROM public.readings_5m a
        JOIN public.servers s ON s.id = a.server_id
        {_SERVER_JOINS}
        JOIN public.metric_definitions md ON md.id = a.metric_code
    """,
    "v_readings_1h": f"""
        SELECT a.bucket AS time,
               a.server_id,
               {_SERVER_DIMS},
               r.power_capacity_w AS rack_power_capacity_w,
               md.code AS metric,
               md.name AS metric_name,
               md.unit,
               md.category,
               a.component,
               a.avg_value,
               a.min_value,
               a.max_value,
               a.samples
        FROM public.readings_1h a
        JOIN public.servers s ON s.id = a.server_id
        {_SERVER_JOINS}
        JOIN public.metric_definitions md ON md.id = a.metric_code
    """,
    "v_server_health": f"""
        SELECT h.server_id,
               {_SERVER_DIMS},
               s.status AS server_status,
               md.code AS metric,
               md.name AS metric_name,
               md.category,
               h.component,
               h.health,
               CASE h.health WHEN 'OK' THEN 0 WHEN 'Unknown' THEN 1 WHEN 'Warning' THEN 2 ELSE 3 END
                 AS health_rank,
               h.state,
               h.since,
               h.updated_at,
               CASE max(CASE h.health WHEN 'OK' THEN 0 WHEN 'Unknown' THEN 1 WHEN 'Warning' THEN 2 ELSE 3 END)
                      OVER (PARTITION BY h.server_id)
                 WHEN 0 THEN 'OK' WHEN 1 THEN 'Unknown' WHEN 2 THEN 'Warning' ELSE 'Critical' END
                 AS server_worst_health
        FROM public.health_status h
        JOIN public.servers s ON s.id = h.server_id
        {_SERVER_JOINS}
        JOIN public.metric_definitions md ON md.id = h.metric_code
        WHERE s.status <> 'decommissioned'
    """,
    "v_alerts": """
        SELECT a.id AS alert_id,
               a.rule_id,
               ar.name AS rule_name,
               ar.rule_type,
               ar.route,
               a.server_id,
               COALESCE(s.name, s.bmc_host) AS server_name,
               a.collector_id,
               c.name AS collector_name,
               a.site_id,
               st.code AS site_code,
               st.name AS site_name,
               rm.name AS room_name,
               r.name AS rack_name,
               s.vendor,
               s.model,
               md.code AS metric,
               a.component,
               a.state,
               a.severity,
               a.title,
               a.muted,
               a.occurrences,
               a.opened_at,
               a.acked_at,
               a.acked_by,
               a.resolved_at,
               EXTRACT(EPOCH FROM (a.acked_at - a.opened_at)) AS seconds_to_ack,
               EXTRACT(EPOCH FROM (a.resolved_at - a.opened_at)) AS seconds_to_resolve
        FROM public.alerts a
        JOIN public.alert_rules ar ON ar.id = a.rule_id
        LEFT JOIN public.servers s ON s.id = a.server_id
        LEFT JOIN public.collectors c ON c.id = a.collector_id
        LEFT JOIN public.sites st ON st.id = a.site_id
        LEFT JOIN public.racks r ON r.id = s.rack_id
        LEFT JOIN public.rooms rm ON rm.id = r.room_id
        LEFT JOIN public.metric_definitions md ON md.id = a.metric_code
    """,
    "v_inventory": f"""
        SELECT s.id AS server_id,
               {_SERVER_DIMS},
               s.height_u,
               s.status AS server_status,
               s.bmc_host,
               s.bmc_model,
               s.last_seen_at,
               c.id AS component_id,
               c.type AS component_type,
               c.name AS component_name,
               c.model AS component_model,
               c.manufacturer AS component_manufacturer,
               c.serial AS component_serial,
               c.capacity AS component_capacity,
               c.capacity_unit AS component_capacity_unit,
               c.firmware_version AS component_firmware
        FROM public.servers s
        {_SERVER_JOINS}
        LEFT JOIN public.components c ON c.server_id = s.id AND c.removed_at IS NULL
        WHERE s.status <> 'decommissioned'
    """,
    "v_firmware_compliance": f"""
        SELECT f.server_id,
               {_SERVER_DIMS},
               f.component,
               f.component_key,
               f.component_type,
               f.version AS installed_version,
               b.version AS approved_version,
               CASE WHEN b.version IS NULL THEN NULL ELSE b.version = f.version END AS compliant,
               f.collected_at
        FROM public.firmware_inventory f
        JOIN public.servers s ON s.id = f.server_id
        {_SERVER_JOINS}
        LEFT JOIN public.firmware_baselines b
               ON b.vendor = s.vendor AND b.model = s.model AND b.component = f.component_key
        WHERE s.status <> 'decommissioned'
    """,
}

GRANTS = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gcc_app') THEN
    GRANT USAGE ON SCHEMA public TO gcc_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO gcc_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO gcc_app;
    GRANT USAGE ON SCHEMA reporting TO gcc_app;
    GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO gcc_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO gcc_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO gcc_app;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gcc_ingest') THEN
    GRANT USAGE ON SCHEMA public TO gcc_ingest;
    GRANT SELECT ON sites, rooms, racks, servers, collectors, metric_definitions, app_settings TO gcc_ingest;
    GRANT SELECT, INSERT ON readings, events TO gcc_ingest;
    GRANT SELECT, INSERT, UPDATE ON latest_readings, health_status, bmc_thresholds, components,
                                    firmware_inventory TO gcc_ingest;
    GRANT UPDATE (name, vendor, model, serial, bmc_mac, bmc_model, host_ips, system_path,
                  discovered_at, last_seen_at, updated_at) ON servers TO gcc_ingest;
    GRANT UPDATE (last_heartbeat, version, hostname, stats, updated_at) ON collectors TO gcc_ingest;
    GRANT USAGE, SELECT ON SEQUENCE events_id_seq, components_id_seq TO gcc_ingest;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gcc_superset_ro') THEN
    GRANT USAGE ON SCHEMA reporting TO gcc_superset_ro;
    GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO gcc_superset_ro;
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM gcc_superset_ro;
  END IF;
END
$$;
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS reporting")
    for name, body in VIEWS.items():
        op.execute(f"CREATE VIEW reporting.{name} AS {body}")
    op.execute(GRANTS)


def downgrade() -> None:
    for name in reversed(list(VIEWS)):
        op.execute(f"DROP VIEW IF EXISTS reporting.{name}")
    op.execute("DROP SCHEMA IF EXISTS reporting")
