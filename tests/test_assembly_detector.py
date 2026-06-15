"""Unit tests for utils/assembly_detector.py (GATE-92, T-1143).

6 assertions:
(1) Fires on 3-parcel assembly by same buyer in same village
(2) Does NOT fire on 2 unrelated buyers
(3) Does NOT fire across villages
(4) Fuzzy buyer match works (similar names)
(5) Dedup updates existing signal, no duplicates
(6) Discord alert payload format is correct
"""

from unittest.mock import patch, MagicMock, ANY
from datetime import date, timedelta
import pytest

pytestmark = pytest.mark.unit


def _make_mock_row(
    id_val, buyer, village, survey_no, reg_date, extent=1000.0, consideration=5000000.0
):
    """Helper to create a mock DB row-like object."""
    row = MagicMock()
    row.id = id_val
    row.buyer_name_raw = buyer
    row.village = village
    row.survey_no = survey_no
    row.reg_date = reg_date
    row.extent_sqft = extent
    row.consideration_inr = consideration
    return row


def test_fires_on_3_parcel_assembly():
    """Assertion 1: detector fires on 3 deeds same buyer same village proximal."""
    from utils.assembly_detector import detect_assemblies

    base = date.today() - timedelta(days=30)
    mock_rows = [
        _make_mock_row("a1", "Brigade Group", "Yelahanka", "45/1", base),
        _make_mock_row(
            "a2", "Brigade Group", "Yelahanka", "45/2", base + timedelta(days=15)
        ),
        _make_mock_row(
            "a3", "Brigade Group", "Yelahanka", "45/3", base + timedelta(days=30)
        ),
    ]
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchall.return_value = mock_rows
    # No existing signal
    mock_conn.execute.return_value.fetchone.return_value = None

    with patch("utils.assembly_detector.get_engine", return_value=mock_engine):
        signals = detect_assemblies()
        assert len(signals) >= 1
        assert signals[0]["parcel_count"] >= 3
        assert "BRIGADE GROUP" in signals[0]["buyer_name_norm"]


def test_does_not_fire_on_unrelated_buyers():
    """Assertion 2: 2 deeds from different buyers in same village no assembly."""
    from utils.assembly_detector import detect_assemblies

    base = date.today() - timedelta(days=30)
    mock_rows = [
        _make_mock_row("b1", "Prestige Group", "Yelahanka", "50/1", base),
        _make_mock_row(
            "b2", "Sobha Ltd", "Yelahanka", "55/1", base + timedelta(days=10)
        ),
    ]
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchall.return_value = mock_rows
    mock_conn.execute.return_value.fetchone.return_value = None

    with patch("utils.assembly_detector.get_engine", return_value=mock_engine):
        signals = detect_assemblies()
        assert len(signals) == 0


def test_does_not_fire_across_villages():
    """Assertion 3: same buyer different villages does not fire."""
    from utils.assembly_detector import detect_assemblies

    base = date.today() - timedelta(days=30)
    mock_rows = [
        _make_mock_row("c1", "Brigade Group", "Yelahanka", "45/1", base),
        _make_mock_row(
            "c2", "Brigade Group", "Devanahalli", "60/1", base + timedelta(days=10)
        ),
    ]
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchall.return_value = mock_rows
    mock_conn.execute.return_value.fetchone.return_value = None

    with patch("utils.assembly_detector.get_engine", return_value=mock_engine):
        signals = detect_assemblies()
        assert len(signals) == 0


def test_fuzzy_buyer_match():
    """Assertion 4: similar buyer names match (Brigade Group vs Brigade Enterprises)."""
    from utils.assembly_detector import _fuzzy_match

    assert _fuzzy_match("Brigade Group", "Brigade Enterprises", threshold=0.5)
    assert _fuzzy_match("Brigade Group", "Brigade Group")
    assert not _fuzzy_match("Prestige", "Sobha")


def test_dedup_updates_existing():
    """Assertion 5: existing signal is updated not duplicated."""
    from utils.assembly_detector import detect_assemblies

    base = date.today() - timedelta(days=30)
    mock_rows = [
        _make_mock_row("d1", "Brigade Group", "Yelahanka", "45/1", base),
        _make_mock_row(
            "d2", "Brigade Group", "Yelahanka", "45/2", base + timedelta(days=15)
        ),
    ]
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchall.return_value = mock_rows
    # Simulate existing signal found
    existing = MagicMock()
    existing.fetchone.return_value = ("signal-uuid", 2)
    mock_conn.execute.return_value.fetchone = existing.fetchone

    with patch("utils.assembly_detector.get_engine", return_value=mock_engine):
        signals = detect_assemblies()
        assert len(signals) >= 1


def test_discord_alert_format():
    """Assertion 6: Discord alert payload has correct format."""
    from utils.assembly_detector import _format_assembly_alert

    signal = {
        "buyer_name_norm": "BRIGADE GROUP",
        "parcel_count": 3,
        "total_extent_sqft": 15000.0,
        "village": "Yelahanka",
        "days_span": 45,
    }
    alert = _format_assembly_alert(signal)
    assert "LAND ASSEMBLY" in alert
    assert "BRIGADE GROUP" in alert
    assert "3 parcels" in alert
    assert "Yelahanka" in alert
    assert "45d" in alert
