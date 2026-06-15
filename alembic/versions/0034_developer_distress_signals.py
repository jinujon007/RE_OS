"""Create developer_distress_signals table for Sprint 72.

Migration chain:
    0033_shareholder_sessions -> 0034_developer_distress_signals
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034_developer_distress_signals"
down_revision: Union[str, None] = "0033_shareholder_sessions"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        "developer_distress_signals",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("developer_name", sa.Text(), nullable=False),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("signal_type", sa.Text(), nullable=False),
        sa.Column(
            "stall_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "stall_ratio", sa.Float(), server_default=sa.text("0.0"), nullable=False
        ),
        sa.Column(
            "mention_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "distress_score", sa.Float(), server_default=sa.text("0.0"), nullable=False
        ),
        sa.Column(
            "detected_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "ingest_log_id", sa.UUID(), sa.ForeignKey("ingest_log.id"), nullable=True
        ),
    )
    op.create_check_constraint(
        "ck_developer_distress_signal_type",
        "developer_distress_signals",
        "signal_type IN ('rera_stall','nclt_news','bda_auction','sarfaesi','computed')",
    )
    op.create_unique_constraint(
        "uq_developer_distress_signal",
        "developer_distress_signals",
        ["developer_name", "market", "signal_type"],
    )
    op.create_index(
        "idx_developer_distress_market_detected",
        "developer_distress_signals",
        ["market", "detected_at"],
    )


def downgrade():
    op.drop_index(
        "idx_developer_distress_market_detected",
        table_name="developer_distress_signals",
    )
    op.drop_constraint(
        "uq_developer_distress_signal", "developer_distress_signals", type_="unique"
    )
    op.drop_constraint(
        "ck_developer_distress_signal_type", "developer_distress_signals", type_="check"
    )
    op.drop_table("developer_distress_signals")
