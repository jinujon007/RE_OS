"""Create prediction_ledger table for falsifiable claim tracking (GATE-93, T-1147).

Tracks every forecast/score/alert as a falsifiable row: the system records what
it predicted, by when it should be checkable, and later fills in the actual
value and verdict (hit/miss/partial/unverifiable).

Migration chain:
    0056_assembly_signals -> 0057_prediction_ledger
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0057_prediction_ledger"
down_revision: Union[str, None] = "0056_assembly_signals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prediction_ledger",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("date_made", sa.Date(), nullable=False),
        sa.Column("source_module", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.Text(), nullable=False),
        sa.Column("market", sa.Text(), nullable=True),
        sa.Column("parcel_id", sa.UUID(), sa.ForeignKey("parcels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("survey_no", sa.Text(), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("falsifiable_metric", sa.Text(), nullable=False),
        sa.Column("predicted_value", sa.Numeric(), nullable=True),
        sa.Column("check_date", sa.Date(), nullable=False),
        sa.Column("actual_value", sa.Numeric(), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("idx_pledger_check_verdict", "prediction_ledger", ["check_date", "verdict"])


def downgrade() -> None:
    op.drop_index("idx_pledger_check_verdict", table_name="prediction_ledger")
    op.drop_table("prediction_ledger")
