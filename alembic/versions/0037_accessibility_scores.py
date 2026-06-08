"""Create accessibility_scores table for continuous travel-time scoring (T-757, T-1039).

Migration chain:
    0035_evaluate_jobs -> 0036_supply_pipeline -> 0037_accessibility_scores

Columns:
    id                  UUID PK (gen_random_uuid)
    market              TEXT NOT NULL (market name)
    destination_name    TEXT NOT NULL (employment hub name)
    travel_time_min     FLOAT NOT NULL (minutes)
    distance_km         FLOAT (kilometers)
    mode                TEXT DEFAULT 'driving'
    traffic_condition   TEXT DEFAULT 'typical'
    measured_at         TIMESTAMPTZ DEFAULT NOW()
    accessibility_score FLOAT (per-destination component)

Constraints:
    UNIQUE (market, destination_name, mode, measured_at::DATE)
    Index on (market, measured_at DESC) for latest-per-market queries
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0037_accessibility_scores"
down_revision: Union[str, None] = "0036_supply_pipeline"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        "accessibility_scores",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("market", sa.Text(), nullable=False),
        sa.Column("destination_name", sa.Text(), nullable=False),
        sa.Column("travel_time_min", sa.Float(), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False, server_default="driving"),
        sa.Column("traffic_condition", sa.Text(), nullable=False, server_default="typical"),
        sa.Column(
            "measured_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("accessibility_score", sa.Float(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_accessibility_per_day",
        "accessibility_scores",
        ["market", "destination_name", "mode", sa.text("(measured_at AT TIME ZONE 'Asia/Kolkata')::DATE")],
    )
    op.create_index(
        "idx_accessibility_market_measured",
        "accessibility_scores",
        ["market", sa.text("measured_at DESC")],
    )


def downgrade():
    op.drop_index("idx_accessibility_market_measured", table_name="accessibility_scores")
    op.drop_constraint("uq_accessibility_per_day", "accessibility_scores", type_="unique")
    op.drop_table("accessibility_scores")
