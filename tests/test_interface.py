"""Tests for Sprint 65 — Interface Layer (Telegram Bot + Formatters)"""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit

from interface.telegram_bot import parse_message, dispatch_evaluation, ParsedFieldMessage
from interface.formatters import format_telegram_verdict, format_opportunity_alert, format_error


class TestParseMessage:
    def test_parses_full_message_yelahanka_jd(self):
        result = parse_message("5 acres Yelahanka JD 5200 psf")
        assert result.market == "Yelahanka"
        assert result.area_acres == 5.0
        assert result.area_sqft == 5.0 * 43560
        assert result.deal_type == "jd"
        # 4/7 tokens: market(1) + acres(1) + psf(1) + deal_type(1)
        assert result.confidence == 0.57

    def test_parses_devanahalli_purchase(self):
        result = parse_message("Devanahalli 3.5 acres purchase")
        assert result.market == "Devanahalli"
        assert result.area_acres == 3.5
        assert result.deal_type == "purchase"

    def test_parses_hebbal_sqft_and_psf(self):
        result = parse_message("Hebbal 20000 sqft 6500 psf JD")
        assert result.market == "Hebbal"
        assert abs(result.area_sqft - 20000) < 1
        assert result.ask_psf == 6500.0
        assert result.deal_type == "jd"

    def test_low_confidence_empty_text(self):
        result = parse_message("")
        assert result.confidence == 0.0

    def test_low_confidence_gibberish(self):
        result = parse_message("hello world test message")
        assert result.confidence < 0.5

    def test_handles_crore_price(self):
        result = parse_message("Yelahanka 2 acres 10cr JD")
        assert result.market == "Yelahanka"
        assert result.area_acres == 2.0
        assert result.deal_type == "jd"
        # 10cr / (2ac * 43560 sqft) = 100000000 / 87120 = ~1147.84 PSF
        assert result.ask_psf > 1100
        assert result.ask_psf < 1200

    def test_parses_compare_type(self):
        result = parse_message("5 acres Devanahalli evaluate all options")
        assert result.market == "Devanahalli"
        assert result.deal_type == "compare"

    def test_parses_kial_airport_alias(self):
        result = parse_message("KIAL area 10 acres")
        assert result.market == "Devanahalli"

    def test_parses_bellary_alias(self):
        result = parse_message("Bellary road 3 acres JD 7000")
        assert result.market == "Hebbal"


class TestDispatchEvaluation:
    def test_skips_low_confidence(self):
        msg = ParsedFieldMessage(confidence=0.4)
        result = dispatch_evaluation(msg)
        assert result["status"] == "skipped"

    def test_calls_evaluate_endpoint(self):
        msg = ParsedFieldMessage(
            market="Yelahanka", area_acres=5.0, area_sqft=5*43560,
            ask_psf=5200, deal_type="jd", confidence=0.85
        )
        with patch("httpx.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"job_id": "abc123", "status": "running"}
            result = dispatch_evaluation(msg)
            assert result["job_id"] == "abc123"
            mock_post.assert_called_once()


class TestFormatters:
    def test_format_verdict_urgent(self):
        v = format_telegram_verdict(
            market="Yelahanka", survey_no="45/2", score=0.85,
            components={"irr": 0.9, "legal": 0.8, "timing": 0.7, "distress": 0.3, "exclusivity": 0.5},
            legal_risk="CLEAR", next_action="URGENT action"
        )
        assert "URGENT" in v
        assert "Yelahanka" in v
        assert len(v) <= 1200

    def test_format_verdict_observe(self):
        v = format_telegram_verdict(
            market="Hebbal", survey_no="12/3", score=0.25,
            components={"irr": 0.2, "legal": 0.3, "timing": 0.4, "distress": 0.1, "exclusivity": 0.2},
            legal_risk="UNKNOWN", next_action="HOLD"
        )
        assert "OBSERVE" in v or "HOLD" in v
        assert len(v) <= 1200

    def test_format_opportunity_alert(self):
        alert = format_opportunity_alert("45/2", 0.85, "Yelahanka", "URGENT — initiate DD")
        assert "45/2" in alert
        assert "85%" in alert or "0.85" in alert

    def test_format_error_message(self):
        err = format_error("Something went wrong")
        assert "Error" in err
        assert "Something went wrong" in err
