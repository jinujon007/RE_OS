"""Add data_source column to corridor_boundaries + seed OSM geometry (T-1236).

Migration chain:
    0064_ingest_failed_records -> 0065_corridor_boundaries_v2

Updates the 3 corridor boundary rows with:
- data_source column (varchar, 'approximate' or 'osm')
- Optionally updated geom if OSM data is available at migration time.

The data_source field tracks whether geometry is from OSM (accurate)
or approximated from WKT bounding boxes.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision: str = "0065_corridor_boundaries_v2"
down_revision: Union[str, None] = "0064_ingest_failed_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "corridor_boundaries",
        sa.Column("data_source", sa.String(20), nullable=True,
                  server_default="approximate"),
    )

    op.add_column(
        "corridor_boundaries",
        sa.Column("bbox_geom", Geometry("POLYGON", srid=4326), nullable=True),
    )

    op.execute("""
        COMMENT ON COLUMN corridor_boundaries.data_source
        IS 'geometry origin: osm=Overpass API, approximate=WKT bounding box'
    """)


def downgrade() -> None:
    op.drop_column("corridor_boundaries", "bbox_geom")
    op.drop_column("corridor_boundaries", "data_source")
