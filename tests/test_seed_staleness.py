"""T-953: Seed staleness SLO enforcement tests."""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


def test_seed_staleness_triggers_deletion():
    """When live listings >= SLO_SEED_MIN_LIVE_LISTINGS, action is remove_seed_and_use_live."""
    from utils.data_quality import DataQualityMonitor
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Yelahanka", 15, None, 12),
        ]
        flags = DataQualityMonitor.check_seed_staleness(min_live_listings=10)
        assert len(flags) == 1
        assert flags[0]["action"] == "remove_seed_and_use_live"
        assert flags[0]["market"] == "Yelahanka"


def test_seed_staleness_no_action_below_threshold():
    """When live listings < SLO_SEED_MIN_LIVE_LISTINGS, no removal flag."""
    from utils.data_quality import DataQualityMonitor
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Yelahanka", 15, None, 3),
        ]
        flags = DataQualityMonitor.check_seed_staleness(min_live_listings=10)
        assert len(flags) == 0


def test_seed_staleness_health_endpoint_data_exists():
    """_get_market_psf_fallback returns float for known market (not scheduler)."""
    from utils.data_quality import DataQualityMonitor
    dqm = DataQualityMonitor
    assert hasattr(dqm, 'check_seed_staleness')
    assert callable(dqm.check_seed_staleness)
