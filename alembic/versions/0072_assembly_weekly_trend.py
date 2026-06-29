"""Create v_assembly_weekly_trend view + index for assembly time-series.

Revision ID: 0072_assembly_weekly_trend
Revises: 0071_developer_pricing_history
Create Date: 2026-06-27
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0072_assembly_weekly_trend"
down_revision: Union[str, None] = "0071_developer_pricing_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE VIEW v_assembly_weekly_trend AS
        SELECT
            DATE_TRUNC('week', detected_at)::date AS week_start,
            market,
            COUNT(*) AS cluster_count,
            ROUND(AVG(confidence_score)::numeric, 3) AS avg_confidence,
            COUNT(*) FILTER (WHERE confidence_score > 0.7) AS high_confidence_count
        FROM assembly_signals
        WHERE detected_at IS NOT NULL
        GROUP BY DATE_TRUNC('week', detected_at), market
        ORDER BY week_start DESC
    """)
    op.create_index(
        "idx_assembly_signals_detected_market",
        "assembly_signals",
        ["detected_at", "market"],
        postgresql_where=None,
    )


def downgrade() -> None:
    op.drop_index("idx_assembly_signals_detected_market", table_name="assembly_signals")
    op.execute("DROP VIEW IF EXISTS v_assembly_weekly_trend")
