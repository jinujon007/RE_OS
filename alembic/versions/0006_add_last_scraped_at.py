"""add last_scraped_at to micro_markets"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_add_last_scraped_at"
down_revision: Union[str, None] = "0005_drop_superseded_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "micro_markets",
        sa.Column("last_scraped_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("micro_markets", "last_scraped_at")
