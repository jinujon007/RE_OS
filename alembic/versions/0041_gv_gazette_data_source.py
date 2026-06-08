"""Add 'gazette_pdf' to guidance_values data_source CHECK constraint (GATE-78).

The gazette parser sets data_source='gazette_pdf' but the original CHECK only
allowed 'portal_scraped', 'seed_estimated', 'manual_entry'. Without this fix,
all gazette_pdf upserts would fail with a CHECK constraint violation.

Strategy: drop old constraint, add new one with 'gazette_pdf' included.
Uses a named constraint to avoid relying on auto-generated names.

Migration chain:
    0040_gv_gazette_freshness -> 0041_gv_gazette_data_source
"""
from typing import Union

from alembic import op

revision: str = "0041_gv_gazette_data_source"
down_revision: Union[str, None] = "0040_gv_gazette_freshness"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_CONSTRAINT_NAME = "ck_guidance_values_data_source"


def upgrade():
    op.execute(
        f"ALTER TABLE guidance_values DROP CONSTRAINT IF EXISTS {_CONSTRAINT_NAME}"
    )
    op.execute(
        f"ALTER TABLE guidance_values ADD CONSTRAINT {_CONSTRAINT_NAME} "
        f"CHECK (data_source IN "
        f"('portal_scraped', 'seed_estimated', 'manual_entry', 'gazette_pdf', 'igr_gazette'))"
    )


def downgrade():
    op.execute(
        f"ALTER TABLE guidance_values DROP CONSTRAINT IF EXISTS {_CONSTRAINT_NAME}"
    )
    op.execute(
        f"ALTER TABLE guidance_values ADD CONSTRAINT {_CONSTRAINT_NAME} "
        f"CHECK (data_source IN "
        f"('portal_scraped', 'seed_estimated', 'manual_entry'))"
    )
