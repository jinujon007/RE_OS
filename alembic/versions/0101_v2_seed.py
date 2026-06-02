"""v2 Seed — run seed_v2.sql reference data.
Separate from schema migration so seed can be re-run independently.
Revision ID: 0101_v2_seed
Revises: 0100_v2_schema
Create Date: 2026-06-02
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0101_v2_seed"
down_revision: Union[str, None] = "0100_v2_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    sql_path = op.get_context().script.dir / ".." / ".." / "database" / "seed_v2.sql"
    if sql_path.exists():
        with open(sql_path, encoding="utf-8") as f:
            op.execute(f.read())


def downgrade() -> None:
    pass
