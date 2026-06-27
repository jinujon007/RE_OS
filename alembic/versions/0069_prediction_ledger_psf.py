"""Create prediction_ledger_psf table for PSF forecast accuracy tracking (T-1381).

Tracks each PSF forecast as a row with predicted vs actual values,
horizon windows, error percentage, and CHECK constraints ensuring
data integrity: predicted_psf > 0, error_pct within ±1000%.

Used by prediction_tracker.py to compute MAPE and by the scheduler
to backfill actuals from project_snapshots or listings.

Revision ID: 0069_prediction_ledger_psf
Revises: 0068_decision_journal_workflow
Create Date: 2026-06-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0069_prediction_ledger_psf"
down_revision: Union[str, None] = "0068_decision_journal_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prediction_ledger_psf",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("market", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=True),
        sa.Column("predicted_psf", sa.Numeric(10, 2), nullable=False),
        sa.Column("predicted_at", sa.DateTime(), nullable=False),
        sa.Column("horizon_weeks", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("horizon_months", sa.Integer(), nullable=True, server_default="6"),
        sa.Column("actual_psf", sa.Numeric(10, 2), nullable=True),
        sa.Column("measured_at", sa.DateTime(), nullable=True),
        sa.Column("error_pct", sa.Numeric(8, 2), nullable=True),
        sa.Column("source", sa.String(50), nullable=True, server_default="psf_forecaster"),
        sa.CheckConstraint("predicted_psf > 0", name="ck_pledger_psf_positive"),
        sa.CheckConstraint(
            "error_pct IS NULL OR abs(error_pct) < 1000",
            name="ck_pledger_error_bounds",
        ),
    )
    op.create_index(
        "ix_pledgerpsf_market_predicted",
        "prediction_ledger_psf",
        ["market", "predicted_at"],
    )
    op.create_index(
        "ix_pledgerpsf_market_measured",
        "prediction_ledger_psf",
        ["market", "measured_at"],
        postgresql_where=sa.text("measured_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_pledgerpsf_market_measured", table_name="prediction_ledger_psf")
    op.drop_index("ix_pledgerpsf_market_predicted", table_name="prediction_ledger_psf")
    op.drop_table("prediction_ledger_psf")
