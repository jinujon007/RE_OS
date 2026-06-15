"""Test that the scheduler has at least 15 registered jobs with unique IDs."""

import re
from pathlib import Path


SCHEDULER_PATH = Path(__file__).parents[1] / "config" / "scheduler.py"

MIN_JOBS = 15


def _extract_job_ids() -> list[str]:
    """Parse scheduler.py and extract all job IDs from add_job() calls."""
    text = SCHEDULER_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r'scheduler\.add_job\(.*?id\s*=\s*"([^"]+)"', re.DOTALL)
    return pattern.findall(text)


def test_scheduler_has_minimum_jobs():
    """Assert scheduler registers at least 15 jobs."""
    ids = _extract_job_ids()
    assert len(ids) >= MIN_JOBS, (
        f"Expected ≥{MIN_JOBS} scheduler jobs, found {len(ids)}"
    )


def test_scheduler_no_duplicate_job_ids():
    """Assert all scheduler job IDs are unique."""
    ids = _extract_job_ids()
    duplicates = [jid for jid in ids if ids.count(jid) > 1]
    assert not duplicates, f"Duplicate scheduler job IDs found: {set(duplicates)}"
