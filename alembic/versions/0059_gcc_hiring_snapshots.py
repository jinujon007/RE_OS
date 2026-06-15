"""Create gcc_hiring_snapshots table + data_source column on gcc_events (GATE-94, T-1152).

Tracks weekly Naukri public job-posting counts per tracked GCC employer at
North Bengaluru office locations (Manyata/Kirloskar/Karle/Embassy hubs).

Also adds data_source TEXT column to gcc_events to distinguish seed records
from hiring-snapshot-derived records.

Migration chain:
    0058_tenders -> 0059_gcc_hiring_snapshots
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0059_gcc_hiring_snapshots"
down_revision: Union[str, None] = "0058_tenders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gcc_hiring_snapshots",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("employer", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("posting_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'naukri_search'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "employer",
            "location",
            "snapshot_date",
            name="uq_gcc_snapshot_employer_loc_date",
        ),
    )
    op.create_index("idx_gcc_snapshots_date", "gcc_hiring_snapshots", ["snapshot_date"])
    op.create_index("idx_gcc_snapshots_employer", "gcc_hiring_snapshots", ["employer"])

    op.add_column(
        "gcc_events",
        sa.Column(
            "data_source", sa.Text(), nullable=True, server_default=sa.text("'seed'")
        ),
    )
    op.create_index("idx_gcc_events_data_source", "gcc_events", ["data_source"])


def downgrade() -> None:
    op.drop_index("idx_gcc_events_data_source", table_name="gcc_events")
    op.drop_column("gcc_events", "data_source")
    op.drop_index("idx_gcc_snapshots_employer", table_name="gcc_hiring_snapshots")
    op.drop_index("idx_gcc_snapshots_date", table_name="gcc_hiring_snapshots")
    op.drop_table("gcc_hiring_snapshots")
