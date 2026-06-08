"""Standalone B-tree index on listings.price_psf (T-1088 GATE-81).

PSF range filters run against this column directly. Existing composite
indexes don't cover single-column price_psf range queries efficiently.

Migration chain:
    0048_idx_rera_projects_developer_id -> 0049_idx_listings_price_psf
"""
from typing import Union

from alembic import op

revision: str = "0049_idx_listings_price_psf"
down_revision: Union[str, None] = "0048_idx_rera_projects_developer_id"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_index(
        "idx_listings_price_psf",
        "listings",
        ["price_psf"],
    )


def downgrade():
    op.drop_index("idx_listings_price_psf", "listings")
