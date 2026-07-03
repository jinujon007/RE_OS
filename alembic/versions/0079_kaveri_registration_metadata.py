"""Create kaveri_registration_metadata table for auto-discovered deed registrations.

Stores metadata from daily Kaveri portal scans: doc numbers, parties,
property details, and download tracking status.

Revision ID: 0079_kaveri_registration_metadata
Revises: 0078_new_markets
Create Date: 2026-07-03
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0079_kaveri_registration_metadata"
down_revision: Union[str, None] = "0078_new_markets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kaveri_registration_metadata",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("doc_no", sa.Text(), nullable=False),
        sa.Column("village", sa.Text(), nullable=False),
        sa.Column("taluk", sa.Text(), nullable=True),
        sa.Column("reg_date", sa.Date(), nullable=True),
        sa.Column("seller", sa.Text(), nullable=True),
        sa.Column("buyer", sa.Text(), nullable=True),
        sa.Column("survey_no", sa.Text(), nullable=True),
        sa.Column("property_area", sa.Text(), nullable=True),
        sa.Column("estimated_value", sa.Text(), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("pdf_downloaded", sa.Boolean(), server_default=sa.text("FALSE"), nullable=False),
        sa.Column("pdf_path", sa.Text(), nullable=True),
        sa.UniqueConstraint("doc_no", "village", name="uq_kaveri_reg_doc_village"),
    )
    op.create_index(
        "idx_kaveri_reg_village_date",
        "kaveri_registration_metadata",
        ["village", sa.text("reg_date DESC")],
    )
    op.create_index(
        "idx_kaveri_reg_pending",
        "kaveri_registration_metadata",
        ["pdf_downloaded", sa.text("reg_date DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_kaveri_reg_pending", table_name="kaveri_registration_metadata")
    op.drop_index("idx_kaveri_reg_village_date", table_name="kaveri_registration_metadata")
    op.drop_table("kaveri_registration_metadata")
