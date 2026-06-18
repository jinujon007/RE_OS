"""Create corridor_backtest_verdicts table (T-1266).

Revision ID: 0066_corridor_backtest_verdicts
Revises: 0065_corridor_boundaries_v2
Create Date: 2026-06-18
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0066_corridor_backtest_verdicts"
down_revision: Union[str, None] = "0065_corridor_boundaries_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corridor_backtest_verdicts",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("corridor_name", sa.String(100), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("rank_correlation", sa.Float(), nullable=True),
        sa.Column("projects_evaluated", sa.Integer(), nullable=True),
        sa.Column("kill_criterion_met", sa.Boolean(), nullable=True),
        sa.Column("verdict", sa.String(20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_check_constraint(
        "ck_corridor_backtest_verdicts_verdict",
        "corridor_backtest_verdicts",
        "verdict IN ('PASS', 'FAIL', 'INSUFFICIENT_DATA')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_corridor_backtest_verdicts_verdict",
        "corridor_backtest_verdicts",
    )
    op.drop_table("corridor_backtest_verdicts")
