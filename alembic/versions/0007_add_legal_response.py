"""Add legal_response column to board_sessions for Legal Head agent (T-347).

After T-347 added the 5th dept head (Legal), the board_sessions table needs
a dedicated column to store its response alongside bd/finance/engineering/ops.

Revision ID: 0007_add_legal_response
Revises: 0006_add_last_scraped_at
Create Date: 2026-05-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_add_legal_response"
down_revision: Union[str, None] = "0006_add_last_scraped_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("board_sessions", sa.Column("legal_response", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("board_sessions", "legal_response")
