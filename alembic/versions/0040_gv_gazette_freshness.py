"""Add gazette_year and gazette_published_date to guidance_values (T-1070 GATE-78).

Tracks gazette publication freshness for stale-data detection in Board Room
and Discord alerts.

Migration chain:
    0039_gv_extraction_confidence -> 0040_gv_gazette_freshness
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040_gv_gazette_freshness"
down_revision: Union[str, None] = "0039_gv_extraction_confidence"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column(
        "guidance_values",
        sa.Column("gazette_year", sa.Integer(), nullable=True),
    )
    op.add_column(
        "guidance_values",
        sa.Column("gazette_published_date", sa.Date(), nullable=True),
    )


def downgrade():
    op.drop_column("guidance_values", "gazette_published_date")
    op.drop_column("guidance_values", "gazette_year")
