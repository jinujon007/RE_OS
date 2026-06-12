"""Unit tests for PSF Truth — registered-vs-ask spread (GATE-91, T-1138).

4 assertions:
(1) compute_psf_spread returns SpreadResult with all fields
(2) Insufficient data (n_registered < 10) → status='insufficient_data'
(3) Spread endpoint returns 200 with spread_pct or insufficient_data
(4) One-line summary formats correctly for Board Room injection
"""
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
pytestmark = pytest.mark.unit

from utils.psf_truth import compute_psf_spread, SpreadResult


def _mock_conn(reg_rows, ask_rows, table_exists=True):
    """Create a mock connection with execute calls matching psf_truth query order:
    1. information_schema table existence check (.scalar())
    2. registered_transactions median query (.fetchone())
    3. listings median query (.fetchone())
    """
    conn = MagicMock()
    conn.__enter__.return_value = conn

    results = []

    # First call: table_exists check via .scalar()
    exists_mock = MagicMock()
    exists_mock.scalar.return_value = table_exists
    results.append(exists_mock)

    if table_exists:
        # Second call: reg median query
        reg_mock = MagicMock()
        reg_mock.fetchone.return_value = reg_rows
        results.append(reg_mock)

        # Third call: ask median query
        ask_mock = MagicMock()
        ask_mock.fetchone.return_value = ask_rows
        results.append(ask_mock)
    else:
        # Return early from insufficient_data
        pass

    it = iter(results)
    conn.execute.side_effect = lambda *a, **kw: next(it)

    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    return engine


def test_compute_psf_spread_sufficient():
    """Spread computed with sufficient registered data."""
    engine = _mock_conn(
        reg_rows=(6500.0, 15),  # median 6500, 15 records
        ask_rows=(7800.0, 30),  # median 7800, 30 listings
    )
    with patch("utils.psf_truth.get_engine", return_value=engine):
        result = compute_psf_spread("Yelahanka", window_days=180)

    assert result.status == "ok"
    assert result.registered_median_psf == 6500.0
    assert result.ask_median_psf == 7800.0
    assert result.n_registered == 15
    assert result.n_listings == 30
    assert result.spread_pct is not None
    # (7800 - 6500) / 6500 * 100 = 20%
    assert abs(result.spread_pct - 20.0) < 0.1
    assert result.window_days == 180


def test_insufficient_data():
    """Fewer than 10 registered transactions → status='insufficient_data'."""
    engine = _mock_conn(
        reg_rows=(None, 3),  # only 3 records
        ask_rows=None,        # should not be reached
    )
    with patch("utils.psf_truth.get_engine", return_value=engine):
        result = compute_psf_spread("Yelahanka")

    assert result.status == "insufficient_data"
    assert result.n_registered == 3
    assert result.registered_median_psf is None
    assert result.spread_pct is None


def test_spread_response_pydantic_shape():
    """SpreadResponse Pydantic model validates all fields."""
    from utils.psf_truth import SpreadResponse
    data = {
        "registered_median_psf": 6500.0,
        "ask_median_psf": 7800.0,
        "spread_pct": 20.0,
        "n_registered": 15,
        "n_listings": 30,
        "window_days": 180,
        "status": "ok",
    }
    model = SpreadResponse(**data)
    assert model.n_registered == 15
    assert model.status == "ok"


def test_spread_model_rejects_extra_fields():
    """SpreadResponse should reject unknown fields (strict Pydantic)."""
    from utils.psf_truth import SpreadResponse
    data = {
        "registered_median_psf": 6500.0,
        "ask_median_psf": 7800.0,
        "n_registered": 15,
        "n_listings": 30,
        "window_days": 180,
        "status": "ok",
        "extra_field": "should_fail",
    }
    with pytest.raises(Exception):
        SpreadResponse(**data)


def test_one_line_summary():
    """One-line summary formats correctly."""
    result = SpreadResult(
        registered_median_psf=6500.0,
        ask_median_psf=7800.0,
        spread_pct=20.0,
        n_registered=15,
        n_listings=30,
        window_days=180,
        status="ok",
    )
    summary = result.one_line_summary()
    assert "REGISTERED-vs-ASK SPREAD" in summary
    assert "₹6,500" in summary
    assert "₹7,800" in summary
    assert "20.0% wider" in summary


def test_one_line_summary_insufficient():
    """One-line summary shows insufficient data message."""
    result = SpreadResult(
        registered_median_psf=None,
        ask_median_psf=None,
        spread_pct=None,
        n_registered=3,
        n_listings=0,
        window_days=180,
        status="insufficient_data",
    )
    summary = result.one_line_summary()
    assert "Insufficient registered deed data" in summary
    assert "3 records" in summary
