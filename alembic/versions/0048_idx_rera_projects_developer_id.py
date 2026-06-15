"""Standalone B-tree index on rera_projects.developer_id (T-1087 GATE-81).

Developer scorecard queries join on this column alone. Existing composite
indexes are insufficient for single-column lookups at 10,000+ row scale.

Migration chain:
    0047_check_constraints_integrity -> 0048_idx_rera_projects_developer_id
"""

from typing import Union

from alembic import op

revision: str = "0048_idx_rera_projects_developer_id"
down_revision: Union[str, None] = "0047_check_constraints_integrity"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_index(
        "idx_rera_projects_developer_id",
        "rera_projects",
        ["developer_id"],
    )


def downgrade():
    op.drop_index("idx_rera_projects_developer_id", "rera_projects")
