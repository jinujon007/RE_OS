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
    op.add_column("news_articles", sa.Column("sentiment_score", sa.Float(), nullable=True))
    op.add_column("news_articles", sa.Column("sentiment_label", sa.String(20), nullable=True))
    op.create_index("idx_news_articles_sentiment_score", "news_articles", ["sentiment_score"])


def downgrade() -> None:
    op.drop_index("idx_news_articles_sentiment_score", table_name="news_articles")
    op.drop_column("news_articles", "sentiment_label")
    op.drop_column("news_articles", "sentiment_score")
