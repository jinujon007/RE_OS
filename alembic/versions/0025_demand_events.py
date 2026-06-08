"""Create demand_events table + add config_absorption to market_snapshots

Creates the demand_events table for tracking demand-side signals
(NRI queries, bulk inquiries, listing surges, price cuts, portal highlights)
and adds a config_absorption JSONB column to market_snapshots.

Migration chain:
    0024_news_tone_columns -> 0025_demand_events
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "0025_demand_events"
down_revision: Union[str, None] = "0024_news_tone_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


_VALID_EVENT_TYPES = (
    "'nri_query'", "'bulk_inquiry'", "'listing_surge'",
    "'price_cut'", "'portal_highlight'",
)


def upgrade():
    op.create_table("demand_events",
        sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("market", sa.VARCHAR(100), nullable=False),
        sa.Column("event_type", sa.VARCHAR(50), nullable=False),
        sa.Column("count", sa.Integer(), server_default=sa.text("1")),
        sa.Column("value_cr", sa.NUMERIC(12, 2), nullable=True),
        sa.Column("source", sa.VARCHAR(100), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint(
            f"event_type IN ({', '.join(_VALID_EVENT_TYPES)})",
            name="ck_demand_events_event_type",
        ),
    )
    op.create_index("idx_demand_events_market_type", "demand_events", ["market", "event_type", "recorded_at"])
    op.add_column("market_snapshots",
        sa.Column("config_absorption", JSONB(), nullable=True)
    )


def downgrade():
    op.drop_column("market_snapshots", "config_absorption")
    op.drop_index("idx_demand_events_market_type", "demand_events")
    op.drop_table("demand_events")
