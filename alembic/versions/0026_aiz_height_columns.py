"""Add height_limit_m and note columns to regulatory_zones for AIZ cap query

Revision ID: 0026_demand_events
Revises: 0025_demand_events
Create Date: 2026-06-08

Context: fsi_calculator.py queries `height_limit_m` and `note` from
regulatory_zones WHERE zone_type='AIZ'. The original schema only had
max_height_m. This migration adds the two columns and back-fills AIZ
rows from max_height_m so existing seed data is not lost.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0026_demand_events"
down_revision: Union[str, None] = "0025_demand_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "regulatory_zones",
        sa.Column("height_limit_m", sa.Numeric(7, 2), nullable=True),
    )
    op.add_column(
        "regulatory_zones",
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.execute(
        "UPDATE regulatory_zones SET height_limit_m = max_height_m "
        "WHERE zone_type = 'AIZ' AND height_limit_m IS NULL"
    )


def downgrade() -> None:
    op.drop_column("regulatory_zones", "note")
    op.drop_column("regulatory_zones", "height_limit_m")
