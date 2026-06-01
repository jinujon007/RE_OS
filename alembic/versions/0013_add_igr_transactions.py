"""Add igr_transactions table for Karnataka IGR sale deed data (Sprint 39 — T-476).

IGR = Inspector General of Registration. Actual registered transaction prices.
transaction_psf is 15-25% below listing PSF — critical for accurate IRR calculations.

Revision ID: 0013_add_igr_transactions
Revises: 0012_agent_registry_hired_on_idx
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013_add_igr_transactions"
down_revision: Union[str, None] = "0012_agent_registry_hired_on_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS igr_transactions (
            id              VARCHAR(32) PRIMARY KEY,
            market          VARCHAR(100) NOT NULL,
            survey_no       VARCHAR(200),
            seller_name     TEXT,
            buyer_name      TEXT,
            consideration_amount  BIGINT,
            area_sqft       NUMERIC(12, 1),
            transaction_psf NUMERIC(10, 0)
                GENERATED ALWAYS AS (
                    ROUND(consideration_amount::NUMERIC / NULLIF(area_sqft, 0))
                ) STORED,
            registration_date  DATE,
            sro_office      VARCHAR(200),
            source          VARCHAR(50) NOT NULL DEFAULT 'fallback'
                            CHECK (source IN ('portal_playwright', 'portal_post', 'fallback')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_igr_transactions_market_date
            ON igr_transactions(market, registration_date DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_igr_transactions_survey_no
            ON igr_transactions(survey_no)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS igr_transactions")
