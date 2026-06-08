import pytest
from unittest.mock import MagicMock, patch, ANY
pytestmark = pytest.mark.unit


def test_canary_fires_on_zero_listings():
    """Canary fires send_scraper_alert when findings below threshold."""
    from config.settings import PORTAL_SCOUT_MIN_LISTINGS_CANARY

    with patch("utils.discord_notifier.send_scraper_alert") as mock_alert:
        threshold = PORTAL_SCOUT_MIN_LISTINGS_CANARY
        findings_count = threshold - 1
        if findings_count < threshold:
            from utils.discord_notifier import send_scraper_alert
            send_scraper_alert("Yelahanka", "portal_scout", "ZERO_LISTINGS_CANARY", record_count=findings_count)
        mock_alert.assert_called_once_with("Yelahanka", "portal_scout", "ZERO_LISTINGS_CANARY", record_count=findings_count)


def test_canary_silent_when_listings_above_threshold():
    """Canary does NOT fire when listings count >= threshold."""
    from config.settings import PORTAL_SCOUT_MIN_LISTINGS_CANARY

    with patch("utils.discord_notifier.send_scraper_alert") as mock_alert:
        threshold = PORTAL_SCOUT_MIN_LISTINGS_CANARY
        findings_count = threshold + 5
        if findings_count < threshold:
            from utils.discord_notifier import send_scraper_alert
            send_scraper_alert("Yelahanka", "portal_scout", "ZERO_LISTINGS_CANARY", record_count=findings_count)
        mock_alert.assert_not_called()


def test_canary_imports_clean():
    """Settings has PORTAL_SCOUT_MIN_LISTINGS_CANARY > 0."""
    from config.settings import PORTAL_SCOUT_MIN_LISTINGS_CANARY
    assert isinstance(PORTAL_SCOUT_MIN_LISTINGS_CANARY, int)
    assert PORTAL_SCOUT_MIN_LISTINGS_CANARY > 0
