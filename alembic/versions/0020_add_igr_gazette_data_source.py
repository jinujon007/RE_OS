"""Add igr_gazette to data_source check constraints

Revision ID: 0020_add_igr_gazette_data_source
Revises: 0019_add_opp_scores_unique
Create Date: 2026-06-05
"""
from alembic import op

revision = "0020_add_igr_gazette_data_source"
down_revision = "0019_add_opp_scores_unique"
branch_labels = None
depends_on = None

# Tables and their data_source check constraint names
_TABLES = [
    ("guidance_values", "guidance_values_data_source_check"),
    ("kaveri_registrations", "kaveri_registrations_data_source_check"),
    ("listings", "listings_data_source_check"),
    ("rera_projects", "rera_projects_data_source_check"),
]

_NEW_VALUES = "ARRAY['portal_scraped', 'seed_estimated', 'manual_entry', 'igr_gazette']::text[]"
_OLD_VALUES = "ARRAY['portal_scraped', 'seed_estimated', 'manual_entry']::text[]"


def upgrade() -> None:
    for table, constraint_name in _TABLES:
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{constraint_name}"')
        op.execute(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint_name}" '
            f'CHECK (data_source::text = ANY ({_NEW_VALUES}))'
        )


def downgrade() -> None:
    for table, constraint_name in _TABLES:
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{constraint_name}"')
        op.execute(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint_name}" '
            f'CHECK (data_source::text = ANY ({_OLD_VALUES}))'
        )
