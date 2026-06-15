"""T-1050 unit tests — Discord govt policy formatters."""

import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_format_govt_policy_alert_high_signal():
    from utils.discord_notifier import format_govt_policy_alert

    event = {
        "headline": "Metro Phase 3 approved",
        "location_text": "Yelahanka",
        "investment_cr": 6100.0,
        "stage": "approval",
        "impact_score": 9,
        "signal_strength": "high",
        "time_horizon": "long",
        "actionability": "buy_now",
        "why_it_matters": "Will transform Yelahanka's connectivity and land values significantly over the next 5 years.",
    }
    msg = format_govt_policy_alert(event)
    assert "Metro Phase 3 approved" in msg
    assert "Impact: 9/10" in msg
    assert "BUY_NOW" in msg


def test_format_govt_policy_alert_risk_signal():
    from utils.discord_notifier import format_govt_policy_alert

    event = {
        "headline": "HAL height restrictions risk",
        "location_text": "Hebbal",
        "signal_strength": "risk",
        "impact_score": 5,
        "time_horizon": "immediate",
        "actionability": "avoid",
        "why_it_matters": "Height caps reduce FSI potential.",
    }
    msg = format_govt_policy_alert(event)
    assert "HAL height restrictions risk" in msg
    assert "AVOID" in msg


def test_format_govt_policy_weeky_digest_has_score():
    from unittest.mock import MagicMock
    from utils.discord_notifier import format_govt_policy_weekly_digest

    mock_result = MagicMock()
    mock_result.north_bengaluru_score = 0.78
    mock_result.high_opportunity_count = 5
    mock_result.risk_count = 2
    mock_result.top_infra_events = [
        {"headline": "Metro approved", "impact_score": 9, "stage": "approval"},
        {"headline": "STRR tender awarded", "impact_score": 7, "stage": "tender"},
    ]
    mock_result.top_policy_events = [
        {
            "headline": "FSI revision proposed",
            "impact_score": 8,
            "stage": "announcement",
        },
    ]
    mock_result.weekly_digest = "North Bengaluru sees strong infrastructure pipeline with metro and STRR progressing."

    msg = format_govt_policy_weekly_digest(mock_result)
    assert "North Bengaluru Score" in msg
    assert "0.78" in msg
    assert "Metro approved" in msg
    assert "FSI revision proposed" in msg


def test_send_govt_policy_alert():
    from utils.discord_notifier import send_govt_policy_alert

    with patch("utils.discord_notifier.send") as mock_send:
        event = {
            "headline": "Test alert",
            "impact_score": 8,
            "signal_strength": "high",
        }
        result = send_govt_policy_alert(event)
        assert result is True
        mock_send.assert_called_once()


def test_send_govt_policy_digest():
    from utils.discord_notifier import send_govt_policy_digest

    with patch("utils.discord_notifier.send") as mock_send:
        mock_result = MagicMock()
        mock_result.north_bengaluru_score = 0.7
        mock_result.high_opportunity_count = 3
        mock_result.risk_count = 1
        mock_result.top_infra_events = []
        mock_result.top_policy_events = []
        mock_result.weekly_digest = "Test digest"
        result = send_govt_policy_digest(mock_result)
        assert result is True
        mock_send.assert_called_once()
