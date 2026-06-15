"""Add developer_id FK to surveys table (v2 market-aware surveys)

Revision ID: 0018_add_surveys_developer_id
Revises: 0017_regulatory_zones_market_fk
Create Date: 2026-06-05
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0018_add_surveys_developer_id"
down_revision: Union[str, None] = "0017_regulatory_zones_market_fk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Column may already exist from v2 schema (0100_v2_schema) — use IF NOT EXISTS
    op.execute("""
        ALTER TABLE surveys
        ADD COLUMN IF NOT EXISTS developer_id UUID REFERENCES developers(id) ON DELETE SET NULL
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_surveys_developer ON surveys (developer_id)"
    )


def downgrade() -> None:
    op.drop_index("idx_surveys_developer", "surveys")
    op.drop_column("surveys", "developer_id")
