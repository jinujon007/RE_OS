"""Add response_time_s column to board_sessions for Board Room response time tracking (GATE-88 R9).

Revision ID: 0052_board_session_timing
Revises: 0051_market_forecasts
Create Date: 2026-06-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0052_board_session_timing"
down_revision: Union[str, Sequence[str], None] = "0051_market_forecasts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "board_sessions",
        sa.Column("response_time_s", sa.Float(), nullable=True),
    )
    op.create_index(
        "idx_board_sessions_response_time",
        "board_sessions",
        ["response_time_s"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index("idx_board_sessions_response_time", table_name="board_sessions")
    op.drop_column("board_sessions", "response_time_s")
