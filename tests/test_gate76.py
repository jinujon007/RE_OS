"""GATE-76 — Weekly + Monthly Intelligence Digest
Six assertions:
1. WeeklyIntelDigest().build('Yelahanka') returns WeeklyDigestResult without raising
2. MonthlyIntelDigest().build('Yelahanka') returns MonthlyDigestResult without raising
3. format_weekly_digest(result) returns str <= 400 chars
4. GET /api/digest/weekly?market=Yelahanka returns 200 + JSON with psf_delta_pct key
5. GET /api/digest/monthly?market=Yelahanka returns 200 + JSON with psf_mom_pct key
6. weekly_intel_digest job function is callable
"""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_db():
    with (
        patch("utils.weekly_digest.get_engine") as w_eng,
        patch("utils.monthly_digest.get_engine") as m_eng,
    ):
        mock_conn = MagicMock()
        w_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        m_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = None
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_conn.execute.return_value.fetchone.return_value = None
        yield


class TestGate76:
    def test_weekly_digest_build_returns_result_without_raising(self, mock_db):
        from utils.weekly_digest import WeeklyIntelDigest, WeeklyDigestResult

        digest = WeeklyIntelDigest()
        result = digest.build("Yelahanka")
        assert isinstance(result, WeeklyDigestResult)
        assert all(
            hasattr(result, f)
            for f in ("market", "psf_delta_pct", "psf_direction", "new_rera_count")
        )

    def test_monthly_digest_build_returns_result_without_raising(self, mock_db):
        from utils.monthly_digest import MonthlyIntelDigest, MonthlyDigestResult

        with patch.object(MonthlyIntelDigest, "_generate_synthesis", return_value=""):
            digest = MonthlyIntelDigest()
            result = digest.build("Yelahanka")
            assert isinstance(result, MonthlyDigestResult)
            assert all(
                hasattr(result, f)
                for f in ("market", "psf_mom_pct", "absorption_trend")
            )

    def test_format_weekly_digest_under_400_chars(self):
        from utils.weekly_digest import WeeklyDigestResult
        from utils.discord_notifier import format_weekly_digest

        result = WeeklyDigestResult(
            market="Yelahanka",
            psf_delta_pct=5.0,
            psf_direction="up",
            new_rera_count=3,
            competitor_launches=[
                {
                    "developer_name": "Brigade",
                    "project_name": "Test",
                    "grade": "A",
                    "units": 100,
                }
            ],
            distressed_developers=[
                {
                    "developer_name": "DevX",
                    "market": "Yelahanka",
                    "distress_score": 0.75,
                }
            ],
            top_opportunity={
                "survey_no": "45/2",
                "market": "Yelahanka",
                "composite_score": 0.85,
                "timing_score": 0.72,
            },
        )
        msg = format_weekly_digest(result)
        assert isinstance(msg, str)
        assert len(msg) <= 400
        assert "Yelahanka" in msg

    def test_digest_weekly_api_returns_json(self):
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app
        from utils.weekly_digest import WeeklyDigestResult

        client = TestClient(app)
        with patch("utils.weekly_digest.WeeklyIntelDigest") as MockDigest:
            mock_instance = MagicMock()
            mock_instance.build.return_value = WeeklyDigestResult(
                market="Yelahanka", psf_delta_pct=5.0, psf_direction="up"
            )
            MockDigest.return_value = mock_instance
            resp = client.get("/api/digest/weekly?market=Yelahanka")
            assert resp.status_code == 200
            data = resp.json()
            assert "psf_delta_pct" in data

    def test_digest_monthly_api_returns_json(self):
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app
        from utils.monthly_digest import MonthlyDigestResult

        client = TestClient(app)
        with patch("utils.monthly_digest.MonthlyIntelDigest") as MockDigest:
            mock_instance = MagicMock()
            mock_instance.build.return_value = MonthlyDigestResult(
                market="Yelahanka", psf_mom_pct=3.5
            )
            MockDigest.return_value = mock_instance
            resp = client.get("/api/digest/monthly?market=Yelahanka")
            assert resp.status_code == 200
            data = resp.json()
            assert "psf_mom_pct" in data

    def test_weekly_digest_job_registered(self):
        from config.scheduler import run_weekly_intel_digest

        assert callable(run_weekly_intel_digest)
        assert run_weekly_intel_digest.__doc__ is not None
        assert "dedup" in (run_weekly_intel_digest.__doc__ or "").lower()
