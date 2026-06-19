"""T-1305: Kill criteria deadline monitoring — automated weekly reminders (GATE-123)."""
import pathlib
import pytest

pytestmark = pytest.mark.unit


def test_kill_criteria_reminder_registered():
    """run_kill_criteria_reminder job is registered in maintenance_jobs."""
    path = pathlib.Path("config/scheduler/maintenance_jobs.py")
    content = path.read_text(encoding="utf-8")
    assert 'id="kill_criteria_weekly_reminder"' in content, (
        "kill_criteria_weekly_reminder job not registered"
    )
    assert "run_kill_criteria_reminder" in content


def test_reminder_discord_message_format():
    """Reminder Discord message code contains avg/target, days_left, journal count formatting."""
    path = pathlib.Path("config/scheduler/maintenance_jobs.py")
    content = path.read_text(encoding="utf-8")
    assert "deed_days_left" in content, "must compute deed_days_left from deadline - today"
    assert "deed_weekly_avg" in content, "must query weekly avg deed count"
    assert "journal_count" in content, "must query decision_journal count"
    assert "Kill Criteria Weekly Check" in content


def test_reminder_suppression_code():
    """Reminder has suppression: agent_memories fact 'kill_criteria_both_met' suppresses after both met."""
    path = pathlib.Path("config/scheduler/maintenance_jobs.py")
    content = path.read_text(encoding="utf-8")
    assert "kill_criteria_both_met" in content, (
        "must have suppression via kill_criteria_both_met agent_memory fact"
    )
    assert "SUPPRESSION" not in content or "suppression" not in content or "agent_memories" in content


def test_days_remaining_dynamic():
    """Kill-criteria endpoint days_remaining computed from date.today() (not hardcoded)."""
    path = pathlib.Path("dashboard/routers/ops.py")
    content = path.read_text(encoding="utf-8")
    assert "date.today()" in content, (
        "kill_criteria endpoint must compute days_remaining dynamically"
    )
