"""Add agent_registry table (Phase 8 — Agent Hiring & Onboarding).

Revision ID: 0011_add_agent_registry
Revises: 0010_add_sentiment_columns
Create Date: 2026-06-01
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0011_add_agent_registry"
down_revision: Union[str, None] = "0010_add_sentiment_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_registry (
            id          VARCHAR(100) PRIMARY KEY,
            name        TEXT NOT NULL,
            role        TEXT NOT NULL,
            department  VARCHAR(50),
            spec        JSONB NOT NULL,
            llm_tier    VARCHAR(20) NOT NULL DEFAULT 'analysis'
                        CHECK (llm_tier IN ('heavy', 'analysis', 'light')),
            active      BOOLEAN NOT NULL DEFAULT TRUE,
            hired_on    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_registry_dept "
        "ON agent_registry(department)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_registry_active "
        "ON agent_registry(active)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_registry CASCADE")
