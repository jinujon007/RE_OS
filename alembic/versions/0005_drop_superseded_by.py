"""drop unused superseded_by column from agent_memories"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_drop_superseded_by"
down_revision: Union[str, None] = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("agent_memories", "superseded_by")


def downgrade() -> None:
    op.add_column(
        "agent_memories",
        sa.Column("superseded_by", sa.UUID(), nullable=True),
    )
