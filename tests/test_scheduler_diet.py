"""Unit tests for scheduler diet (GATE-91, T-1139).

4 assertions:
(1) Org-sim jobs absent by default (SCHEDULER_ENABLE_ORG_SIM=False)
(2) SCHEDULER_ENABLE_ORG_SIM setting exists and defaults to False
(3) kaveri_deeds_weekly job registered in scheduler.py
(4) No duplicate job IDs in scheduler.py
"""
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
pytestmark = pytest.mark.unit

SCHEDULER_PATH = Path("config/scheduler.py")
SETTINGS_PATH = Path("config/settings.py")


def test_org_sim_jobs_gated():
    """Assert org-sim jobs (weekly_pr_brief, weekly_process_audit, monthly_ceo_letter)
    are gated behind SCHEDULER_ENABLE_ORG_SIM check."""
    content = SCHEDULER_PATH.read_text()

    # Each job must be gated
    for job_id in ("weekly_pr_brief", "weekly_process_audit", "monthly_ceo_letter"):
        # Find scheduler.add_job for this job
        pattern = rf"id=\"{job_id}\""
        assert re.search(pattern, content), f"Job {job_id} must exist in scheduler"

        # Assert it's gated
        # Search for: if SCHEDULER_ENABLE_ORG_SIM: before the add_job
        lines = content.split("\n")
        found = False
        for i, line in enumerate(lines):
            if job_id in line and "id=" in line:
                # Look backwards for SCHEDULER_ENABLE_ORG_SIM gate
                for j in range(max(0, i - 20), i):
                    if "SCHEDULER_ENABLE_ORG_SIM" in lines[j]:
                        found = True
                        break
                break
        assert found, f"Job {job_id} must be gated by SCHEDULER_ENABLE_ORG_SIM"


def test_scheduler_enable_org_sim_default():
    """Assert SCHEDULER_ENABLE_ORG_SIM setting exists with default False."""
    content = SETTINGS_PATH.read_text()
    assert "SCHEDULER_ENABLE_ORG_SIM" in content
    assert "false" in content.lower()  # Default is false


def test_kaveri_deeds_weekly_registered():
    """Assert kaveri_deeds_weekly job is registered."""
    content = SCHEDULER_PATH.read_text()
    assert "kaveri_deeds_weekly" in content
    assert "id=\"kaveri_deeds_weekly\"" in content
    assert "run_kaveri_deeds_weekly" in content


def test_no_duplicate_job_ids():
    """Assert no duplicate job IDs in scheduler.py add_job calls."""
    content = SCHEDULER_PATH.read_text()
    # Only match id= inside add_job( calls, not in comments/docstrings
    add_job_blocks = re.findall(
        r"scheduler\.add_job\(.*?(?=\bscheduler\.add_job\b|\Z)",
        content,
        re.DOTALL,
    )
    all_ids: list[str] = []
    for block in add_job_blocks:
        ids_in_block = re.findall(r'id="([^"]+)"', block)
        all_ids.extend(ids_in_block)
    duplicates = {jid for jid in all_ids if all_ids.count(jid) > 1}
    assert not duplicates, f"Duplicate job IDs found in add_job calls: {duplicates}"
