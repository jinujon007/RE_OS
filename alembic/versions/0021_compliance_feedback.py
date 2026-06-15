"""Add compliance_milestones table + feedback loop columns

Revision ID: 0021_compliance_feedback
Revises: 0020_add_igr_gazette_data_source
Create Date: 2026-06-05
"""

from typing import Sequence, Union
from alembic import op

revision: str = "0021_compliance_feedback"
down_revision: Union[str, None] = "0020_add_igr_gazette_data_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # ── compliance_milestones ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS compliance_milestones (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            market      TEXT NOT NULL,
            milestone   TEXT NOT NULL,
            deadline    DATE,
            status      TEXT NOT NULL DEFAULT 'pending',
            notes       TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_compliance_milestone UNIQUE (market, milestone)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compliance_market ON compliance_milestones (market)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compliance_deadline ON compliance_milestones (deadline)"
    )

    # ── feedback loop columns on opportunity_scores ───────────────────────────
    op.execute("""
        ALTER TABLE opportunity_scores
        ADD COLUMN IF NOT EXISTS actual_irr NUMERIC(6,2),
        ADD COLUMN IF NOT EXISTS actual_outcome TEXT,
        ADD COLUMN IF NOT EXISTS deal_type TEXT,
        ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS notes TEXT
    """)


def downgrade() -> None:
    for col in ("notes", "closed_at", "deal_type", "actual_outcome", "actual_irr"):
        op.drop_column("opportunity_scores", col)
    op.drop_table("compliance_milestones")
