"""Create tenders table for eProcurement Karnataka tender monitoring (GATE-93, T-1149).

Tracks public works tenders from Karnataka eProcurement portal filtered to
North Bengaluru relevant keywords. Dedup on tender_id.

Migration chain:
    0057_prediction_ledger -> 0058_tenders
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0058_tenders"
down_revision: Union[str, None] = "0057_prediction_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenders",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tender_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("dept", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("value_inr", sa.Numeric(), nullable=True),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("close_date", sa.Date(), nullable=True),
        sa.Column("location_text", sa.Text(), nullable=True),
        sa.Column("market_match", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("tender_id"),
    )
    op.create_index("idx_tenders_published", "tenders", ["published_date"])
    op.create_index("idx_tenders_value", "tenders", ["value_inr"])


def downgrade() -> None:
    op.drop_index("idx_tenders_value", table_name="tenders")
    op.drop_index("idx_tenders_published", table_name="tenders")
    op.drop_table("tenders")
