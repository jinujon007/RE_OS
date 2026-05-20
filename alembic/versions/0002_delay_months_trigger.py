"""Convert delay_months from GENERATED ALWAYS AS to trigger-computed column.

GENERATED ALWAYS AS columns can fail on DB reinit with the PostGIS Docker image
on certain PostgreSQL minor versions. A BEFORE INSERT OR UPDATE trigger is
equivalent, portable, and allows back-filling existing rows.

Revision ID: 0002_delay_months_trigger
Revises: 0001_baseline
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_delay_months_trigger"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE rera_projects DROP COLUMN IF EXISTS delay_months")
    op.execute("ALTER TABLE rera_projects ADD COLUMN IF NOT EXISTS delay_months INTEGER DEFAULT 0")
    op.execute("""
        UPDATE rera_projects
        SET delay_months = (actual_completion_date - possession_date) / 30
        WHERE actual_completion_date IS NOT NULL
          AND possession_date IS NOT NULL
          AND actual_completion_date > possession_date
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION fn_compute_delay_months()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.actual_completion_date IS NOT NULL AND NEW.possession_date IS NOT NULL
               AND NEW.actual_completion_date > NEW.possession_date THEN
                NEW.delay_months := (NEW.actual_completion_date - NEW.possession_date) / 30;
            ELSE
                NEW.delay_months := 0;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_compute_delay_months ON rera_projects")
    op.execute("""
        CREATE TRIGGER trg_compute_delay_months
        BEFORE INSERT OR UPDATE OF actual_completion_date, possession_date
        ON rera_projects
        FOR EACH ROW EXECUTE FUNCTION fn_compute_delay_months()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_compute_delay_months ON rera_projects")
    op.execute("DROP FUNCTION IF EXISTS fn_compute_delay_months()")
    op.execute("ALTER TABLE rera_projects DROP COLUMN IF EXISTS delay_months")
    op.execute("""
        ALTER TABLE rera_projects ADD COLUMN IF NOT EXISTS delay_months INTEGER
            GENERATED ALWAYS AS (
                CASE WHEN actual_completion_date IS NOT NULL
                          AND possession_date IS NOT NULL
                          AND actual_completion_date > possession_date
                     THEN (actual_completion_date - possession_date) / 30
                     ELSE 0 END
            ) STORED
    """)
