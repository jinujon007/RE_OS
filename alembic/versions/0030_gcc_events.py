"""Create gcc_events table — GCC Demand Scout (Sprint 67 — GATE-71)

Tracks Global Capability Center announcements as forward-looking demand signals.
Each event is scored for North Bengaluru residential demand impact and feeds
demand_score_v2 as a 5th component (gcc_north_norm × 0.15).

Migration chain:
    0029_lls_portfolio + 0029_operations (merge) -> 0030_gcc_events
"""

from typing import Sequence, Tuple, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0030_gcc_events"
down_revision: Union[Tuple[str, str], None] = (
    "0029_lls_portfolio",
    "0029_operations",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None

_ENTRANT_TYPES = ("'NEW'", "'EXPANSION'", "'RELOCATION'", "'CONSOLIDATION'")
_WORK_MODELS = ("'FULL_OFFICE'", "'HYBRID'", "'REMOTE_FRIENDLY'")
_MATURITY_LEVELS = (1, 2, 3, 4)
_SOURCE_RELIABILITY = ("'OFFICIAL'", "'VERIFIED'", "'PRESS'", "'ESTIMATED'")
_TIME_HORIZONS = ("'0-12m'", "'1-3y'", "'3-5y'")


def upgrade():
    op.create_table(
        "gcc_events",
        sa.Column(
            "id",
            UUID(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        # Dedup key: slugify(company + location + announced_year_month)
        sa.Column("canonical_id", sa.VARCHAR(200), nullable=False),
        # Company identity
        sa.Column("company", sa.VARCHAR(200), nullable=False),
        sa.Column("sector", sa.VARCHAR(100), nullable=True),
        sa.Column("country_of_origin", sa.VARCHAR(100), nullable=True),
        # Location + corridor
        sa.Column("bengaluru_location", sa.VARCHAR(200), nullable=True),
        sa.Column("nearest_corridor", sa.VARCHAR(100), nullable=True),
        # Classification tags (three mandatory)
        sa.Column("entrant_type", sa.VARCHAR(20), nullable=True),
        sa.Column("work_model", sa.VARCHAR(20), nullable=True),
        sa.Column(
            "signal_maturity_level",
            sa.SmallInteger(),
            nullable=True,
        ),
        sa.Column(
            "is_negative_signal",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        # Impact scores
        sa.Column(
            "north_bengaluru_impact_score",
            sa.Numeric(4, 2),
            nullable=True,
        ),
        # Deal metrics
        sa.Column("investment_cr", sa.Numeric(12, 2), nullable=True),
        sa.Column("planned_headcount", sa.Integer(), nullable=True),
        sa.Column("headcount_timeline_months", sa.Integer(), nullable=True),
        sa.Column("median_ctc_l", sa.Numeric(8, 2), nullable=True),
        sa.Column("office_sqft", sa.Integer(), nullable=True),
        # Sub-scores (0–10 each)
        sa.Column("demand_creation_score", sa.SmallInteger(), nullable=True),
        sa.Column("residential_impact_score", sa.SmallInteger(), nullable=True),
        sa.Column("appreciation_impact_score", sa.SmallInteger(), nullable=True),
        sa.Column("rental_impact_score", sa.SmallInteger(), nullable=True),
        # Composite score (can be negative for CONSOLIDATION events)
        sa.Column("gcc_signal_score", sa.Numeric(5, 2), nullable=True),
        # Demand classification
        sa.Column("primary_housing_segment", sa.VARCHAR(50), nullable=True),
        sa.Column("time_horizon", sa.VARCHAR(10), nullable=True),
        sa.Column("estimated_demand_units", sa.Integer(), nullable=True),
        # Source provenance
        sa.Column("source_url", sa.VARCHAR(500), nullable=True),
        sa.Column("source_name", sa.VARCHAR(100), nullable=True),
        sa.Column("source_reliability", sa.VARCHAR(20), nullable=True),
        sa.Column("announced_at", sa.Date(), nullable=True),
        # Alert tracking
        sa.Column(
            "discord_alert_fired",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # Constraints
        sa.UniqueConstraint("canonical_id", name="uq_gcc_events_canonical_id"),
        sa.CheckConstraint(
            f"entrant_type IN ({', '.join(_ENTRANT_TYPES)})",
            name="ck_gcc_entrant_type",
        ),
        sa.CheckConstraint(
            f"work_model IN ({', '.join(_WORK_MODELS)})",
            name="ck_gcc_work_model",
        ),
        sa.CheckConstraint(
            f"signal_maturity_level IN ({', '.join(str(lvl) for lvl in _MATURITY_LEVELS)})",
            name="ck_gcc_maturity_level",
        ),
        sa.CheckConstraint(
            f"source_reliability IN ({', '.join(_SOURCE_RELIABILITY)})",
            name="ck_gcc_source_reliability",
        ),
        sa.CheckConstraint(
            f"time_horizon IN ({', '.join(_TIME_HORIZONS)})",
            name="ck_gcc_time_horizon",
        ),
        sa.CheckConstraint(
            "north_bengaluru_impact_score BETWEEN 0.0 AND 1.0",
            name="ck_gcc_nb_impact_range",
        ),
    )

    op.create_index(
        "idx_gcc_events_corridor_score",
        "gcc_events",
        ["nearest_corridor", "gcc_signal_score", "announced_at"],
    )
    op.create_index(
        "idx_gcc_events_maturity_nb",
        "gcc_events",
        ["signal_maturity_level", "north_bengaluru_impact_score"],
        postgresql_where=sa.text("is_negative_signal = FALSE"),
    )
    op.create_index(
        "idx_gcc_events_alert_pending",
        "gcc_events",
        ["discord_alert_fired", "gcc_signal_score"],
        postgresql_where=sa.text(
            "discord_alert_fired = FALSE AND is_negative_signal = FALSE"
        ),
    )


def downgrade():
    op.drop_index("idx_gcc_events_alert_pending", "gcc_events")
    op.drop_index("idx_gcc_events_maturity_nb", "gcc_events")
    op.drop_index("idx_gcc_events_corridor_score", "gcc_events")
    op.drop_table("gcc_events")
