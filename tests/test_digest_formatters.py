import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


@pytest.fixture
def weekly_result():
    from utils.weekly_digest import WeeklyDigestResult
    return WeeklyDigestResult(
        market="Yelahanka",
        psf_delta_pct=5.25,
        psf_direction="up",
        new_rera_count=3,
        competitor_launches=[
            {"developer_name": "Brigade", "project_name": "Brigade Palm", "grade": "A", "units": 120},
        ],
        distressed_developers=[
            {"developer_name": "Dev X", "market": "Yelahanka", "distress_score": 0.75},
        ],
        top_opportunity={"survey_no": "45/2", "market": "Yelahanka", "composite_score": 0.85, "timing_score": 0.72},
    )


@pytest.fixture
def monthly_result():
    from utils.monthly_digest import MonthlyDigestResult
    return MonthlyDigestResult(
        market="Yelahanka",
        psf_mom_pct=3.5,
        absorption_trend="accelerating",
        pipeline_supply_added=200,
        gcc_events_count=5,
        govt_policy_events_count=3,
        top_opportunities=[
            {"survey_no": "45/2", "market": "Yelahanka", "composite_score": 0.85, "timing_score": 0.72},
        ],
        llm_synthesis="Yelahanka showing strong absorption with PSF up 3.5%.",
    )


class TestDigestFormatters:
    def test_format_weekly_digest_under_400_chars(self, weekly_result):
        from utils.discord_notifier import format_weekly_digest
        msg = format_weekly_digest(weekly_result)
        assert isinstance(msg, str)
        assert len(msg) <= 400

    def test_format_monthly_digest_under_800_chars(self, monthly_result):
        from utils.discord_notifier import format_monthly_digest
        msg = format_monthly_digest([monthly_result])
        assert isinstance(msg, str)
        assert len(msg) <= 800

    def test_send_weekly_calls_webhook(self, weekly_result):
        from utils.discord_notifier import send_weekly_digest
        with patch("utils.discord_notifier.send") as mock_send:
            mock_send.return_value = True
            results = [weekly_result]
            with patch("utils.discord_notifier._get_webhook_url", return_value="https://discord.com/api/webhooks/test"):
                send_weekly_digest(results)
                assert mock_send.call_count == 1

    def test_send_monthly_calls_webhook(self, monthly_result):
        from utils.discord_notifier import send_monthly_digest
        with patch("utils.discord_notifier.send") as mock_send:
            mock_send.return_value = True
            results = [monthly_result]
            with patch("utils.discord_notifier._get_webhook_url", return_value="https://discord.com/api/webhooks/test"):
                send_monthly_digest(results)
                assert mock_send.call_count == 1
