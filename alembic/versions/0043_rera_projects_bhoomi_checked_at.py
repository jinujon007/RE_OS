"""Add bhoomi_checked_at column to rera_projects (T-1080 GATE-80).

Tracks when Bhoomi auto-survey was last checked for each project
to avoid redundant lookups and rate-limit issues.

Migration chain:
    0042_rera_projects_survey_no -> 0043_rera_projects_bhoomi_checked_at
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043_rera_projects_bhoomi_checked_at"
down_revision: Union[str, None] = "0042_rera_projects_survey_no"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column(
        "rera_projects",
        sa.Column("bhoomi_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("rera_projects", "bhoomi_checked_at")
