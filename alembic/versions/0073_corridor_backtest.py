"""Create corridor_backtest_results table for backtest accuracy snapshots.

Revision ID: 0073_corridor_backtest
Revises: 0072_assembly_weekly_trend
Create Date: 2026-06-27
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0073_corridor_backtest"
down_revision: Union[str, None] = "0072_assembly_weekly_trend"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corridor_backtest_results",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("market", sa.String(100), nullable=False, comment="Canonical market name (Yelahanka/Devanahalli/Hebbal)"),
        sa.Column("corridor", sa.String(200), nullable=False, comment="Corridor display name"),
        sa.Column("snapshot_date", sa.Date(), nullable=False, comment="Date of the backtest snapshot window"),
        sa.Column("psf_actual", sa.Numeric(10, 2), nullable=True, comment="Actual avg PSF from registered transactions"),
        sa.Column("psf_predicted", sa.Numeric(10, 2), nullable=True, comment="Predicted PSF from corridor scorer model"),
        sa.Column("error_pct", sa.Numeric(8, 2), nullable=True, comment="Prediction error % — negative means over-prediction"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("market", "corridor", "snapshot_date", name="uq_corridor_backtest_result"),
        sa.CheckConstraint("ABS(error_pct) < 1000", name="ck_corridor_backtest_error_range"),
    )
    op.create_index(
        "idx_corridor_backtest_market_date",
        "corridor_backtest_results",
        ["market", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_corridor_backtest_market_date", table_name="corridor_backtest_results")
    op.drop_table("corridor_backtest_results")
