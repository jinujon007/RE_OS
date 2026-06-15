"""ON DELETE SET NULL on orphan-risk foreign keys (T-1085 GATE-81).

Changes listings.rera_project_id and kaveri_registrations.rera_project_id
to ON DELETE SET NULL so that a deleted rera_projects row cleanly nullifies
child FK values instead of blocking cleanup (default RESTRICT).

Migration chain:
    0045_materialized_market_brief -> 0046_fk_on_delete_set_null
"""

from typing import Union

from alembic import op

revision: str = "0046_fk_on_delete_set_null"
down_revision: Union[str, None] = "0045_materialized_market_brief"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_LISTINGS_FK = "listings_rera_project_id_fkey"
_REGISTRATIONS_FK = "kaveri_registrations_rera_project_id_fkey"


def upgrade():
    # listings.rera_project_id -> rera_projects.id
    op.drop_constraint(_LISTINGS_FK, "listings", type_="foreignkey")
    op.create_foreign_key(
        _LISTINGS_FK,
        "listings",
        "rera_projects",
        ["rera_project_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # kaveri_registrations.rera_project_id -> rera_projects.id
    op.drop_constraint(_REGISTRATIONS_FK, "kaveri_registrations", type_="foreignkey")
    op.create_foreign_key(
        _REGISTRATIONS_FK,
        "kaveri_registrations",
        "rera_projects",
        ["rera_project_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    # Restore listings FK to no ondelete (default RESTRICT)
    op.drop_constraint(_LISTINGS_FK, "listings", type_="foreignkey")
    op.create_foreign_key(
        _LISTINGS_FK,
        "listings",
        "rera_projects",
        ["rera_project_id"],
        ["id"],
    )

    # Restore kaveri_registrations FK to no ondelete (default RESTRICT)
    op.drop_constraint(_REGISTRATIONS_FK, "kaveri_registrations", type_="foreignkey")
    op.create_foreign_key(
        _REGISTRATIONS_FK,
        "kaveri_registrations",
        "rera_projects",
        ["rera_project_id"],
        ["id"],
    )
