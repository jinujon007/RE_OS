"""Create parcels table + parcel_id FK on rera_projects and registered_transactions.

Creates the parcels table making survey_no a first-class entity, and wires
parcel_id FK columns (ON DELETE SET NULL) on rera_projects,
registered_transactions, and kaveri_registrations per Sprint 81 pattern.

geom uses PostGIS Polygon type (SRID 4326) via GeoAlchemy2 for spatial joins.

Migration chain:
    0054_registered_transactions_karnataka_index -> 0055_parcels_table
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision: str = "0055_parcels_table"
down_revision: Union[str, None] = "0054_registered_transactions_karnataka_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parcels",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("district", sa.Text(), nullable=True),
        sa.Column("taluk", sa.Text(), nullable=True),
        sa.Column("hobli", sa.Text(), nullable=True),
        sa.Column("village", sa.Text(), nullable=False),
        sa.Column("survey_no", sa.Text(), nullable=False),
        sa.Column("survey_no_raw", sa.Text(), nullable=True),
        sa.Column("extent_sqft", sa.Numeric(), nullable=True),
        sa.Column("geom", Geometry("POLYGON", srid=4326), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
        sa.UniqueConstraint("village", "survey_no", name="uq_parcels_village_survey_no"),
    )

    op.create_index("idx_parcels_village_survey_no", "parcels", ["village", "survey_no"])
    op.create_index("idx_parcels_village", "parcels", ["village"])
    op.create_index("idx_parcels_survey_no", "parcels", ["survey_no"])
    op.create_index("idx_parcels_district", "parcels", ["district"])

    op.add_column("rera_projects",
        sa.Column("parcel_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_rera_projects_parcel_id",
        "rera_projects", "parcels",
        ["parcel_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_rera_projects_parcel_id", "rera_projects", ["parcel_id"])

    op.add_column("registered_transactions",
        sa.Column("parcel_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_registered_transactions_parcel_id",
        "registered_transactions", "parcels",
        ["parcel_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_registered_transactions_parcel_id", "registered_transactions", ["parcel_id"])

    op.add_column("kaveri_registrations",
        sa.Column("parcel_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_kaveri_registrations_parcel_id",
        "kaveri_registrations", "parcels",
        ["parcel_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_kaveri_registrations_parcel_id", "kaveri_registrations", ["parcel_id"])


def downgrade() -> None:
    op.drop_index("idx_kaveri_registrations_parcel_id", table_name="kaveri_registrations")
    op.drop_constraint("fk_kaveri_registrations_parcel_id", "kaveri_registrations", type_="foreignkey")
    op.drop_column("kaveri_registrations", "parcel_id")

    op.drop_index("idx_registered_transactions_parcel_id", table_name="registered_transactions")
    op.drop_constraint("fk_registered_transactions_parcel_id", "registered_transactions", type_="foreignkey")
    op.drop_column("registered_transactions", "parcel_id")

    op.drop_index("idx_rera_projects_parcel_id", table_name="rera_projects")
    op.drop_constraint("fk_rera_projects_parcel_id", "rera_projects", type_="foreignkey")
    op.drop_column("rera_projects", "parcel_id")

    op.drop_index("idx_parcels_district", table_name="parcels")
    op.drop_index("idx_parcels_survey_no", table_name="parcels")
    op.drop_index("idx_parcels_village", table_name="parcels")
    op.drop_index("idx_parcels_village_survey_no", table_name="parcels")
    op.drop_constraint("uq_parcels_village_survey_no", "parcels", type_="unique")
    op.drop_table("parcels")
