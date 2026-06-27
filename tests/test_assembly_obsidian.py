"""T-1417: Assembly → Obsidian sync."""
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


_SAMPLE_CLUSTER = {
    "buyer_name": "Test Buyer",
    "village": "Test Village",
    "market": "Yelahanka",
    "confidence_score": 0.85,
    "parcel_count": 5,
    "total_area_sqm": 10000.0,
    "first_deed_date": "2026-01-15",
    "detected_at": "2026-06-25",
    "survey_numbers": ["45/2", "46/1", "47/3"],
    "days_active": 45,
    "total_consideration_inr": 25000000,
}


class TestAssemblyObsidian:
    def test_write_assembly_signal_returns_tuple(self):
        from utils.obsidian_sync import write_assembly_signal
        with patch("utils.obsidian_sync._ensure_sync_dir", return_value=True):
            with patch("utils.obsidian_sync._write_md", return_value="/tmp/test.md"):
                result = write_assembly_signal(_SAMPLE_CLUSTER)
                assert isinstance(result, tuple)
                assert len(result) == 2
                assert isinstance(result[0], str)
                assert isinstance(result[1], str)

    def test_filename_contains_buyer_and_village(self):
        from utils.obsidian_sync import write_assembly_signal
        with patch("utils.obsidian_sync._ensure_sync_dir", return_value=True):
            with patch("utils.obsidian_sync._write_md", return_value="/tmp/test.md"):
                fn, _ = write_assembly_signal(_SAMPLE_CLUSTER)
                assert "Test Buyer" in fn
                assert "Test Village" in fn

    def test_confidence_in_frontmatter(self):
        from utils.obsidian_sync import write_assembly_signal
        with patch("utils.obsidian_sync._ensure_sync_dir", return_value=True):
            with patch("utils.obsidian_sync._write_md", return_value="/tmp/test.md"):
                _, content = write_assembly_signal(_SAMPLE_CLUSTER)
                assert "confidence: 0.85" in content
                assert "type: assembly_signal" in content

    def test_next_actions_present(self):
        from utils.obsidian_sync import write_assembly_signal
        with patch("utils.obsidian_sync._ensure_sync_dir", return_value=True):
            with patch("utils.obsidian_sync._write_md", return_value="/tmp/test.md"):
                _, content = write_assembly_signal(_SAMPLE_CLUSTER)
                assert "Verify ownership at Sub-Registrar" in content
                assert "Check RERA filings" in content
                assert "Approach as JD/JV" in content

    def test_empty_cluster_does_not_raise(self):
        from utils.obsidian_sync import write_assembly_signal
        with patch("utils.obsidian_sync._ensure_sync_dir", return_value=True):
            with patch("utils.obsidian_sync._write_md", return_value="/tmp/t.md"):
                fn, content = write_assembly_signal({})
                assert isinstance(fn, str)
                assert isinstance(content, str)

    def test_called_from_run_assembly_detection(self):
        from config.scheduler.deed_jobs import run_assembly_detection
        mock_markets = ["Yelahanka"]
        with patch("utils.assembly_detector.AssemblyDetector") as MockDetector:
            mock_instance = MockDetector.return_value
            mock_instance.detect_clusters.return_value = [_SAMPLE_CLUSTER]
            with patch("config.settings.TARGET_MARKETS", mock_markets):
                with patch("config.scheduler.deed_jobs.send"):
                    with patch("utils.telegram_notifier.send_message"):
                        with patch("utils.obsidian_sync.write_assembly_signal") as mock_writer:
                            mock_writer.return_value = ("test.md", "# content")
                            run_assembly_detection()
                            mock_writer.assert_called_once()
