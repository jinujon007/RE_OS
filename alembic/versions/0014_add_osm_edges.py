"""Add osm_edges table (Tier 1 — Geospatial Foundation).
Revision ID: 0014_add_osm_edges
Revises: 0013_add_igr_transactions
Create Date: 2026-06-02
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0014_add_osm_edges"
down_revision: Union[str, None] = "0013_add_igr_transactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "osm_edges",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("market", sa.String(100), nullable=False),
        sa.Column("u", sa.BigInteger(), nullable=False),
        sa.Column("v", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.Integer(), nullable=True),
        sa.Column("osmid", sa.BigInteger(), nullable=True),
        sa.Column("length", sa.Float(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("highway", sa.Text(), nullable=True),
        sa.Column("geom", sa.dialects.postgresql.GEOMETRY("LineString", 4326), nullable=True),
    )
    op.create_index(
        "idx_osm_edges_market_geom",
        "osm_edges",
        [sa.text("market"), sa.text("geom")],
        postgresql_using="gist",
    )
    op.create_index("idx_osm_edges_u", "osm_edges", ["u"])
    op.create_index("idx_osm_edges_v", "osm_edges", ["v"])
    op.create_index("idx_osm_edges_uv", "osm_edges", ["u", "v"])


def downgrade() -> None:
    op.drop_index("idx_osm_edges_uv", table_name="osm_edges")
    op.drop_index("idx_osm_edges_v", table_name="osm_edges")
    op.drop_index("idx_osm_edges_u", table_name="osm_edges")
    op.drop_index("idx_osm_edges_market_geom", table_name="osm_edges")
    op.drop_table("osm_edges")
