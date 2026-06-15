"""Add Karnataka-scale composite index on registered_transactions.

Adds (sro, taluk, hobli, village, reg_date) composite index to support
hobli-level and taluk-level queries as KAVERI_DEED_SCOPE scales beyond
the 3 test markets to full Karnataka.

Revision ID: 0054_registered_transactions_karnataka_index
Revises: 0053_registered_transactions
Create Date: 2026-06-12
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0054_registered_transactions_karnataka_index"
down_revision: Union[str, None] = "0053_registered_transactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index for Karnataka-scale queries by SRO → taluk → hobli → village
    # Covers: all deeds in a hobli, all deeds in a taluk, all deeds under an SRO
    op.create_index(
        "idx_registered_transactions_jurisdiction",
        "registered_transactions",
        ["sro", "taluk", "hobli", "village", sa.text("reg_date DESC")],
    )

    # District + date for cross-SRO district-level rollups
    op.create_index(
        "idx_registered_transactions_district_date",
        "registered_transactions",
        ["district", sa.text("reg_date DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_registered_transactions_district_date",
        table_name="registered_transactions",
    )
    op.drop_index(
        "idx_registered_transactions_jurisdiction", table_name="registered_transactions"
    )
