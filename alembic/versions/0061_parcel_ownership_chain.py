"""Create parcel_ownership_chain table — RTC ownership history per survey_no (GATE-99, T-1185).

Stores parsed RTC (Record of Rights, Tenancy and Crops) data from Bhoomi portal.
Each row represents one fetch of ownership data for a survey number.

Migration chain:
    0060_dc_conversions -> 0061_parcel_ownership_chain
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0061_parcel_ownership_chain"
down_revision: Union[str, None] = "0060_dc_conversions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parcel_ownership_chain",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("parcel_id", sa.UUID(), sa.ForeignKey("parcels.id", ondelete="CASCADE"), nullable=True),
        sa.Column("survey_no", sa.String(50), nullable=False),
        sa.Column("market", sa.String(100), nullable=True),
        sa.Column("khata_no", sa.String(50), nullable=True),
        sa.Column("owner_name", sa.Text(), nullable=True),
        sa.Column("previous_owner", sa.Text(), nullable=True),
        sa.Column("transfer_date", sa.Date(), nullable=True),
        sa.Column("area_acres", sa.Float(), nullable=True),
        sa.Column(
            "govt_acquisition_notice",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("govt_acquisition_detail", sa.Text(), nullable=True),
        sa.Column(
            "encumbrance_flag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("encumbrance_detail", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'bhoomi_rtc'"),
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column(
            "parser_completeness_score",
            sa.Float(),
            nullable=True,
            comment="0.0–1.0: fraction of expected fields successfully extracted",
        ),
        sa.UniqueConstraint(
            "survey_no", "market", sa.text("fetched_at::date"),
            name="uq_parcel_ownership_chain_daily",
        ),
    )
    op.create_index(
        "idx_parcel_ownership_survey_market",
        "parcel_ownership_chain",
        ["survey_no", "market"],
    )
    op.create_index(
        "idx_parcel_ownership_fetched_at",
        "parcel_ownership_chain",
        [sa.text("fetched_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_parcel_ownership_fetched_at", table_name="parcel_ownership_chain")
    op.drop_index("idx_parcel_ownership_survey_market", table_name="parcel_ownership_chain")
    op.drop_table("parcel_ownership_chain")
