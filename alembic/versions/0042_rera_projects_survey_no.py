"""Add survey_no column to rera_projects (T-1079 GATE-80).

Extracted from RERA detail pages to enable Bhoomi auto-survey lookups.

Migration chain:
    0041_gv_gazette_data_source -> 0042_rera_projects_survey_no
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042_rera_projects_survey_no"
down_revision: Union[str, None] = "0041_gv_gazette_data_source"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column(
        "rera_projects",
        sa.Column("survey_no", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("rera_projects", "survey_no")
