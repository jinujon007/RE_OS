"""Create parcel_graph_edges table for Persisting ParcelGraph results (GATE-155).

Stores edges between survey numbers computed by ParcelGraph.build().
Shared_buyer edges capture aggregation signals; adjacency edges capture
contiguous parcels. Edge_weight decays with transaction recency.

Business columns (market, village, survey_a, survey_b) are NOT NULL so
the UNIQUE constraint correctly enforces deduplication across all 4 dimensions.

Revision ID: 0075_parcel_graph_edges
Revises: 0074_deed_village_priority
Create Date: 2026-06-29
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0075_parcel_graph_edges"
down_revision: Union[str, None] = "0074_deed_village_priority"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parcel_graph_edges",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("market", sa.String(100), nullable=False),
        sa.Column("village", sa.String(200), nullable=False),
        sa.Column("survey_a", sa.String(100), nullable=False),
        sa.Column("survey_b", sa.String(100), nullable=False),
        sa.Column("shared_buyer", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("transaction_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "edge_weight",
            sa.Numeric(6, 4),
            sa.CheckConstraint("edge_weight >= 0"),
            nullable=False,
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "market", "village", "survey_a", "survey_b",
            name="uq_parcel_graph_edges",
        ),
    )
    op.create_index(
        "idx_parcel_graph_market_village",
        "parcel_graph_edges",
        ["market", "village"],
    )


def downgrade() -> None:
    op.drop_index("idx_parcel_graph_market_village", table_name="parcel_graph_edges")
    op.drop_table("parcel_graph_edges")
