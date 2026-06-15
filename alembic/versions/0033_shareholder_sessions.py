"""Create shareholder_sessions table for quarterly board reviews (Phase 14 - Sprint 62)

Stores shareholder board session data including quarterly reviews, deal reviews,
and strategic votes. Tracks shareholder responses, debate transcripts, and CEO synthesis.

Migration chain:
    0032_merge_gcc_token -> 0033_shareholder_sessions
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_shareholder_sessions"
down_revision: Union[str, None] = "0032_merge_gcc_token"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        "shareholder_sessions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("session_type", sa.VARCHAR(30), nullable=False),
        sa.Column("quarter", sa.VARCHAR(10), nullable=True),
        sa.Column("deal_job_id", sa.UUID(), nullable=True),
        sa.Column("trigger_reason", sa.VARCHAR(200), nullable=True),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "shareholder_responses",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
        sa.Column("debate_transcript", sa.TEXT(), nullable=True),
        sa.Column("ceo_synthesis", sa.TEXT(), nullable=True),
        sa.Column("verdict", sa.VARCHAR(20), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=True
        ),
        sa.Column("completed_at", sa.TIMESTAMP(), nullable=True),
    )
    op.create_check_constraint(
        "ck_shareholder_sessions_session_type",
        "shareholder_sessions",
        "session_type IN ('deal_review','quarterly_board','strategic_vote')",
    )
    op.create_check_constraint(
        "ck_shareholder_sessions_status",
        "shareholder_sessions",
        "status IN ('pending','in_progress','complete','failed')",
    )
    op.create_index(
        "idx_shareholder_sessions_type_quarter",
        "shareholder_sessions",
        ["session_type", "quarter"],
    )
    op.create_index(
        "idx_shareholder_sessions_status", "shareholder_sessions", ["status"]
    )


def downgrade():
    op.drop_index("idx_shareholder_sessions_status", table_name="shareholder_sessions")
    op.drop_index(
        "idx_shareholder_sessions_type_quarter", table_name="shareholder_sessions"
    )
    op.drop_constraint(
        "ck_shareholder_sessions_status", "shareholder_sessions", type_="check"
    )
    op.drop_constraint(
        "ck_shareholder_sessions_session_type", "shareholder_sessions", type_="check"
    )
    op.drop_table("shareholder_sessions")
