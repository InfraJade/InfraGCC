"""Readings hypertable, exactly as specified in the design doc, with compression and retention.

Raw readings: 1-day chunks, compressed after 7 days, kept for 30 days.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE readings (
          time        timestamptz      NOT NULL,
          server_id   integer          NOT NULL REFERENCES servers(id),
          metric_code smallint         NOT NULL REFERENCES metric_definitions(id),
          component   text             NOT NULL DEFAULT '',
          value       double precision,
          status      text
        )
        """
    )
    op.execute("SELECT create_hypertable('readings', 'time', chunk_time_interval => interval '1 day')")
    op.execute("CREATE INDEX ix_readings_server_metric_time ON readings (server_id, metric_code, time DESC)")
    op.execute(
        """
        ALTER TABLE readings SET (
          timescaledb.compress,
          timescaledb.compress_segmentby = 'server_id, metric_code',
          timescaledb.compress_orderby = 'component, time DESC'
        )
        """
    )
    op.execute("SELECT add_compression_policy('readings', compress_after => INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('readings', drop_after => INTERVAL '30 days')")


def downgrade() -> None:
    op.execute("SELECT remove_retention_policy('readings', if_exists => true)")
    op.execute("SELECT remove_compression_policy('readings', if_exists => true)")
    op.execute("DROP TABLE readings")
