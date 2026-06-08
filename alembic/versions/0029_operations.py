"""Create projects, project_tasks, deal_velocity tables (Sprint 58 — Operations Dept)

Tables for project milestone tracking, task assignment, and deal velocity metrics.
Part of the Operations Department build-out (GATE-66).

Migration chain:
    0028_landowner_contacts -> 0029_operations
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0029_operations"
down_revision: Union[str, None] = "0028_landowner_contacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"),
                   primary_key=True, nullable=False),
        sa.Column("name", sa.TEXT(), nullable=False),
        sa.Column("market", sa.VARCHAR(100), nullable=True),
        sa.Column("survey_no", sa.VARCHAR(50), nullable=True),
        sa.Column("deal_type", sa.VARCHAR(20), nullable=True),
        sa.Column("status", sa.VARCHAR(30), server_default=sa.text("'lead'"),
                   nullable=False),
        sa.Column("source_deal_id", sa.UUID(), nullable=True),
        sa.Column("source_board_session_id", sa.UUID(), nullable=True),
        sa.Column("pm_agent_id", sa.VARCHAR(100), nullable=True),
        sa.Column("start_date", sa.DATE(), nullable=True),
        sa.Column("target_close_date", sa.DATE(), nullable=True),
        sa.Column("actual_close_date", sa.DATE(), nullable=True),
        sa.Column("notes", sa.TEXT(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"),
                   nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"),
                   nullable=True),
        sa.ForeignKeyConstraint(["source_deal_id"], ["deal_pipeline.id"],
                                 ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_board_session_id"], ["board_sessions.session_id"],
                                 ondelete="SET NULL"),
    )
    op.create_check_constraint("ck_projects_status", "projects",
        "status IN ('lead','mou','loi','signed','rera_applied','construction','possession','delivered','paused')")
    op.create_index("idx_projects_status", "projects", ["status"])
    op.create_index("idx_projects_market", "projects", ["market"])

    op.create_table(
        "project_tasks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"),
                   primary_key=True, nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.TEXT(), nullable=False),
        sa.Column("owner_agent_id", sa.VARCHAR(100), nullable=True),
        sa.Column("dept", sa.VARCHAR(30), nullable=True),
        sa.Column("status", sa.VARCHAR(20), server_default=sa.text("'todo'"),
                   nullable=True),
        sa.Column("due_date", sa.DATE(), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("notes", sa.TEXT(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"),
                   nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                 ondelete="CASCADE"),
    )
    op.create_check_constraint("ck_project_tasks_status", "project_tasks",
        "status IN ('todo','in_progress','done','blocked')")
    op.create_index("idx_project_tasks_project_status", "project_tasks",
                     ["project_id", "status"])

    op.create_table(
        "deal_velocity",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"),
                   primary_key=True, nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("from_status", sa.VARCHAR(30), nullable=True),
        sa.Column("to_status", sa.VARCHAR(30), nullable=True),
        sa.Column("days_elapsed", sa.INTEGER(), nullable=True),
        sa.Column("transitioned_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"),
                   nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_deal_velocity_project", "deal_velocity", ["project_id"])
    op.create_index("idx_project_tasks_dept", "project_tasks", ["dept"])


def downgrade():
    op.drop_index("idx_deal_velocity_project", table_name="deal_velocity")
    op.drop_index("idx_project_tasks_dept", table_name="project_tasks")
    op.drop_table("deal_velocity")
    op.drop_index("idx_project_tasks_project_status", table_name="project_tasks")
    op.drop_constraint("ck_project_tasks_status", "project_tasks", type_="check")
    op.drop_table("project_tasks")
    op.drop_index("idx_projects_status", table_name="projects")
    op.drop_index("idx_projects_market", table_name="projects")
    op.drop_constraint("ck_projects_status", "projects", type_="check")
    op.drop_table("projects")
