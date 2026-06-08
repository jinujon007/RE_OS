"""Create token_usage table for per-agent token budget tracking (Sprint 60)

Stores token usage records per agent run with computed over_budget flag.
Used by TokenUsageTracker to identify agents exceeding their token budgets.

Migration chain:
    0029_lls_portfolio -> 0031_token_usage (note: 0030 exists but is the operations tables)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0031_token_usage"
down_revision: Union[str, None] = "0029_lls_portfolio"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        "token_usage",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("agent_name", sa.VARCHAR(100), nullable=False, index=True),
        sa.Column("model", sa.VARCHAR(100), nullable=False),
        sa.Column("tokens_used", sa.INTEGER(), nullable=False),
        sa.Column("budget_limit", sa.INTEGER(), nullable=False),
        sa.Column(
            "over_budget",
            sa.BOOLEAN(),
            sa.Computed("tokens_used > budget_limit", persisted=False),
            nullable=False,
        ),
        sa.Column("run_id", sa.VARCHAR(100), nullable=True, unique=True),
        sa.Column("recorded_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=True),
    )
    op.create_index(
        "idx_token_usage_recorded_agent",
        "token_usage",
        ["recorded_at", "agent_name"],
        postgresql_using="btree",
    )


def downgrade():
    op.drop_index("idx_token_usage_recorded_agent", table_name="token_usage")
    op.drop_table("token_usage")