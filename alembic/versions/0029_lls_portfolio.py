"""Create lls_portfolio table for Investor Readiness (Sprint 57 — GATE-65)

LLS Pedigree section: seeded with promoter/founder track record from prior
firms (Puravankara, Confident Group, Kent Construction, TVS Emerald) since
LLS is a new startup with no completed projects (J-8 resolution 2026-06-08).

Migration chain:
    0028_landowner_contacts -> 0029_lls_portfolio
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0029_lls_portfolio"
down_revision: Union[str, None] = "0028_landowner_contacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        "lls_portfolio",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("project_name", sa.TEXT(), nullable=False),
        sa.Column("location", sa.TEXT(), nullable=True),
        sa.Column("market", sa.VARCHAR(100), nullable=True),
        sa.Column("segment", sa.VARCHAR(30), nullable=True),
        sa.Column("total_units", sa.INTEGER(), nullable=True),
        sa.Column("sold_units", sa.INTEGER(), nullable=True),
        sa.Column("launched_date", sa.DATE(), nullable=True),
        sa.Column("possession_date", sa.DATE(), nullable=True),
        sa.Column("land_cost_cr", sa.NUMERIC(12, 2), nullable=True),
        sa.Column("gdv_cr", sa.NUMERIC(12, 2), nullable=True),
        sa.Column("realized_irr_pct", sa.NUMERIC(5, 2), nullable=True),
        sa.Column("status", sa.VARCHAR(20), server_default=sa.text("'planned'"), nullable=True),
        sa.Column("rera_no", sa.VARCHAR(100), nullable=True),
        sa.Column("notes", sa.TEXT(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("NOW()"), nullable=True),
    )
    op.create_check_constraint("ck_lls_portfolio_segment",
        "lls_portfolio",
        "segment IN ('affordable','mid_market','premium','luxury')",
    )
    op.create_check_constraint("ck_lls_portfolio_status",
        "lls_portfolio",
        "status IN ('delivered','ongoing','planned','paused')",
    )
    op.create_index("idx_lls_portfolio_status", "lls_portfolio", ["status"])
    op.create_index("idx_lls_portfolio_market", "lls_portfolio", ["market"])


def downgrade():
    op.drop_index("idx_lls_portfolio_market", table_name="lls_portfolio")
    op.drop_index("idx_lls_portfolio_status", table_name="lls_portfolio")
    op.drop_constraint("ck_lls_portfolio_status", "lls_portfolio", type_="check")
    op.drop_constraint("ck_lls_portfolio_segment", "lls_portfolio", type_="check")
    op.drop_table("lls_portfolio")
