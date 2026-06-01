import pytest
from unittest.mock import patch
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

        with patch("utils.discord_notifier.send_system_alert", side_effect=Exception("alert failed")):
            with pytest.raises(RuntimeError, match="original crash"):
                safe_job(failing_fn, "my_job")
