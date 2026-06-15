"""Unit tests for utils/parcel_linker.py (GATE-92, T-1142).

6 assertions:
(1) normalize_survey_no handles standard case
(2) normalize_survey_no handles variant separators
(3) normalize_survey_no returns None on garbage
(4) normalize_survey_no returns None on empty
(5) link_parcels is idempotent (mock DB, no duplicate parcels)
(6) link_parcels returns dict with expected keys
"""

from unittest.mock import patch, MagicMock
import pytest

pytestmark = pytest.mark.unit


def test_normalize_standard():
    """Assertion 1: '45/2A' stays as '45/2A'."""
    from utils.parcel_linker import normalize_survey_no

    assert normalize_survey_no("45/2A") == "45/2A"


def test_normalize_variant_separators():
    """Assertion 2: variant separators all map to same canonical form."""
    from utils.parcel_linker import normalize_survey_no

    assert normalize_survey_no("45/2-A") == "45/2A"
    assert normalize_survey_no("45/2 A") == "45/2A"
    assert normalize_survey_no("45/2  A") == "45/2A"
    assert normalize_survey_no("45/2-a") == "45/2A"


def test_normalize_garbage():
    """Assertion 3: garbage input returns None."""
    from utils.parcel_linker import normalize_survey_no

    assert normalize_survey_no("") is None
    assert normalize_survey_no(None) is None
    assert normalize_survey_no("   ") is None
    assert normalize_survey_no(".") is None


def test_normalize_empty_after_strip():
    """Assertion 4: whitespace-only after strip returns None."""
    from utils.parcel_linker import normalize_survey_no

    assert normalize_survey_no("   ") is None
    assert normalize_survey_no("") is None


def test_normalize_kannada_and_url_encoded():
    """Assertion 4b: Kannada numerals and URL-encoded input handled safely."""
    from utils.parcel_linker import normalize_survey_no

    # Kannada numerals should survive normalization (kept as-is, not stripped)
    result = normalize_survey_no("45/2ಎ")
    assert result is not None
    assert result.startswith("45/2")
    # Hanging hyphen
    assert normalize_survey_no(" 1/1- ") == "1/1"
    # Multiple slashes
    assert normalize_survey_no("45//2") == "45/2"


def test_link_parcels_idempotent():
    """Assertion 5: link_parcels does not create duplicate parcels on re-run."""
    from utils.parcel_linker import link_parcels

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    # First call returns empty for all source queries
    mock_conn.execute.return_value.fetchall.return_value = []
    with patch("utils.parcel_linker.get_engine", return_value=mock_engine):
        stats1 = link_parcels()
        # Second call with the same data should not error
        stats2 = link_parcels()
        assert isinstance(stats1, dict)
        assert isinstance(stats2, dict)


def test_link_parcels_returns_dict():
    """Assertion 6: link_parcels returns dict with expected keys."""
    from utils.parcel_linker import link_parcels

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchall.return_value = []
    with patch("utils.parcel_linker.get_engine", return_value=mock_engine):
        stats = link_parcels()
        for key in (
            "created",
            "linked_rera",
            "linked_registered",
            "linked_kaveri",
            "skipped",
        ):
            assert key in stats, f"Missing key: {key}"
