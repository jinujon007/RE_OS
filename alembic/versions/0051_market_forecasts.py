"""Create market_forecasts table for PSF time-series forecasts (GATE-85).

Revision ID: 0051_market_forecasts
Revises: 0050_merge_sprint81_82
Create Date: 2026-06-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0051_market_forecasts"
down_revision: Union[str, Sequence[str], None] = "0050_merge_sprint81_82"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_forecasts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("horizon_months", sa.Integer(), nullable=False),
        sa.Column("current_psf", sa.Numeric(10, 2), nullable=True),
        sa.Column("forecast_psf", sa.Numeric(10, 2), nullable=True),
        sa.Column("conf_low", sa.Numeric(10, 2), nullable=True),
        sa.Column("conf_high", sa.Numeric(10, 2), nullable=True),
        sa.Column("trend_direction", sa.Text(), nullable=True),
        sa.Column("slope_pct_per_month", sa.Numeric(6, 4), nullable=True),
        sa.Column("data_points", sa.Integer(), nullable=True),
        sa.Column("mae_pct", sa.Numeric(6, 3), nullable=True),
        sa.Column("model_version", sa.Text(), server_default=sa.text("'linear_v1'"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
    )

    op.create_check_constraint(
        "ck_market_forecasts_horizon",
        "market_forecasts",
        "horizon_months IN (3, 6, 12)",
    )
    op.create_check_constraint(
        "ck_market_forecasts_trend",
        "market_forecasts",
        "trend_direction IN ('rising', 'falling', 'flat', 'insufficient_data', 'error')",
    )
    op.create_unique_constraint(
        "uq_market_forecasts_key",
        "market_forecasts",
        ["market", "forecast_date", "horizon_months"],
    )
    op.create_index(
        "idx_market_forecasts_lookup",
        "market_forecasts",
        ["market", sa.text("forecast_date DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_market_forecasts_lookup", table_name="market_forecasts")
    op.drop_constraint("uq_market_forecasts_key", "market_forecasts", type_="unique")
    op.drop_constraint("ck_market_forecasts_horizon", "market_forecasts", type_="check")
    op.drop_constraint("ck_market_forecasts_trend", "market_forecasts", type_="check")
    op.drop_table("market_forecasts")
