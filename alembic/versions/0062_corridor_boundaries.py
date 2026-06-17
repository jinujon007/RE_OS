"""Create corridor_boundaries table + seed 3 PostGIS WKT polygons (GATE-100, T-1190).

Stores approximate corridor polygons for spatial corridor membership queries.
Each row is a named corridor with a PostGIS polygon boundary and metadata.

Seeded on creation:
  1. NH-44         (Yelahanka-Attur-Doddajala strip)
  2. Hebbal-Yelahanka (Nagawara-Sahakarnagar-Vidyaranyapura)
  3. Doddaballapur Road (Chokkanahalli-Sampigehalli strip)

Migration chain:
    0061_parcel_ownership_chain -> 0062_corridor_boundaries
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0062_corridor_boundaries"
down_revision: Union[str, None] = "0061_parcel_ownership_chain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    _ensure_postgis()

    op.create_table(
        "corridor_boundaries",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("corridor_id", sa.String(50), nullable=False, unique=True),
        sa.Column("corridor_name", sa.String(200), nullable=True),
        sa.Column("primary_market", sa.String(100), nullable=True),
        sa.Column("geom", postgresql.GEOMETRY("POLYGON", 4326), nullable=True),
        sa.Column("gcc_hubs", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "seeded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )

    _create_gist_index("idx_corridor_boundaries_geom", "corridor_boundaries", "geom")
    op.create_index(
        "idx_corridor_boundaries_corridor_id",
        "corridor_boundaries",
        ["corridor_id"],
    )

    _seed_boundaries()

    op.execute(
        "ALTER TABLE corridor_boundaries "
        "ADD CONSTRAINT chk_corridor_boundaries_valid_geom "
        "CHECK (geom IS NULL OR ST_IsValid(geom))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE corridor_boundaries DROP CONSTRAINT IF EXISTS chk_corridor_boundaries_valid_geom"
    )
    op.drop_index(
        "idx_corridor_boundaries_corridor_id",
        table_name="corridor_boundaries",
    )
    op.execute(
        "DROP INDEX IF EXISTS idx_corridor_boundaries_geom"
    )
    op.drop_table("corridor_boundaries")


def _ensure_postgis() -> None:
    """Enable PostGIS extension; no-op if already available."""
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    except Exception:
        from alembic import op as _op
        _op.execute("SELECT PostGIS_Version()")


def _create_gist_index(index_name: str, table: str, column: str) -> None:
    """Create a GiST index via raw SQL (works across Alembic versions)."""
    op.execute(
        f"CREATE INDEX {index_name} ON {table} USING GIST ({column})"
    )


def _seed_boundaries() -> None:
    """Seed the 3 corridor boundary polygons."""
    op.execute("""
    INSERT INTO corridor_boundaries (corridor_id, corridor_name, primary_market, geom, gcc_hubs, notes)
    VALUES
      ('nh44', 'NH-44 (Yelahanka -> Devanahalli)', 'Yelahanka',
       ST_SetSRID(ST_MakeEnvelope(77.555, 13.090, 77.605, 13.150), 4326),
       ARRAY['Manyata Tech Park', 'Karle Tech Park'],
       'Approximate 2km-wide bounding box along NH-44 Bellary Road strip. Center ~13.12N 77.58E.'),
      ('hebbal_yelahanka', 'Hebbal-Yelahanka Inner Road', 'Hebbal',
       ST_SetSRID(ST_MakeEnvelope(77.545, 13.020, 77.595, 13.080), 4326),
       ARRAY['Manyata Tech Park'],
       'Approximate 2km-wide bounding box covering Nagawara-Sahakarnagar-Vidyaranyapura. Center ~13.05N 77.57E.'),
      ('doddaballapur', 'Doddaballapur Road', 'Yelahanka',
       ST_SetSRID(ST_MakeEnvelope(77.615, 13.120, 77.665, 13.180), 4326),
       ARRAY['Manyata Tech Park', 'Karle Tech Park'],
       'Approximate 2km-wide bounding box along Doddaballapur Road. Center ~13.15N 77.64E.')
    """)
