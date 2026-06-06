"""Add tone_label and tone_score columns to news_articles (Sprint 35)

Adds columns for 6-label finbert-tone (yiyanghkust/finbert-tone):
- tone_label VARCHAR(30) — dominant tone: Risk/Uncertainty/Litigious/Constraining/Positive/Negative
- tone_score NUMERIC(5,4) — probability of the dominant tone (0-1)

Migration chain:
    0023_unified_psf_view -> 0024_news_tone_columns
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0024_news_tone_columns"
down_revision: Union[str, None] = "0023_unified_psf_view"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column("news_articles",
        sa.Column("tone_label", sa.VARCHAR(30), nullable=True)
    )
    op.add_column("news_articles",
        sa.Column("tone_score", sa.NUMERIC(5, 4), nullable=True)
    )
    op.create_index("idx_news_tone_label", "news_articles", ["tone_label"])


def downgrade():
    op.drop_index("idx_news_tone_label", "news_articles")
    op.drop_column("news_articles", "tone_score")
    op.drop_column("news_articles", "tone_label")
