"""Add tasks table for Task Board (Phase 3 closure).

Revision ID: 0008_add_tasks_table
Revises: 0007_add_legal_response
Create Date: 2026-05-30
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0008_add_tasks_table"
down_revision: Union[str, None] = "0007_add_legal_response"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(50)),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("priority", sa.String(10), nullable=False, server_default="medium"),
        sa.Column("source_type", sa.String(30)),
        sa.Column("source_id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('queued','active','done','failed','rejected')", name="chk_tasks_status"),
        sa.CheckConstraint("priority IN ('high','medium','low')", name="chk_tasks_priority"),
    )
    op.create_index("idx_tasks_status", "tasks", ["status"])
    op.create_index("idx_tasks_owner",  "tasks", ["owner"])
    op.create_index("idx_tasks_source", "tasks", ["source_type", "source_id"])


def downgrade() -> None:
    op.drop_index("idx_tasks_source")
    op.drop_index("idx_tasks_owner")
    op.drop_index("idx_tasks_status")
    op.drop_table("tasks")
