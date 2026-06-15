"""Add extraction_confidence column to guidance_values (T-1068 GATE-78).

Tracks OCR extraction quality: 1.0 = pure English, 0.7 = mixed Kannada/English,
0.5 = fallback regex only.

Migration chain:
    0038_govt_policy_events -> 0039_gv_extraction_confidence
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039_gv_extraction_confidence"
down_revision: Union[str, None] = "0038_govt_policy_events"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade():
    op.add_column(
        "guidance_values",
        sa.Column(
            "extraction_confidence",
            sa.Float(),
            server_default=sa.text("0.7"),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_column("guidance_values", "extraction_confidence")
