"""Create ingest_failed_records table for dead letter queue (GATE-108, T-1231).

Stores records that failed upsert during DBOrganizer.run(). Supports retry
with exponential backoff (max 3 attempts) and admin inspection via endpoint.

Columns:
  - id UUID PK
  - entity_type TEXT (e.g. 'rera_project', 'registration', 'listing')
  - source_id TEXT (original source identifier for tracking)
  - raw_data JSONB (the full record dict that failed)
  - error_text TEXT (the exception message)
  - plugin_id TEXT (which ingest plugin produced this record)
  - failed_at TIMESTAMPTZ
  - retry_count INT default 0

Migration chain:
  0063_api_audit_log -> 0064_ingest_failed_records
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0064_ingest_failed_records"
down_revision: Union[str, None] = "0063_api_audit_log"


def upgrade() -> None:
    op.create_table(
        "ingest_failed_records",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("plugin_id", sa.Text(), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ingest_failed_created_at", "ingest_failed_records", ["failed_at"])
    op.create_index(
        "idx_ingest_failed_retry_count",
        "ingest_failed_records",
        ["retry_count"],
        postgresql_where=sa.text("retry_count < 3"),
    )


def downgrade() -> None:
    op.drop_index("idx_ingest_failed_retry_count")
    op.drop_index("idx_ingest_failed_created_at")
    op.drop_table("ingest_failed_records")
