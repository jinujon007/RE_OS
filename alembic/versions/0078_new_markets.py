"""Insert Thanisandra and Bagalur into micro_markets (GATE-170 / T-1537).

Adds two new markets to the existing micro_markets table:
- Thanisandra: Bengaluru Urban, North zone
- Bagalur: Bengaluru Rural, North zone

Revision ID: 0078_new_markets
Revises: 0077_deal_score_log
Create Date: 2026-07-03
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text

revision: str = "0078_new_markets"
down_revision: Union[str, None] = "0077_deal_score_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # micro_markets live schema: name, slug (unique, NOT NULL), city, state, priority.
    # No lat/lon/district/zone columns exist — coords live in utils/strr_overlay.py.
    op.execute(
        text("""
            INSERT INTO micro_markets (name, slug, city, state, priority)
            VALUES
                ('Thanisandra', 'thanisandra', 'Bengaluru', 'Karnataka', 1),
                ('Bagalur', 'bagalur', 'Bengaluru', 'Karnataka', 1)
            ON CONFLICT (slug) DO NOTHING
        """)
    )


def downgrade() -> None:
    op.execute(
        text("DELETE FROM micro_markets WHERE slug IN ('thanisandra', 'bagalur')")
    )
