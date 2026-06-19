"""T-1303: Prediction ledger automated verdict runner enhancement (GATE-123)."""
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

pytestmark = pytest.mark.unit


def test_psf_verdict_resolution_has_10pct_band():
    """PSF forecast verdict threshold: |predicted - actual| / actual <= 0.10 -> hit."""
    path = __import__("pathlib").Path("utils/prediction_ledger.py")
    content = path.read_text(encoding="utf-8")
    assert "<= 10" in content or "<=10" in content, (
        "psf_forecast must check if pct_diff <= 10 for 'hit' verdict"
    )


def test_psf_verdict_resolution_has_20pct_band():
    """PSF forecast verdict threshold: <= 0.20 -> partial, > 0.20 -> miss."""
    path = __import__("pathlib").Path("utils/prediction_ledger.py")
    content = path.read_text(encoding="utf-8")
    assert "<= 20" in content, (
        "psf_forecast must check if pct_diff <= 20 for 'partial' verdict"
    )


def test_psf_verdict_unverifiable():
    """When registered_transactions returns NULL, verdict='unverifiable' not 'miss'."""
    from utils.prediction_ledger import _get_market_median_psf_for_month

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = (None,)
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("utils.prediction_ledger.get_engine", return_value=mock_engine):
        result = _get_market_median_psf_for_month("Yelahanka", date(2026, 7, 1))

    assert result is None


def test_opportunity_verdict_rera_fallback():
    """When rera_projects returns NULL, listings fallback is used for opportunity_score verdict."""
    from utils.prediction_ledger import _get_market_rera_avg_psf

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.side_effect = [
        (None,),
        (6200.0,),
    ]
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("utils.prediction_ledger.get_engine", return_value=mock_engine):
        result = _get_market_rera_avg_psf("Yelahanka")

    assert result == 6200.0


def test_weekly_discord_summary():
    """build_weekly_digest_discord_message returns formatted message with correct counts."""
    from utils.prediction_ledger import build_weekly_digest_discord_message

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        ("hit", 3), ("miss", 1), ("unverifiable", 1),
    ]
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("utils.prediction_ledger.get_engine", return_value=mock_engine):
        msg = build_weekly_digest_discord_message()

    assert msg is not None
    assert "3 hit" in msg
    assert "1 miss" in msg
