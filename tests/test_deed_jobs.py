"""T-1411 — Kaveri download reminder job unit tests."""

import pytest
from unittest.mock import patch, MagicMock
from contextlib import ExitStack

pytestmark = pytest.mark.unit


_SAMPLE_MAP = {
    "Yelahanka": {
        "kaveri_sro_district": "Gandhinagar",
        "kaveri_taluk": "Yelahanka",
        "kaveri_hobli": "Yalahanka Hobli",
        "villages": [
            {"name": "Amanikere", "code": 26138, "is_urban": False},
        ],
    },
}


@pytest.fixture
def mock_deps():
    """Standard mocks for run_kaveri_download_reminder test dependencies.

    Patches at the module level where deed_jobs has already imported them.
    """
    with ExitStack() as stack:
        mock_exists = stack.enter_context(
            patch("config.scheduler.deed_jobs.Path.exists")
        )
        mock_json_loads = stack.enter_context(
            patch("config.scheduler.deed_jobs.json.loads")
        )
        mock_eng = stack.enter_context(
            patch("config.scheduler.deed_jobs.get_engine")
        )
        mock_send = stack.enter_context(
            patch("config.scheduler.deed_jobs.send", new=MagicMock())
        )
        mock_tg = stack.enter_context(
            patch("utils.telegram_notifier.send_message", new=MagicMock())
        )
        mock_exists.return_value = True
        mock_json_loads.return_value = _SAMPLE_MAP
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = ("2026-06-01",)
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        yield {
            "exists": mock_exists,
            "json_loads": mock_json_loads,
            "engine": mock_eng,
            "discord": mock_send,
            "telegram": mock_tg,
        }


class TestRunKaveriDownloadReminder:
    def test_job_registered_with_correct_trigger(self):
        from config.scheduler.deed_jobs import register_jobs

        mock_scheduler = MagicMock()
        register_jobs(mock_scheduler, lambda f, n: f())
        job_calls = mock_scheduler.add_job.call_args_list
        reminder_calls = [
            c for c in job_calls
            if c.kwargs.get("id") == "kaveri_download_reminder"
        ]
        assert len(reminder_calls) == 1
        name = reminder_calls[0].kwargs.get("name", "")
        trigger_args = reminder_calls[0].args if reminder_calls[0].args else []
        trigger_kw = reminder_calls[0].kwargs.get("trigger") or {}
        job_str = str(reminder_calls[0])
        assert "kaveri_download_reminder" in str(reminder_calls[0])
        assert "Mon 09:00 IST" in name

    def test_reminder_contains_village_name(self, mock_deps):
        from config.scheduler.deed_jobs import run_kaveri_download_reminder

        run_kaveri_download_reminder()

        discord_call = mock_deps["discord"].call_args
        msg = discord_call[0][2] if len(discord_call[0]) > 2 else ""
        assert "Amanikere" in str(msg)

    def test_reminder_contains_sro(self, mock_deps):
        from config.scheduler.deed_jobs import run_kaveri_download_reminder

        run_kaveri_download_reminder()

        discord_call = mock_deps["discord"].call_args
        msg = discord_call[0][2] if len(discord_call[0]) > 2 else ""
        assert "Gandhinagar" in str(msg)

    def test_reminder_contains_last_deed_date(self, mock_deps):
        from config.scheduler.deed_jobs import run_kaveri_download_reminder

        run_kaveri_download_reminder()

        discord_call = mock_deps["discord"].call_args
        msg = str(discord_call[0][2] if len(discord_call[0]) > 2 else "")
        assert "2026-06-01" in msg

    def test_falls_back_to_generic_on_missing_map(self, mock_deps):
        from config.scheduler.deed_jobs import run_kaveri_download_reminder

        mock_deps["exists"].return_value = False

        with patch(
            "config.scheduler.deed_jobs._send_generic_reminder", new=MagicMock()
        ) as mock_generic:
            run_kaveri_download_reminder()
            assert mock_generic.called

    def test_both_discord_and_telegram_called(self, mock_deps):
        from config.scheduler.deed_jobs import run_kaveri_download_reminder

        run_kaveri_download_reminder()

        assert mock_deps["discord"].called
        assert mock_deps["telegram"].called

    def test_falls_back_on_json_parse_error(self, mock_deps):
        from config.scheduler.deed_jobs import run_kaveri_download_reminder

        mock_deps["json_loads"].side_effect = ValueError("bad json")

        with patch(
            "config.scheduler.deed_jobs._send_generic_reminder", new=MagicMock()
        ) as mock_generic:
            run_kaveri_download_reminder()
            assert mock_generic.called

    def test_no_priorities_triggers_generic(self, mock_deps):
        from config.scheduler.deed_jobs import run_kaveri_download_reminder

        mock_deps["json_loads"].return_value = {
            "EmptyMarket": {
                "kaveri_sro_district": "Unknown",
                "villages": [],
            }
        }
        mock_deps["discord"].reset_mock()

        with patch(
            "config.scheduler.deed_jobs._send_generic_reminder", new=MagicMock()
        ) as mock_generic:
            run_kaveri_download_reminder()
            assert mock_generic.called

    def test_db_exception_logs_warning(self, mock_deps):
        from config.scheduler.deed_jobs import run_kaveri_download_reminder

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("connection lost")
        mock_deps["engine"].return_value.connect.return_value.__enter__.return_value = mock_conn

        with patch("config.scheduler.deed_jobs.logger.warning") as mock_log:
            run_kaveri_download_reminder()
            warning_messages = [str(c[0][0]) for c in mock_log.call_args_list if c[0]]
            assert any("Last deed query failed" in m for m in warning_messages)

    def test_generic_fallback_logs_warning_not_silent(self):
        from config.scheduler.deed_jobs import _send_generic_reminder

        with patch("config.scheduler.deed_jobs.send", side_effect=Exception("Discord down")), \
             patch("utils.telegram_notifier.send_message", side_effect=Exception("TG down")), \
             patch("config.scheduler.deed_jobs.logger.warning") as mock_log:
            _send_generic_reminder()
            assert mock_log.called
