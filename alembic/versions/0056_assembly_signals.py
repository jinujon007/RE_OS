"""Create assembly_signals table for land assembly detection (GATE-92, T-1143).

Tracks detected land assemblies: same buyer acquiring parcels in same village
within 180 days with adjacent survey numbers. Dedup: update existing open signal
for same buyer+village.

Migration chain:
    0055_parcels_table -> 0056_assembly_signals
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0056_assembly_signals"
down_revision: Union[str, None] = "0055_parcels_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assembly_signals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("buyer_name_norm", sa.Text(), nullable=False),
        sa.Column("village", sa.Text(), nullable=False),
        sa.Column("parcel_count", sa.Integer(), nullable=False),
        sa.Column("total_extent_sqft", sa.Numeric(), nullable=True),
        sa.Column("total_consideration_inr", sa.Numeric(), nullable=True),
        sa.Column("first_deed_date", sa.Date(), nullable=True),
        sa.Column("last_deed_date", sa.Date(), nullable=True),
        sa.Column("survey_nos", sa.ARRAY(sa.Text()), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("discord_alerted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
    )

    op.create_unique_constraint(
        "uq_assembly_signals_buyer_village",
        "assembly_signals",
        ["buyer_name_norm", "village"],
    )

    op.create_check_constraint(
        "ck_assembly_signals_parcel_count",
        "assembly_signals",
        "parcel_count >= 2",
    )

    op.create_check_constraint(
        "ck_assembly_signals_confidence",
        "assembly_signals",
        "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
    )

    op.create_index("idx_assembly_signals_status", "assembly_signals", ["status"])
    op.create_index("idx_assembly_signals_status_alerted", "assembly_signals", ["status", "discord_alerted"])
    op.create_index("idx_assembly_signals_village", "assembly_signals", ["village"])
    op.create_index("idx_assembly_signals_buyer", "assembly_signals", ["buyer_name_norm"])


def downgrade() -> None:
    op.drop_index("idx_assembly_signals_buyer", table_name="assembly_signals")
    op.drop_index("idx_assembly_signals_village", table_name="assembly_signals")
    op.drop_index("idx_assembly_signals_status_alerted", table_name="assembly_signals")
    op.drop_index("idx_assembly_signals_status", table_name="assembly_signals")
    op.drop_constraint("ck_assembly_signals_confidence", "assembly_signals", type_="check")
    op.drop_constraint("ck_assembly_signals_parcel_count", "assembly_signals", type_="check")
    op.drop_constraint("uq_assembly_signals_buyer_village", "assembly_signals", type_="unique")
    op.drop_table("assembly_signals")
