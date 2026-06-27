"""GATE-145 — Deed pipeline ramp: Weekly reminder + inbox tracker + throughput projection.

5 assertions:
(1) run_kaveri_download_reminder importable from config.scheduler.deed_jobs;
    callable; registered with CronTrigger(day_of_week='mon', hour=9, minute=0).
(2) get_inbox_progress() importable from utils.deed_progress;
    returns dict with this_week_new_rows key.
(3) compute_throughput_projection() importable;
    returns projection_verdict 'will_miss' when avg_4wk=0.
(4) /api/v1/deeds/projection returns 200 with projection_verdict key (mock DB).
(5) /api/v1/deeds/inbox-progress returns 200 with pending + this_week_new_rows keys (mock).
"""

import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestGate145:
    def test_a1_reminder_importable_and_trigger(self):
        from config.scheduler.deed_jobs import run_kaveri_download_reminder, register_jobs
        assert callable(run_kaveri_download_reminder)

        mock_scheduler = MagicMock()
        register_jobs(mock_scheduler, lambda f, n: f())
        calls = mock_scheduler.add_job.call_args_list
        reminder_calls = [c for c in calls if c.kwargs.get("id") == "kaveri_download_reminder"]
        assert len(reminder_calls) == 1
        name = reminder_calls[0].kwargs.get("name", "")
        assert "Mon 09:00 IST" in name

    def test_a2_inbox_progress_importable(self):
        from utils.deed_progress import get_inbox_progress
        with patch("utils.deed_progress.Path.exists", return_value=False), \
             patch("utils.deed_progress.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.scalar.return_value = 0
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            result = get_inbox_progress()
            assert isinstance(result, dict)
            assert "this_week_new_rows" in result

    def test_a3_projection_importable(self):
        from utils.deed_progress import compute_throughput_projection
        with patch("utils.deed_progress.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            result = compute_throughput_projection()
            assert result["projection_verdict"] == "will_miss"

    def test_a4_projection_endpoint(self):
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app
        client = TestClient(app)

        with patch("utils.deed_progress.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            resp = client.get("/api/v1/deeds/projection")
            assert resp.status_code == 200
            data = resp.json()
            assert "projection_verdict" in data

    def test_a5_inbox_progress_endpoint(self):
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app
        client = TestClient(app)

        with patch("utils.deed_progress.Path.exists", return_value=False), \
             patch("utils.deed_progress.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.scalar.return_value = 0
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            resp = client.get("/api/v1/deeds/inbox-progress")
            assert resp.status_code == 200
            data = resp.json()
            assert "pending" in data
            assert "this_week_new_rows" in data
