"""Create dc_conversions table — DC Conversion Tracker (GATE-94, T-1153).

Tracks land-use conversion (DC) application status from Bhoomi/landrecords portal.
survey_no links to parcels table via parcel linker for assembly detection.
Discord alert on conversion in a covered market village.

Migration chain:
    0059_gcc_hiring_snapshots -> 0060_dc_conversions
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0060_dc_conversions"
down_revision: Union[str, None] = "0059_gcc_hiring_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dc_conversions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("application_no", sa.Text(), nullable=False),
        sa.Column("village", sa.Text(), nullable=True),
        sa.Column("survey_no", sa.Text(), nullable=True),
        sa.Column("extent_acres", sa.Numeric(10, 4), nullable=True),
        sa.Column("from_use", sa.Text(), nullable=True),
        sa.Column("to_use", sa.Text(), nullable=True),
        sa.Column("applicant_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("application_date", sa.Date(), nullable=True),
        sa.Column("decision_date", sa.Date(), nullable=True),
        sa.Column(
            "data_source", sa.Text(), nullable=False, server_default=sa.text("'live'")
        ),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.UniqueConstraint("application_no", name="uq_dc_conversions_app_no"),
    )
    op.create_index("idx_dc_conversions_village", "dc_conversions", ["village"])
    op.create_index("idx_dc_conversions_survey", "dc_conversions", ["survey_no"])
    op.create_index("idx_dc_conversions_status", "dc_conversions", ["status"])


def downgrade() -> None:
    op.drop_index("idx_dc_conversions_status", table_name="dc_conversions")
    op.drop_index("idx_dc_conversions_survey", table_name="dc_conversions")
    op.drop_index("idx_dc_conversions_village", table_name="dc_conversions")
    op.drop_table("dc_conversions")
