"""CHECK constraints: zero-PSF and empty registration number (T-1086 GATE-81).

Blocks garbage data at the DB level without requiring application logic:
- guidance_values.guidance_value_psf > 0 (no zero/negative PSF)
- kaveri_registrations.registration_number IS NULL OR length > 0 (no '')

Pre-cleans existing garbage before adding constraints.

Migration chain:
    0046_fk_on_delete_set_null -> 0047_check_constraints_integrity
"""

from typing import Union

from alembic import op

revision: str = "0047_check_constraints_integrity"
down_revision: Union[str, None] = "0046_fk_on_delete_set_null"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    # Clean existing garbage before adding constraints
    op.execute(
        "DELETE FROM guidance_values "
        "WHERE guidance_value_psf IS NULL OR guidance_value_psf <= 0"
    )
    op.execute(
        "UPDATE kaveri_registrations "
        "SET registration_number = NULL "
        "WHERE registration_number = ''"
    )

    # CHECK: no zero/negative PSF
    op.create_check_constraint(
        "ck_guidance_values_psf_positive",
        "guidance_values",
        "guidance_value_psf > 0",
    )

    # CHECK: no empty string registration numbers (NULL is fine)
    op.create_check_constraint(
        "ck_kaveri_reg_no_nonempty",
        "kaveri_registrations",
        "registration_number IS NULL OR length(trim(registration_number)) > 0",
    )


def downgrade():
    op.drop_constraint(
        "ck_kaveri_reg_no_nonempty", "kaveri_registrations", type_="check"
    )
    op.drop_constraint(
        "ck_guidance_values_psf_positive", "guidance_values", type_="check"
    )
