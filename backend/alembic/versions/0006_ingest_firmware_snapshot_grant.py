"""Let the ingest role apply full firmware snapshots.

`firmware` in a batch is a full snapshot of installed firmware (docs/contracts/README.md), so entries that are
no longer reported (a replaced drive, a removed card) must be deleted; otherwise compliance would keep judging
firmware that is gone. Components are kept and flagged `removed_at` instead, so they need no DELETE.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gcc_ingest') THEN
            GRANT DELETE ON firmware_inventory TO gcc_ingest;
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gcc_ingest') THEN
            REVOKE DELETE ON firmware_inventory FROM gcc_ingest;
          END IF;
        END
        $$;
        """
    )
