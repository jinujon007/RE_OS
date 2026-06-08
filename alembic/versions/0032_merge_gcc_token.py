"""Merge 0030_gcc_events and 0031_token_usage into single head

Resolves the two parallel branches that both diverged from 0029_lls_portfolio:
  - 0030_gcc_events  (merged 0029_lls_portfolio + 0029_operations)
  - 0031_token_usage (branched from 0029_lls_portfolio, Sprint 60)
"""
from typing import Sequence, Tuple, Union
from alembic import op

revision: str = "0032_merge_gcc_token"
down_revision: Union[Tuple[str, str], None] = (
    "0030_gcc_events",
    "0031_token_usage",
)
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
