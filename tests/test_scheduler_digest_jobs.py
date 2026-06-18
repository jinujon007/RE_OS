"""T-1167: config/scheduler/digest_jobs.py unit tests."""
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_digest_jobs_module_importable():
    from config.scheduler.digest_jobs import (
        run_weekly_digest,
        run_weekly_intel_digest,
        run_monthly_intel_digest,
        monthly_ceo_letter,
        run_compliance_check,
    )
    assert callable(run_weekly_digest)
    assert callable(run_weekly_intel_digest)
    assert callable(run_monthly_intel_digest)
    assert callable(monthly_ceo_letter)
    assert callable(run_compliance_check)


def test_register_jobs_digest_accepts_mock_scheduler():
    from config.scheduler.digest_jobs import register_jobs
    mock_scheduler = MagicMock()
    def safe_job(fn, name): return fn
    with patch("config.settings.SCHEDULER_ENABLE_ORG_SIM", True):
        register_jobs(mock_scheduler, safe_job)
    assert mock_scheduler.add_job.call_count >= 8


# ── T-1278: Deed throughput digest ─────────────────────────────────────────


def test_deed_throughput_digest_registered():
    from config.scheduler.digest_jobs import register_jobs
    mock_scheduler = MagicMock()
    def safe_job(fn, name): return fn
    register_jobs(mock_scheduler, safe_job)
    job_ids = [call.kwargs["id"] for call in mock_scheduler.add_job.call_args_list if "id" in call.kwargs]
    assert "deed_throughput_digest" in job_ids, f"deed_throughput_digest not in {job_ids}"


def test_deed_throughput_digest_warns_below_target():
    from config.scheduler.digest_jobs import run_deed_throughput_digest
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    week_row = (2,)
    cum_row = (5, 2.5)

    mock_conn.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=week_row)),
        MagicMock(fetchone=MagicMock(return_value=cum_row)),
    ]

    captured = {"called": False, "msg": ""}

    def _capture(channel, title, msg):
        captured["called"] = True
        captured["msg"] = msg

    with patch("utils.db.get_engine", return_value=mock_engine), \
         patch("config.scheduler.digest_jobs._digest_already_sent", return_value=False), \
         patch("config.scheduler.digest_jobs._mark_digest_sent"), \
         patch("utils.discord_notifier.send", side_effect=_capture):
        run_deed_throughput_digest()
        assert captured["called"], "Discord send was never called"
        assert "BELOW TARGET" in captured["msg"]
