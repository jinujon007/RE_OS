"""Create decision_journal table (T-1279).

Decision type and outcome values must match _DECISION_TYPES / _DECISION_OUTCOMES
in dashboard/routers/ops.py — update both in sync.
Constraint strings must stay in sync with Python frozensets in the handler file.

Revision ID: 0067_decision_journal
Revises: 0066_corridor_backtest_verdicts
Create Date: 2026-06-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0067_decision_journal"
down_revision: Union[str, None] = "0066_corridor_backtest_verdicts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_journal",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("decision_type", sa.String(50), nullable=False),
        sa.Column("market", sa.String(100), nullable=True),
        sa.Column("intel_used", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_check_constraint(
        "ck_decision_journal_decision_type",
        "decision_journal",
        "decision_type IN ('land_acquisition', 'pricing', 'jv_jd_target', 'market_exit', 'product_decision')",
    )
    op.create_check_constraint(
        "ck_decision_journal_outcome",
        "decision_journal",
        "outcome IN ('acted', 'deferred', 'rejected')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_decision_journal_outcome", "decision_journal")
    op.drop_constraint("ck_decision_journal_decision_type", "decision_journal")
    op.drop_table("decision_journal")
