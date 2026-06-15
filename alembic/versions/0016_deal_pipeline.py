"""Add deal_pipeline table.
Revision ID: 0016_deal_pipeline
Revises: 0102_merge_heads
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0016_deal_pipeline"
down_revision: Union[str, None] = "0102_merge_heads"


def upgrade() -> None:
    op.create_table(
        "deal_pipeline",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("survey_no", sa.String(100), nullable=False),
        sa.Column("micro_market_id", sa.dialects.postgresql.UUID(), nullable=True),
        sa.Column("stage", sa.String(50), nullable=False, server_default="prospecting"),
        sa.Column("opportunity_score", sa.DECIMAL(5, 4), nullable=True),
        sa.Column("assigned_to", sa.String(100), nullable=True, server_default="Jinu"),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("next_step_due", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["micro_market_id"], ["micro_markets.id"]),
    )
    op.create_index("idx_deal_pipeline_stage", "deal_pipeline", ["stage"])
    op.create_index("idx_deal_pipeline_market", "deal_pipeline", ["micro_market_id"])


def downgrade() -> None:
    op.drop_table("deal_pipeline")
