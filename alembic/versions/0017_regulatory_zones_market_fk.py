"""Add micro_market_id FK to regulatory_zones (v2 market-aware zones)

Revision ID: 0017_regulatory_zones_market_fk
Revises: 0016_deal_pipeline
Create Date: 2026-06-05
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0017_regulatory_zones_market_fk"
down_revision: Union[str, None] = "0016_deal_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "regulatory_zones",
        sa.Column(
            "micro_market_id",
            sa.UUID(),
            sa.ForeignKey("micro_markets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_reg_zones_market", "regulatory_zones", ["micro_market_id"])


def downgrade() -> None:
    op.drop_index("idx_reg_zones_market", "regulatory_zones")
    op.drop_column("regulatory_zones", "micro_market_id")
