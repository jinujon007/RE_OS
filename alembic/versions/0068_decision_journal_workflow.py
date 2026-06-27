"""Add decision_flag, context_summary, board_session_id columns (T-1371).

Existing decision_journal table had columns for a different decision schema.
This migration adds the columns needed for the Board Room journal workflow.

Revision ID: 0068_decision_journal_workflow
Revises: 0067_decision_journal
Create Date: 2026-06-25
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0068_decision_journal_workflow"
down_revision: Union[str, None] = "0067_decision_journal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("decision_journal", sa.Column("decision_flag", sa.String(20), nullable=True))
    op.add_column("decision_journal", sa.Column("context_summary", sa.Text(), nullable=True))
    op.add_column("decision_journal", sa.Column("board_session_id", sa.String(36), nullable=True))
    op.create_index("ix_decision_journal_board_session_id", "decision_journal", ["board_session_id"])
    op.create_index("ix_decision_journal_decision_flag", "decision_journal", ["decision_flag"])


def downgrade() -> None:
    op.drop_index("ix_decision_journal_decision_flag", table_name="decision_journal")
    op.drop_index("ix_decision_journal_board_session_id", table_name="decision_journal")
    op.drop_column("decision_journal", "board_session_id")
    op.drop_column("decision_journal", "context_summary")
    op.drop_column("decision_journal", "decision_flag")
