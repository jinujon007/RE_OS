"""Create registered_transactions table for Kaveri deed-level transaction truth (GATE-91).

Revision ID: 0053_registered_transactions
Revises: 0052_board_session_timing
Create Date: 2026-06-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0053_registered_transactions"
down_revision: Union[str, Sequence[str], None] = "0052_board_session_timing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "registered_transactions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("doc_no", sa.Text(), nullable=False),
        sa.Column("reg_date", sa.Date(), nullable=False),
        sa.Column("sro", sa.Text(), nullable=False),
        sa.Column("district", sa.Text(), nullable=True),
        sa.Column("taluk", sa.Text(), nullable=True),
        sa.Column("hobli", sa.Text(), nullable=True),
        sa.Column("village", sa.Text(), nullable=False),
        sa.Column("survey_no", sa.Text(), nullable=True),
        sa.Column("extent_sqft", sa.Numeric(), nullable=True),
        sa.Column("consideration_inr", sa.Numeric(), nullable=True),
        sa.Column("psf", sa.Numeric(), nullable=True),
        sa.Column("deed_type", sa.Text(), nullable=True),
        sa.Column("buyer_name_raw", sa.Text(), nullable=True),
        sa.Column("seller_name_raw", sa.Text(), nullable=True),
        sa.Column("buyer_type", sa.Text(), nullable=True),
        sa.Column("data_source", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("extraction_confidence", sa.Text(), server_default=sa.text("'medium'"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
    )

    op.create_unique_constraint(
        "uq_registered_transactions_key",
        "registered_transactions",
        ["sro", "doc_no", "reg_date"],
    )

    op.create_check_constraint(
        "ck_registered_transactions_consideration",
        "registered_transactions",
        "consideration_inr IS NULL OR consideration_inr > 0",
    )

    op.create_index(
        "idx_registered_transactions_village_date",
        "registered_transactions",
        ["village", sa.text("reg_date DESC")],
    )

    op.create_index(
        "idx_registered_transactions_survey_no",
        "registered_transactions",
        ["survey_no"],
    )

    op.create_index(
        "idx_registered_transactions_sro_date",
        "registered_transactions",
        ["sro", sa.text("reg_date DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_registered_transactions_sro_date", table_name="registered_transactions")
    op.drop_index("idx_registered_transactions_survey_no", table_name="registered_transactions")
    op.drop_index("idx_registered_transactions_village_date", table_name="registered_transactions")
    op.drop_constraint("ck_registered_transactions_consideration", "registered_transactions", type_="check")
    op.drop_constraint("uq_registered_transactions_key", "registered_transactions", type_="unique")
    op.drop_table("registered_transactions")
