"""Add fact_type and metadata columns to agent_memories (Phase 4 — Memory Conflict Detection).
Revision ID: 0015_add_memory_fact_type
Revises: 0014_add_osm_edges
Create Date: 2026-06-02
"""

from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0015_add_memory_fact_type"
down_revision: Union[str, None] = "0014_add_osm_edges"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add fact_type column — distinguishes normal facts from conflicts and digest entries
    op.add_column(
        "agent_memories",
        sa.Column("fact_type", sa.String(20), nullable=False, server_default="fact"),
    )

    # Add metadata column — stores conflict details as JSON: source_a, value_a, source_b, value_b, pct_gap
    op.add_column(
        "agent_memories",
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_memories", "metadata")
    op.drop_column("agent_memories", "fact_type")
