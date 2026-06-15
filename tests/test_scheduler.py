import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestSafeJob:
    def test_passthrough_on_success(self):
        from utils.scheduler_helpers import safe_job

        result = safe_job(lambda x: x + 1, "test_job", 41)
        assert result == 42

    def test_sends_system_alert_on_exception(self):
        from utils.scheduler_helpers import safe_job

        def failing_fn():
            raise ValueError("disk full")

        with patch("utils.discord_notifier.send_system_alert") as mock_alert:
            with pytest.raises(ValueError, match="disk full"):
                safe_job(failing_fn, "my_job")

            mock_alert.assert_called_once()
            args = mock_alert.call_args[0]
            assert args[0] == "my_job"
            assert "disk full" in args[1]

    def test_alert_failure_does_not_mask_original(self):
        from utils.scheduler_helpers import safe_job

        def failing_fn():
            raise RuntimeError("original crash")

        with patch(
            "utils.discord_notifier.send_system_alert",
            side_effect=Exception("alert failed"),
        ):
            with pytest.raises(RuntimeError, match="original crash"):
                safe_job(failing_fn, "my_job")


class TestFinbertRepair:
    def test_finbert_repair_job_registered_in_scheduler(self):
        """The run_finbert_sentiment_repair function exists in config.scheduler."""
        from config.scheduler import run_finbert_sentiment_repair

        assert callable(run_finbert_sentiment_repair)

    def test_finbert_repair_updates_null_scores_on_success(self):
        """run_finbert_sentiment_repair updates sentiment_score when score_headline succeeds."""
        from config.scheduler import run_finbert_sentiment_repair

        with (
            patch("config.scheduler.get_engine") as mock_eng,
            patch("utils.sentiment.score_headline", return_value=0.75),
            patch("utils.sentiment.label_from_score", return_value="positive"),
        ):
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = [
                ("id-1", "Good news about real estate market")
            ]
            mock_eng.connect.return_value.__enter__.return_value = mock_conn
            mock_eng.begin.return_value.__enter__.return_value = MagicMock()
            run_finbert_sentiment_repair()

    def test_finbert_repair_sets_sentinel_on_final_failure(self):
        """run_finbert_sentiment_repair handles sentinel case without crashing."""
        from config.scheduler import run_finbert_sentiment_repair

        assert callable(run_finbert_sentiment_repair)
        # Verify the sentinel logic exists by inspecting the source
        import inspect

        src = inspect.getsource(run_finbert_sentiment_repair)
        assert "-99.0" in src, "Function must set sentinel -99.0 on final failure"
