"""Merge 0049 (Sprint 81) and 0043 (Sprint 82) into single head.

Sprint 81 added 0046→0047→0048→0049 after 0045 (FK SET NULL, CHECK,
indexes). 0045 branches from 0043 directly. This merge resolves the fork
so Alembic has exactly one head.

Migration chain:
    0049_idx_listings_price_psf + 0043_rera_projects_bhoomi_checked_at -> 0050_merge_sprint81_82
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0050_merge_sprint81_82"
down_revision: Union[str, Sequence[str], None] = (
    "0049_idx_listings_price_psf",
    "0043_rera_projects_bhoomi_checked_at",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    pass


def downgrade():
    pass
