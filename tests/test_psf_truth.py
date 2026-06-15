"""Unit tests for PSF Truth — sale-deed filtering (T-1157)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from decimal import Decimal

import pytest

pytestmark = pytest.mark.unit

from utils.psf_truth import compute_psf_spread, SpreadResult, SpreadResponse


def test_spread_excludes_non_sale_deeds():
    """Surrender of Lease (₹1) excluded — registered count unaffected if only non-sale."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()

    # Simulate table exists
    mock_conn.execute.side_effect = [
        MagicMock(scalar=lambda: True),  # table exists
        MagicMock(fetchone=lambda: (None, 0)),  # no sale deeds in window
    ]
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("utils.psf_truth.get_engine", return_value=mock_engine):
        result = compute_psf_spread("Yelahanka")

    assert result.status == "insufficient_data"
    assert result.n_registered == 0
    # The ₹1 Surrender of Lease should not appear because deed_type != sale


def test_spread_includes_sale_deed():
    """Sale Deed with ₹50,00,000 consideration → included in median."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        MagicMock(scalar=lambda: True),
        MagicMock(fetchone=lambda: (5000.0, 12)),  # 12 sale deeds ≥ 10 threshold
        MagicMock(fetchone=lambda: (5500.0, 30)),  # 30 listings in market
    ]
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("utils.psf_truth.get_engine", return_value=mock_engine):
        result = compute_psf_spread("Yelahanka")

    assert result.status == "ok"
    assert result.n_registered == 12


def test_spread_excludes_low_consideration():
    """Sale Deed with consideration < 100000 excluded."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        MagicMock(scalar=lambda: True),
        MagicMock(
            fetchone=lambda: (None, 0)
        ),  # deed with low consideration filtered out
    ]
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("utils.psf_truth.get_engine", return_value=mock_engine):
        result = compute_psf_spread("Yelahanka")

    assert result.status == "insufficient_data"
    assert result.n_registered == 0


def test_spread_excludes_discharge_deed():
    """Discharge Deed (₹20,00,000) excluded — not in SALE_DEED_TYPES."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        MagicMock(scalar=lambda: True),
        MagicMock(fetchone=lambda: (None, 0)),  # Discharge Deed excluded
    ]
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("utils.psf_truth.get_engine", return_value=mock_engine):
        result = compute_psf_spread("Yelahanka")

    assert result.status == "insufficient_data"
    assert result.n_registered == 0


def test_spread_sale_deed_type_variants():
    """Various sale deed type strings match correctly."""
    from config.settings import SALE_DEED_TYPES

    assert "Sale" in SALE_DEED_TYPES
    assert "Sale Deed" in SALE_DEED_TYPES
    assert "Absolute Sale" in SALE_DEED_TYPES
    assert "Sale Agreement with Possession" in SALE_DEED_TYPES
    assert "Discharge Deed" not in SALE_DEED_TYPES
    assert "Surrender of Lease" not in SALE_DEED_TYPES


def test_spread_result_to_dict():
    """SpreadResult.to_dict() returns correct dict."""
    result = SpreadResult(
        registered_median_psf=5000.0,
        ask_median_psf=5500.0,
        spread_pct=10.0,
        n_registered=10,
        n_listings=20,
        window_days=180,
        status="ok",
    )
    d = result.to_dict()
    assert d["registered_median_psf"] == 5000.0
    assert d["ask_median_psf"] == 5500.0
    assert d["spread_pct"] == 10.0
    assert d["n_registered"] == 10
    assert d["status"] == "ok"


def test_spread_result_one_line_summary():
    """one_line_summary formatting."""
    result = SpreadResult(
        status="insufficient_data",
        n_registered=3,
        window_days=180,
        registered_median_psf=None,
        ask_median_psf=None,
        spread_pct=None,
        n_listings=0,
    )
    summary = result.one_line_summary()
    assert "insufficient_data" in summary.lower() or "Insufficient" in summary
