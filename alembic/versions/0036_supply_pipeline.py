"""Create supply_pipeline table for land supply pipeline (Sprint 73 — GATE-73).

Migration chain:
    0035_evaluate_jobs -> 0036_supply_pipeline
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0036_supply_pipeline"
down_revision: Union[str, None] = "0035_evaluate_jobs"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        "supply_pipeline",
        sa.Column("id", UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("project_name", sa.Text(), nullable=True),
        sa.Column("developer_name", sa.Text(), nullable=True),
        sa.Column("estimated_units", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("estimated_acres", sa.Float(), nullable=True),
        sa.Column(
            "source", sa.Text(), nullable=False,
        ),
        sa.Column("approval_date", sa.Date(), nullable=True),
        sa.Column("expected_completion_year", sa.Integer(), nullable=True),
        sa.Column("raw_snippet", sa.Text(), nullable=True),
        sa.Column("data_source", sa.Text(), nullable=False, server_default=sa.text("'scraped'")),
        sa.Column("ingest_log_id", UUID(as_uuid=False), sa.ForeignKey("ingest_log.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_check_constraint(
        "ck_supply_pipeline_source",
        "supply_pipeline",
        "source IN ('rera_pipeline', 'kiadb_tender', 'bda_news', 'bmrda')",
    )
    op.create_unique_constraint(
        "uq_supply_pipeline_market_project_source",
        "supply_pipeline",
        ["market", "project_name", "source"],
    )


def downgrade():
    op.drop_constraint("uq_supply_pipeline_market_project_source", "supply_pipeline", type_="unique")
    op.drop_constraint("ck_supply_pipeline_source", "supply_pipeline", type_="check")
    op.drop_table("supply_pipeline")
