"""Baseline schema — marks database/schema.sql as the migration baseline.

All tables and views in database/schema.sql were created before Alembic was
introduced. This migration stamps the database at revision 0001 without
running any DDL. Apply it to an already-initialised database with:

    alembic stamp 0001_baseline

For a fresh database, run schema.sql first, then stamp:
    psql ... -f database/schema.sql
    alembic stamp 0001_baseline

Revision ID: 0001_baseline
Revises: None
Create Date: 2026-05-20
"""
from typing import Sequence, Union

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Baseline — schema.sql already applied manually or via Docker init.
    pass


def downgrade() -> None:
    # Cannot auto-downgrade from baseline — drop and recreate from schema.sql.
    pass
