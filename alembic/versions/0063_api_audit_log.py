"""Create api_audit_log table for authenticated API request tracking (GATE-107, T-1224).

Stores one row per authenticated API request: request_id, path, method, role,
status_code, and duration_ms. Used for security auditing and usage monitoring.

Indexes:
  - (created_at DESC) for efficient recent-first queries
  - partial index on (role, path) WHERE role IS NOT NULL for filtered lookups

Migration chain:
  0062_corridor_boundaries -> 0063_api_audit_log
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0063_api_audit_log"
down_revision: Union[str, None] = "0062_corridor_boundaries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
    )
    op.create_index(
        "ix_api_audit_log_created_at_desc",
        "api_audit_log",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_api_audit_log_role_path",
        "api_audit_log",
        ["role", "path"],
        postgresql_where=sa.text("role IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_api_audit_log_role_path")
    op.drop_index("ix_api_audit_log_created_at_desc")
    op.drop_table("api_audit_log")
