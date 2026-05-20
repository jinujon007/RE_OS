"""Add board_sessions table for Phase 3 Board Room.

CEO decomposes a pitch; BD, Finance, Engineering, Ops respond concurrently;
CEO synthesises. This table stores session state and all responses.

Revision ID: 0003_board_sessions
Revises: 0002_delay_months_trigger
Create Date: 2026-05-20
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003_board_sessions"
down_revision: Union[str, None] = "0002_delay_months_trigger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS board_sessions (
            session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            market TEXT NOT NULL,
            initiated_by TEXT NOT NULL DEFAULT 'ceo',
            pitch_text TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'complete', 'failed')),
            bd_response TEXT,
            finance_response TEXT,
            engineering_response TEXT,
            ops_response TEXT,
            ceo_synthesis TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_board_sessions_market "
        "ON board_sessions(market, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_board_sessions_status ON board_sessions(status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS board_sessions")
