"""Add v2 assembly_signals columns for GATE-140 (market, hobli, area_sqm, JSONB survey_numbers).

Extends the existing assembly_signals table (0056) with columns needed by the
new AssemblyDetector class. All new columns are nullable — backward compatible.

Revision ID: 0069_assembly_signals_v2
Revises: 0068_decision_journal_workflow
Create Date: 2026-06-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0069_assembly_signals_v2"
down_revision: Union[str, None] = "0068_decision_journal_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assembly_signals", sa.Column("market", sa.String(100), nullable=True))
    op.add_column("assembly_signals", sa.Column("hobli", sa.String(200), nullable=True))
    op.add_column("assembly_signals", sa.Column("buyer_name", sa.String(300), nullable=True))
    op.add_column("assembly_signals", sa.Column("survey_numbers", JSONB(), nullable=True))
    op.add_column("assembly_signals", sa.Column("total_area_sqm", sa.Numeric(12, 2), nullable=True))
    op.add_column("assembly_signals", sa.Column("confidence_score", sa.Numeric(4, 3), nullable=True))
    op.add_column("assembly_signals", sa.Column("detected_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=True))
    op.add_column("assembly_signals", sa.Column("resolved_at", sa.DateTime(), nullable=True))

    op.create_index("ix_assembly_market_confidence", "assembly_signals", ["market", sa.text("confidence_score DESC")])


def downgrade() -> None:
    op.drop_index("ix_assembly_market_confidence", table_name="assembly_signals")
    op.drop_column("assembly_signals", "resolved_at")
    op.drop_column("assembly_signals", "detected_at")
    op.drop_column("assembly_signals", "confidence_score")
    op.drop_column("assembly_signals", "total_area_sqm")
    op.drop_column("assembly_signals", "survey_numbers")
    op.drop_column("assembly_signals", "buyer_name")
    op.drop_column("assembly_signals", "hobli")
    op.drop_column("assembly_signals", "market")
