"""Create evaluate_jobs table for persistent job tracking (Fix 10).

Previously EvaluateJob lived only in the _jobs in-memory dict —
container restarts dropped all in-flight and completed job records.
This table provides durable storage so GET /api/evaluate/<job_id>
survives a restart and results are auditable.

Migration chain:
    0034_developer_distress_signals -> 0035_evaluate_jobs
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0035_evaluate_jobs"
down_revision: Union[str, None] = "0034_developer_distress_signals"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        "evaluate_jobs",
        sa.Column(
            "job_id",
            UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("survey_no", sa.Text(), nullable=False),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("land_area_sqft", sa.Float(), nullable=False, server_default=sa.text("43560.0")),
        sa.Column("sell_psf", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("deal_type", sa.Text(), nullable=False, server_default="compare"),
        sa.Column("pitch", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("progress_msg", sa.Text(), nullable=False, server_default=""),
        sa.Column("board_session", JSONB, nullable=True),
        sa.Column("deal_memo", JSONB, nullable=True),
        sa.Column("investor_brief", JSONB, nullable=True),
        sa.Column("shareholder_round", JSONB, nullable=True),
        sa.Column(
            "deal_id",
            UUID(as_uuid=False),
            sa.ForeignKey("deals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_evaluate_jobs_status",
        "evaluate_jobs",
        "status IN ('pending','running','complete','failed')",
    )
    op.create_index(
        "idx_evaluate_jobs_market_created",
        "evaluate_jobs",
        ["market", "created_at"],
    )
    op.create_index(
        "idx_evaluate_jobs_status",
        "evaluate_jobs",
        ["status"],
    )


def downgrade():
    op.drop_index("idx_evaluate_jobs_status", table_name="evaluate_jobs")
    op.drop_index("idx_evaluate_jobs_market_created", table_name="evaluate_jobs")
    op.drop_constraint("ck_evaluate_jobs_status", "evaluate_jobs", type_="check")
    op.drop_table("evaluate_jobs")
