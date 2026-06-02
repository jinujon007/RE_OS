"""Add igr_transactions table (Sprint 39 — Data Foundation).
Revision ID: 0013_add_igr_transactions
Revises: 0012_agent_registry_hired_on_idx
Create Date: 2026-06-02
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0013_add_igr_transactions"
down_revision: Union[str, None] = "0012_agent_registry_hired_on_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "igr_transactions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("market", sa.String(100), nullable=False),
        sa.Column("micro_market_id", sa.UUID(), nullable=True),
        sa.Column("survey_no", sa.String(100), nullable=True),
        sa.Column("seller_name", sa.Text(), nullable=True),
        sa.Column("buyer_name", sa.Text(), nullable=True),
        sa.Column("consideration_amount", sa.BigInteger(), nullable=True),
        sa.Column("area_sqft", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "transaction_psf", sa.Numeric(12, 2),
            sa.Computed("ROUND(consideration_amount / NULLIF(area_sqft, 0), 0)"),
            nullable=True,
        ),
        sa.Column("registration_date", sa.Date(), nullable=True),
        sa.Column("sro_office", sa.String(200), nullable=True),
        sa.Column(
            "source", sa.String(50), nullable=False, server_default="fallback",
        ),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.CheckConstraint(
            "source IN ('portal_playwright', 'portal_post', 'fallback')",
            name="chk_igr_source",
        ),
        sa.ForeignKeyConstraint(
            ["micro_market_id"], ["micro_markets.id"],
            name="fk_igr_micro_market",
        ),
    )
    op.create_index("idx_igr_market_date", "igr_transactions", ["market", sa.text("registration_date DESC")])
    op.create_index("idx_igr_survey_no", "igr_transactions", ["survey_no"])


def downgrade() -> None:
    op.drop_index("idx_igr_survey_no", table_name="igr_transactions")
    op.drop_index("idx_igr_market_date", table_name="igr_transactions")
    op.drop_table("igr_transactions")
