"""T-954: Locality alias validation tests."""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


def _make_mock_row(listing_id, source_url, property_type, locality, project_name):
    row = MagicMock()
    row.__getitem__.side_effect = lambda idx: [listing_id, source_url, property_type, locality, project_name][idx]
    row.__iter__.return_value = iter([listing_id, source_url, property_type, locality, project_name])
    return row


def test_locality_validation_catches_alien_listing():
    from utils.data_quality import DataQualityMonitor
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_mock_row("uuid-1", "https://example.com/some-property", "Apartment", "Whitefield", "Prestige SomeProject"),
        ]
        result = DataQualityMonitor.locality_validation_score("Yelahanka")
        assert result["suspect"] == 1
        assert result["score"] == 0.0


def test_locality_validation_clean_data_scores_1():
    from utils.data_quality import DataQualityMonitor
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_mock_row("uuid-1", "https://example.com/yelahanka-property", "Apartment", "Yelahanka", "Sobha Yelahanka"),
            _make_mock_row("uuid-2", "https://example.com/vidyaranyapura", "Villa", "Vidyaranyapura", "Prestige Vidyaranyapura"),
        ]
        result = DataQualityMonitor.locality_validation_score("Yelahanka")
        assert result["valid"] == 2
        assert result["suspect"] == 0
        assert result["score"] == 1.0


def test_locality_validation_below_threshold_alerts():
    from utils.data_quality import DataQualityMonitor
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_mock_row("uuid-1", "https://example.com/yelahanka-property", "Apartment", "Yelahanka", "Sobha Yelahanka"),
            _make_mock_row("uuid-2", "https://example.com/whitefield-property", "Villa", "Whitefield", "Prestige Whitefield"),
        ]
        result = DataQualityMonitor.locality_validation_score("Yelahanka", max_suspect_pct=20.0)
        assert result["action"] == "WARN"


def test_locality_aliases_structure():
    """KNOWN_ALIEN_LOCALITIES has entries for all primary markets and is well-formed."""
    from config.locality_aliases import KNOWN_ALIEN_LOCALITIES
    assert "yelahanka" in KNOWN_ALIEN_LOCALITIES
    assert "devanahalli" in KNOWN_ALIEN_LOCALITIES
    assert "hebbal" in KNOWN_ALIEN_LOCALITIES
    for market, aliens in KNOWN_ALIEN_LOCALITIES.items():
        assert isinstance(aliens, list)
        assert len(aliens) >= 3
        for a in aliens:
            assert isinstance(a, str)
            assert len(a) > 0
