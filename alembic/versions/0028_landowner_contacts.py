"""Create landowner_contacts table for Landowner CRM (Sprint 56)

CRM table for tracking landowner relationships, approach status, and deal
flow for land acquisition.

Migration chain:
    0027_land_records -> 0028_landowner_contacts
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0028_landowner_contacts"
down_revision: Union[str, None] = "0027_land_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        "landowner_contacts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("survey_no", sa.VARCHAR(50), nullable=False),
        sa.Column("market", sa.VARCHAR(100), nullable=False),
        sa.Column("owner_name", sa.TEXT(), nullable=False),
        sa.Column("contact_phone", sa.VARCHAR(20), nullable=True),
        sa.Column("contact_type", sa.VARCHAR(30), server_default=sa.text("'primary'"), nullable=True),
        sa.Column("approach_status", sa.VARCHAR(30), server_default=sa.text("'cold'"), nullable=True),
        sa.Column("ask_psf", sa.NUMERIC(10, 2), nullable=True),
        sa.Column("notes", sa.TEXT(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=True),
    )
    op.create_check_constraint("ck_landowner_contact_type",
        "landowner_contacts",
        "contact_type IN ('primary','agent','legal_heir','power_of_attorney')",
    )
    op.create_check_constraint("ck_landowner_approach_status",
        "landowner_contacts",
        "approach_status IN ('cold','warm','meeting_done','mou','loi','closed_won','closed_lost')",
    )
    op.create_index("idx_landowner_contacts_survey_market", "landowner_contacts", ["survey_no", "market"])
    op.create_index("idx_landowner_contacts_status", "landowner_contacts", ["approach_status"])


def downgrade():
    op.drop_index("idx_landowner_contacts_status", table_name="landowner_contacts")
    op.drop_index("idx_landowner_contacts_survey_market", table_name="landowner_contacts")
    op.drop_constraint("ck_landowner_approach_status", "landowner_contacts", type_="check")
    op.drop_constraint("ck_landowner_contact_type", "landowner_contacts", type_="check")
    op.drop_table("landowner_contacts")
