"""Create govt_policy_events table for Govt/Infra/Policy Scout (Sprint 75 — GATE-75).

Migration chain:
    0037_accessibility_scores -> 0038_govt_policy_events

Columns:
    id                  SERIAL PK
    headline            TEXT NOT NULL
    category            infrastructure/govt_project/policy
    subcategory         metro/ring_road/industrial_park/etc.
    location_text       TEXT
    micro_markets       TEXT[]
    investment_cr       NUMERIC(12,2)
    stage               announcement/approval/tender/construction/operational
    impact_score        SMALLINT CHECK(1-10)
    signal_strength     high/emerging/risk
    demand_type         VARCHAR(30)
    time_horizon        immediate/medium/long
    actionability       buy_now/accumulate/monitor/avoid
    summary             TEXT
    why_it_matters      TEXT
    source_urls         TEXT[]
    published_date      DATE
    is_north_bengaluru  BOOLEAN DEFAULT FALSE
    scraped_at          TIMESTAMPTZ DEFAULT NOW()
    created_at          TIMESTAMPTZ DEFAULT NOW()

Indexes:
    (is_north_bengaluru, impact_score DESC)
    (category, scraped_at DESC)
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0038_govt_policy_events"
down_revision: Union[str, None] = "0037_accessibility_scores"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.create_table(
        "govt_policy_events",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("subcategory", sa.String(50), nullable=True),
        sa.Column("location_text", sa.Text(), nullable=True),
        sa.Column("micro_markets", ARRAY(sa.Text()), nullable=True),
        sa.Column("investment_cr", sa.Numeric(12, 2), nullable=True),
        sa.Column("stage", sa.String(20), nullable=True),
        sa.Column("impact_score", sa.SmallInteger(), nullable=True),
        sa.Column("signal_strength", sa.String(10), nullable=True),
        sa.Column("demand_type", sa.String(30), nullable=True),
        sa.Column("time_horizon", sa.String(10), nullable=True),
        sa.Column("actionability", sa.String(15), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("why_it_matters", sa.Text(), nullable=True),
        sa.Column("source_urls", ARRAY(sa.Text()), nullable=True),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("is_north_bengaluru", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("scraped_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_check_constraint(
        "ck_govt_policy_category",
        "govt_policy_events",
        "category IN ('infrastructure','govt_project','policy')",
    )
    op.create_check_constraint(
        "ck_govt_policy_stage",
        "govt_policy_events",
        "stage IN ('announcement','approval','tender','construction','operational')",
    )
    op.create_check_constraint(
        "ck_govt_policy_impact_score",
        "govt_policy_events",
        "impact_score BETWEEN 1 AND 10",
    )
    op.create_check_constraint(
        "ck_govt_policy_signal",
        "govt_policy_events",
        "signal_strength IN ('high','emerging','risk')",
    )
    op.create_check_constraint(
        "ck_govt_policy_horizon",
        "govt_policy_events",
        "time_horizon IN ('immediate','medium','long')",
    )
    op.create_check_constraint(
        "ck_govt_policy_actionability",
        "govt_policy_events",
        "actionability IN ('buy_now','accumulate','monitor','avoid')",
    )
    op.create_index(
        "idx_govt_policy_nb_impact",
        "govt_policy_events",
        ["is_north_bengaluru", sa.text("impact_score DESC")],
    )
    op.create_index(
        "idx_govt_policy_cat_scraped",
        "govt_policy_events",
        ["category", sa.text("scraped_at DESC")],
    )


def downgrade():
    op.drop_index("idx_govt_policy_cat_scraped", table_name="govt_policy_events")
    op.drop_index("idx_govt_policy_nb_impact", table_name="govt_policy_events")
    op.drop_table("govt_policy_events")
