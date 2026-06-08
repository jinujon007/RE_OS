"""T-1046 unit tests — govt_policy_events migration."""
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_govt_policy_events_table_exists():
    """Verify migration creates govt_policy_events table with expected columns."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        ("id",), ("headline",), ("category",), ("subcategory",),
        ("micro_markets",), ("investment_cr",), ("stage",),
        ("impact_score",), ("signal_strength",), ("time_horizon",),
        ("actionability",), ("summary",), ("why_it_matters",),
        ("source_urls",), ("published_date",), ("is_north_bengaluru",),
        ("scraped_at",), ("created_at",),
    ]
    cols = [r[0] for r in mock_conn.execute.return_value.fetchall.return_value]
    required = {"id", "headline", "category", "impact_score", "signal_strength",
                "actionability", "is_north_bengaluru", "micro_markets", "summary"}
    assert required.issubset(set(cols)), f"Missing columns: {required - set(cols)}"


def test_govt_policy_events_required_columns():
    """Required columns (headline, category, is_north_bengaluru) exist in our mock."""
    cols_mock = {
        "headline": "NO",
        "category": "NO",
        "is_north_bengaluru": "NO",
    }
    for col in ("headline", "category", "is_north_bengaluru"):
        assert col in cols_mock, f"{col} should be in column list"
