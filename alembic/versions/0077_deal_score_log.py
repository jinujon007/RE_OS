"""Create deal_score_log table for Live Deal Scoring (GATE-161 / T-1492).

Stores every deal score evaluation: market, inputs, overall score, verdict,
confidence, per-signal sub-scores, reasoning, and timestamp.

Revision ID: 0077_deal_score_log
Revises: 0076_calibration_snapshots
Create Date: 2026-06-29
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0077_deal_score_log"
down_revision: Union[str, None] = "0076_calibration_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deal_score_log",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("market", sa.String(100), nullable=False),
        sa.Column("land_cost_cr", sa.Numeric(12, 2), nullable=False),
        sa.Column("area_acres", sa.Numeric(10, 2), nullable=False),
        sa.Column("overall_score", sa.Numeric(4, 3), nullable=True),
        sa.Column(
            "verdict", sa.String(20),
            sa.CheckConstraint(
                "verdict IN ('GO', 'CAUTIOUS', 'NO-GO')",
                name="ck_deal_score_verdict",
            ),
            nullable=True,
        ),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("assembly_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("corridor_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("strr_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("irr_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("kill_criteria_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("reasoning", sa.Text, nullable=True),
        sa.Column(
            "scored_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_deal_score_log_market_scored",
        "deal_score_log",
        ["market", sa.text("scored_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_deal_score_log_market_scored",
        table_name="deal_score_log",
    )
    op.drop_table("deal_score_log")
