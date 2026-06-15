"""Merge v2 schema branch (0100/0101) with memory enhancements (0015).
Revision ID: 0102_merge_heads
Revises: 0015_add_memory_fact_type, 0101_v2_seed
Create Date: 2026-06-03
"""

from typing import Sequence, Union
from alembic import op

revision: str = "0102_merge_heads"
down_revision: Union[str, None] = ("0015_add_memory_fact_type", "0101_v2_seed")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
