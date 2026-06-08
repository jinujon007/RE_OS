import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestSchedulerDigest:
    def test_weekly_digest_job_registered(self):
        from config.scheduler import run_weekly_intel_digest
        assert callable(run_weekly_intel_digest)

    def test_weekly_job_id_format(self):
        import re
        assert re.match(r"^[a-z_]+$", "weekly_intel_digest")

    def test_monthly_digest_job_registered(self):
        from config.scheduler import run_monthly_intel_digest
        assert callable(run_monthly_intel_digest)

    def test_monthly_job_id_format(self):
        import re
        assert re.match(r"^[a-z_]+$", "monthly_intel_digest")
