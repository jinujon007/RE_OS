"""Merge 0069_prediction_ledger_psf and 0069_assembly_signals_v2 into single head.

Both 0069 migrations branched from 0068_decision_journal_workflow in parallel.
This merge resolves the Alembic fork so there is exactly one head.

Migration chain:
    0069_prediction_ledger_psf + 0069_assembly_signals_v2 -> 0070_merge_0069_heads
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0070_merge_0069_heads"
down_revision: Union[str, Sequence[str], None] = (
    "0069_prediction_ledger_psf",
    "0069_assembly_signals_v2",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
