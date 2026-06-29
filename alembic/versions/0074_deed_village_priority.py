"""Create v_deed_village_priority view for ranking villages by assembly signal density.

priority_score formula:
    (signal_count × max_confidence) - days_since_last_deed
    = assembly signal mass - recency penalty

    - Positive score: high signal density with recent deed activity → download now
    - Score near zero: moderate priority
    - Negative score: old deeds with few signals (can go as low as -30+)
    - Domain: unbounded float, typically -50 to +50 in practice

    Monotonically decreases as last_deed_ingested ages.
    NOT materialized — always reflects current DB state.

Revision ID: 0074_deed_village_priority
Revises: 0073_corridor_backtest
Create Date: 2026-06-27
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0074_deed_village_priority"
down_revision: Union[str, None] = "0073_corridor_backtest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VIEW_SQL = """
CREATE OR REPLACE VIEW v_deed_village_priority AS
SELECT
    asm.hobli AS village,
    asm.market,
    COUNT(DISTINCT asm.id) AS assembly_signal_count,
    MAX(asm.confidence_score) AS max_confidence,
    MAX(rt.created_at) AS last_deed_ingested,
    COALESCE(COUNT(DISTINCT asm.id)::float * MAX(asm.confidence_score), 0)
    - COALESCE(EXTRACT(EPOCH FROM (NOW() - MAX(rt.created_at))) / 86400, 30)
    AS priority_score
FROM assembly_signals asm
LEFT JOIN registered_transactions rt
    ON rt.village ILIKE '%' || asm.hobli || '%'
GROUP BY asm.hobli, asm.market
ORDER BY priority_score DESC
"""


def upgrade() -> None:
    op.execute(VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_deed_village_priority")
