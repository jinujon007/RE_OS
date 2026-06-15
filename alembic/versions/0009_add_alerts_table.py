"""Add alerts table for Discord notification log (Phase 7).
Revision ID: 0009_add_alerts_table
Revises: 0008_add_tasks_table
Create Date: 2026-05-30
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0009_add_alerts_table"
down_revision: Union[str, None] = "0008_add_tasks_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("color", sa.Integer(), server_default="3447003"),
        sa.Column("status", sa.String(20), nullable=False, server_default="sent"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "status IN ('sent','failed','skipped')", name="chk_alerts_status"
        ),
    )
    op.create_index("idx_alerts_channel", "alerts", ["channel"])
    op.create_index("idx_alerts_created_at", "alerts", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_alerts_created_at")
    op.drop_index("idx_alerts_channel")
    op.drop_table("alerts")
