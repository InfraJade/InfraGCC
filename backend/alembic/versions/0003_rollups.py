"""Continuous aggregates: 5-minute and 1-hour average/min/max, with refresh, compression and retention.

- readings_5m: built from raw readings, refreshed every 5 minutes, kept 13 months (395 days).
- readings_1h: hierarchical aggregate over readings_5m, refreshed every 30 minutes, kept 3 years (1095 days).

Both are real-time aggregates (materialized_only = false), so the newest, not-yet-materialized buckets
are computed on the fly and live charts never show a gap. The 5-minute refresh window reaches back
2 days so readings replayed from a collector's 24-hour disk buffer are folded in.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW readings_5m
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT time_bucket(INTERVAL '5 minutes', time) AS bucket,
               server_id,
               metric_code,
               component,
               avg(value)   AS avg_value,
               min(value)   AS min_value,
               max(value)   AS max_value,
               count(value) AS samples
        FROM readings
        GROUP BY bucket, server_id, metric_code, component
        WITH NO DATA
        """
    )
    op.execute(
        "CREATE INDEX ix_readings_5m_server_metric_bucket ON readings_5m (server_id, metric_code, bucket DESC)"
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('readings_5m',
          start_offset => INTERVAL '2 days',
          end_offset => INTERVAL '5 minutes',
          schedule_interval => INTERVAL '5 minutes')
        """
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW readings_1h
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT time_bucket(INTERVAL '1 hour', bucket) AS bucket,
               server_id,
               metric_code,
               component,
               sum(avg_value * samples) / NULLIF(sum(samples), 0) AS avg_value,
               min(min_value)  AS min_value,
               max(max_value)  AS max_value,
               sum(samples)::bigint AS samples
        FROM readings_5m
        GROUP BY 1, server_id, metric_code, component
        WITH NO DATA
        """
    )
    op.execute(
        "CREATE INDEX ix_readings_1h_server_metric_bucket ON readings_1h (server_id, metric_code, bucket DESC)"
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('readings_1h',
          start_offset => INTERVAL '3 days',
          end_offset => INTERVAL '1 hour',
          schedule_interval => INTERVAL '30 minutes')
        """
    )

    # Compression for the rollups once they are well past their refresh windows.
    op.execute("ALTER MATERIALIZED VIEW readings_5m SET (timescaledb.compress = true)")
    op.execute("SELECT add_compression_policy('readings_5m', compress_after => INTERVAL '30 days')")
    op.execute("ALTER MATERIALIZED VIEW readings_1h SET (timescaledb.compress = true)")
    op.execute("SELECT add_compression_policy('readings_1h', compress_after => INTERVAL '30 days')")

    op.execute("SELECT add_retention_policy('readings_5m', drop_after => INTERVAL '395 days')")
    op.execute("SELECT add_retention_policy('readings_1h', drop_after => INTERVAL '1095 days')")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS readings_1h")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS readings_5m")
