"""Create land_records table for Bhoomi RTC integration (Sprint 56)

Table for storing Karnataka Bhoomi RTC (Record of Rights, Tenancy and Crops)
data fetched from landrecords.karnataka.gov.in.

Migration chain:
    0026_demand_events -> 0027_land_records
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0027_land_records"
down_revision: Union[str, None] = "0026_demand_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        "land_records",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("survey_no", sa.VARCHAR(100), nullable=False),
        sa.Column("market", sa.VARCHAR(100), nullable=True),
        sa.Column("owner_name", sa.TEXT(), nullable=True),
        sa.Column("land_nature", sa.VARCHAR(30), nullable=True),
        sa.Column("khata_no", sa.VARCHAR(100), nullable=True),
        sa.Column("area_guntas", sa.NUMERIC(10, 2), nullable=True),
        sa.Column(
            "encumbrances",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=True,
        ),
        sa.Column(
            "bhoomi_status",
            sa.VARCHAR(30),
            server_default=sa.text("'live'"),
            nullable=True,
        ),
        sa.Column(
            "bhoomi_fetched_at",
            sa.TIMESTAMP(),
            server_default=sa.text("NOW()"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_land_records_land_nature",
        "land_records",
        "land_nature IN ('agricultural','converted','revenue','notional','unknown')",
    )
    op.create_check_constraint(
        "ck_land_records_bhoomi_status",
        "land_records",
        "bhoomi_status IN ('live','unavailable','partial')",
    )
    op.create_index("idx_land_records_survey", "land_records", ["survey_no"])
    op.create_index(
        "idx_land_records_survey_market", "land_records", ["survey_no", "market"]
    )


def downgrade():
    op.drop_index("idx_land_records_survey_market", table_name="land_records")
    op.drop_index("idx_land_records_survey", table_name="land_records")
    op.drop_constraint("ck_land_records_bhoomi_status", "land_records", type_="check")
    op.drop_constraint("ck_land_records_land_nature", "land_records", type_="check")
    op.drop_table("land_records")
