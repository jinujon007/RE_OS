"""Add sentiment_score + sentiment_label to news_articles (Phase 8.5).

Revision ID: 0010_add_sentiment_columns
Revises: 0009_add_alerts_table
Create Date: 2026-05-30
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0010_add_sentiment_columns"
down_revision: Union[str, None] = "0009_add_alerts_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use raw SQL with IF NOT EXISTS so this migration is idempotent when the
    # columns were already created by schema.sql (fresh Docker deployment path).
    op.execute(
        "ALTER TABLE news_articles "
        "ADD COLUMN IF NOT EXISTS sentiment_score FLOAT"
    )
    op.execute(
        "ALTER TABLE news_articles "
        "ADD COLUMN IF NOT EXISTS sentiment_label VARCHAR(20)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_news_articles_sentiment_score "
        "ON news_articles(sentiment_score)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_news_articles_sentiment_score")
    op.execute("ALTER TABLE news_articles DROP COLUMN IF EXISTS sentiment_label")
    op.execute("ALTER TABLE news_articles DROP COLUMN IF EXISTS sentiment_score")
