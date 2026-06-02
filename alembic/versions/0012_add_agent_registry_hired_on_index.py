"""Add hired_on index to agent_registry (Phase 8 — perf).
Revision ID: 0012_agent_registry_hired_on_idx
Revises: 0011_add_agent_registry
Create Date: 2026-06-01
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0012_agent_registry_hired_on_idx"
down_revision: Union[str, None] = "0011_add_agent_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_registry_hired_on "
        "ON agent_registry(hired_on DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_registry_hired_on")
