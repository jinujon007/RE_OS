"""Create developer_pricing_history table + v_developer_price_moves view.

Tracks developer PSF changes over time for competitive intelligence:
Grade A developers adjusting prices is a 2-3 month leading indicator.

Table: developer_pricing_history
  One row per (developer, project, scrape_date) unique.
  psf_listed is NULL when only total_price_inr is available (no area data).
  total_price_inr stores the raw total project price from developer sites.
  change_pct computed vs prior scrape for same (developer, project).

View: v_developer_price_moves
  Projects in last 30 days where ABS(change_pct) >= 2%, ranked by recency.
  Filters to rows with non-null psf_listed (PSF-based comparisons only).

Revision ID: 0071_developer_pricing_history
Revises: 0070_merge_0069_heads
Create Date: 2026-06-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0071_developer_pricing_history"
down_revision: Union[str, None] = "0070_merge_0069_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "developer_pricing_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("developer_name", sa.String(200), nullable=False),
        sa.Column("market", sa.String(100), nullable=False),
        sa.Column("project_name", sa.String(300), nullable=False),
        sa.Column("psf_listed", sa.Numeric(10, 2), nullable=True),
        sa.Column("total_price_inr", sa.Numeric(12, 2), nullable=True),
        sa.Column("psf_launch", sa.Numeric(10, 2), nullable=True),
        sa.Column("scrape_date", sa.Date(), nullable=False),
        sa.Column("change_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("prior_psf", sa.Numeric(10, 2), nullable=True),
        sa.UniqueConstraint(
            "developer_name", "project_name", "scrape_date",
            name="uq_dev_price_per_day",
        ),
    )
    op.create_index(
        "ix_dev_price_market_dev",
        "developer_pricing_history",
        ["market", "developer_name"],
    )
    op.create_index(
        "ix_dev_price_scrape_date",
        "developer_pricing_history",
        ["scrape_date"],
    )

    op.execute("COMMENT ON TABLE developer_pricing_history IS "
               "'Per-scrape developer project pricing snapshot for competitive intelligence'")
    op.execute("COMMENT ON COLUMN developer_pricing_history.psf_listed IS "
               "'PSF value (NULL when only total_price_inr available — no area data)'")
    op.execute("COMMENT ON COLUMN developer_pricing_history.total_price_inr IS "
               "'Raw total project price in INR from developer site (e.g. 27900000 for ₹2.79Cr)'")
    op.execute("COMMENT ON COLUMN developer_pricing_history.change_pct IS "
               "'Percent change vs prior scrape for same developer+project (NULL on first observation)'")
    op.execute("COMMENT ON COLUMN developer_pricing_history.prior_psf IS "
               "'PSF from prior scrape, used to compute change_pct (filtered to last 90 days)'")

    op.execute("""
        CREATE OR REPLACE VIEW v_developer_price_moves AS
        SELECT
            developer_name,
            market,
            project_name,
            prior_psf,
            psf_listed AS current_psf,
            change_pct,
            scrape_date
        FROM developer_pricing_history
        WHERE scrape_date >= CURRENT_DATE - INTERVAL '30 days'
          AND change_pct IS NOT NULL
          AND psf_listed IS NOT NULL
          AND ABS(change_pct) >= 2
        ORDER BY scrape_date DESC, ABS(change_pct) DESC
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_developer_price_moves")
    op.drop_index("ix_dev_price_scrape_date", table_name="developer_pricing_history")
    op.drop_index(
        "ix_dev_price_market_dev", table_name="developer_pricing_history"
    )
    op.drop_table("developer_pricing_history")
