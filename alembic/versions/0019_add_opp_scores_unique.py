"""Add unique constraint to opportunity_scores (v2 ON CONFLICT support)

Revision ID: 0019_add_opp_scores_unique
Revises: 0018_add_surveys_developer_id
Create Date: 2026-06-05
"""

from typing import Sequence, Union
from alembic import op

revision: str = "0019_add_opp_scores_unique"
down_revision: Union[str, None] = "0018_add_surveys_developer_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Constraint may already exist (added by v2 schema or earlier migration) — drop + recreate
    op.execute(
        "ALTER TABLE opportunity_scores DROP CONSTRAINT IF EXISTS uq_opp_scores_survey"
    )
    op.execute("ALTER TABLE opportunity_scores DROP CONSTRAINT IF EXISTS uq_opp_score")
    op.execute("""
        ALTER TABLE opportunity_scores
        ADD CONSTRAINT uq_opp_scores_survey UNIQUE (survey_id, survey_no, micro_market_id)
    """)


def downgrade() -> None:
    op.drop_constraint("uq_opp_scores_survey", "opportunity_scores", type_="unique")
