"""Create calibration_snapshots table for Intelligence Calibration (GATE-157).

Stores weekly calibration check results per market: MAPE accuracy at 4wk
and 26wk horizons, trend direction, confidence distribution across agent
memories, stale memory count, and news coverage percentage.

Revision ID: 0076_calibration_snapshots
Revises: 0075_parcel_graph_edges
Create Date: 2026-06-29
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0076_calibration_snapshots"
down_revision: Union[str, None] = "0075_parcel_graph_edges"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calibration_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("market", sa.String(100), nullable=False),
        sa.Column("mape_4wk", sa.Numeric(8, 2), nullable=True),
        sa.Column("mape_26wk", sa.Numeric(8, 2), nullable=True),
        sa.Column(
            "mape_trend",
            sa.String(20),
            sa.CheckConstraint(
                "mape_trend IN ('improving', 'degrading', 'stable', 'unknown')",
                name="ck_calibration_mape_trend",
            ),
            nullable=True,
        ),
        sa.Column("confidence_high", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("confidence_medium", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("confidence_low", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("stale_memory_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("news_coverage_pct", sa.Numeric(5, 1), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_calibration_snapshots_market_computed",
        "calibration_snapshots",
        ["market", sa.text("computed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_calibration_snapshots_market_computed",
        table_name="calibration_snapshots",
    )
    op.drop_table("calibration_snapshots")
