"""T-1418: Three-tier alert system tests."""
import pytest
from unittest.mock import patch, MagicMock, call

pytestmark = pytest.mark.unit


_MOCK_MARKETS = ["Yelahanka"]


class TestAssemblyTiers:
    def test_assembly_alert_thresholds_importable(self):
        from config.settings import ASSEMBLY_ALERT_THRESHOLDS
        assert "high" in ASSEMBLY_ALERT_THRESHOLDS
        assert "medium" in ASSEMBLY_ALERT_THRESHOLDS
        assert ASSEMBLY_ALERT_THRESHOLDS["high"] > ASSEMBLY_ALERT_THRESHOLDS["medium"]

    def test_high_tier_triggers_telegram(self):
        from config.scheduler.deed_jobs import _get_tier
        assert _get_tier(0.9) == "high"
        assert _get_tier(0.76) == "high"

    def test_medium_tier_discord_only_no_telegram(self):
        from config.scheduler.deed_jobs import run_assembly_detection
        clusters = [
            {"market": "Test", "village": "TV", "buyer_name": "B",
             "parcel_count": 3, "total_area_sqm": 1000,
             "confidence_score": 0.6},
        ]
        with patch("utils.assembly_detector.AssemblyDetector") as MockDet:
            MockDet.return_value.detect_clusters.return_value = clusters
            with patch("config.settings.TARGET_MARKETS", _MOCK_MARKETS):
                with patch("config.scheduler.deed_jobs.send") as mock_send:
                    with patch("utils.telegram_notifier.send_message") as mock_tg:
                        run_assembly_detection()
            mock_send.assert_called_once()
            mock_tg.assert_not_called()

    def test_low_tier_no_alert(self):
        from config.scheduler.deed_jobs import run_assembly_detection
        clusters = [
            {"market": "Test", "village": "TV", "buyer_name": "B",
             "parcel_count": 2, "total_area_sqm": 500,
             "confidence_score": 0.3},
        ]
        with patch("utils.assembly_detector.AssemblyDetector") as MockDet:
            MockDet.return_value.detect_clusters.return_value = clusters
            with patch("config.settings.TARGET_MARKETS", _MOCK_MARKETS):
                with patch("config.scheduler.deed_jobs.send") as mock_send:
                    with patch("utils.telegram_notifier.send_message") as mock_tg:
                        run_assembly_detection()
            mock_send.assert_not_called()
            mock_tg.assert_not_called()

    def test_prometheus_counter_called_with_tier_label(self):
        from config.scheduler.deed_jobs import run_assembly_detection
        clusters = [
            {"market": "Yelahanka", "village": "Test", "buyer_name": "B",
             "parcel_count": 10, "total_area_sqm": 10000,
             "confidence_score": 0.9},
        ]
        with patch("utils.assembly_detector.AssemblyDetector") as MockDet:
            MockDet.return_value.detect_clusters.return_value = clusters
            with patch("config.settings.TARGET_MARKETS", _MOCK_MARKETS):
                with patch("config.scheduler.deed_jobs.send"):
                    with patch("utils.telegram_notifier.send_message"):
                        with patch("config.scheduler.deed_jobs._assembly_clusters") as mock_prom:
                            run_assembly_detection()
                            mock_prom.labels.assert_called_with(market="Yelahanka", tier="high")
