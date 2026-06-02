import pytest
from unittest.mock import patch, MagicMock
import json
pytestmark = pytest.mark.unit

from utils.sentiment import score_headline_tone, aggregate_market_sentiment_tone, score_headline


class TestScoreHeadlineTone:
    def test_returns_none_when_no_api_key(self):
        result = score_headline_tone("Real estate prices surge in Bengaluru")
        assert result is None

    def test_bullish_tone(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            [{"label": "bullish", "score": 0.92},
             {"label": "neutral", "score": 0.05},
             {"label": "bearish", "score": 0.03}]
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = score_headline_tone("Prestige launches 500-unit project in Yelahanka", api_key="test_key")
            assert result is not None
            assert result["bullish"] > 0.9
            assert result["bearish"] < 0.1
            assert result["neutral"] < 0.1

    def test_bearish_tone(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            [{"label": "bearish", "score": 0.88},
             {"label": "neutral", "score": 0.10},
             {"label": "bullish", "score": 0.02}]
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = score_headline_tone("Developer delays possession of project by 18 months", api_key="test_key")
            assert result is not None
            assert result["bearish"] > 0.8
            assert result["bullish"] < 0.1
            assert result["neutral"] < 0.2

    def test_neutral_tone(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            [{"label": "neutral", "score": 0.95},
             {"label": "bullish", "score": 0.03},
             {"label": "bearish", "score": 0.02}]
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = score_headline_tone("RERA Karnataka registers 317 new projects in FY 2026", api_key="test_key")
            assert result is not None
            assert result["neutral"] > 0.9
            assert result["bullish"] < 0.1
            assert result["bearish"] < 0.1

    def test_api_error_returns_none(self):
        with patch("utils.sentiment.requests.post", side_effect=Exception("timeout")):
            result = score_headline_tone("Market report", api_key="test_key")
            assert result is None

    def test_empty_text_returns_none(self):
        result = score_headline_tone("")
        assert result is None

    def test_tone_scores_sum_to_near_one(self):
        """Tone scores for a single headline should approximately sum to 1.0"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            [{"label": "bullish", "score": 0.7},
             {"label": "neutral", "score": 0.2},
             {"label": "bearish", "score": 0.1}]
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = score_headline_tone("Mixed signal headline", api_key="test_key")
            assert result is not None
            total = result["bullish"] + result["neutral"] + result["bearish"]
            assert abs(total - 1.0) < 0.01


class TestAggregateMarketSentimentTone:
    def test_empty_list_returns_neutral_defaults(self):
        result = aggregate_market_sentiment_tone([])
        assert result is not None
        assert result["bullish_pct"] == 0.0
        assert result["bearish_pct"] == 0.0
        assert result["neutral_pct"] == 0.0
        assert result["dominant"] == "neutral"
        assert result["confidence"] == 0.0

    def test_bullish_headline_returns_bullish_dominant(self):
        with patch("utils.sentiment.score_headline_tone") as mock_tone:
            mock_tone.return_value = {"bullish": 0.8, "bearish": 0.1, "neutral": 0.1}
            result = aggregate_market_sentiment_tone(["Positive headline"])
            assert result is not None
            assert result["bullish_pct"] == 80.0
            assert result["bearish_pct"] == 10.0
            assert result["neutral_pct"] == 10.0
            assert result["dominant"] == "bullish"
            assert result["confidence"] == 80.0

    def test_multiple_headlines_correct_aggregation(self):
        with patch("utils.sentiment.score_headline_tone") as mock_tone:
            mock_tone.side_effect = [
                {"bullish": 0.9, "bearish": 0.05, "neutral": 0.05},
                {"bullish": 0.7, "bearish": 0.2, "neutral": 0.1},
                {"bullish": 0.6, "bearish": 0.3, "neutral": 0.1}
            ]
            result = aggregate_market_sentiment_tone([
                "Very positive news",
                "Moderately positive news",
                "Somewhat positive news"
            ])
            assert result["bullish_pct"] == 73.3
            assert result["bearish_pct"] == 18.3
            assert result["neutral_pct"] == 8.3
            assert result["dominant"] == "bullish"
            assert result["confidence"] == 73.3

    def test_mixed_tones_returns_correct_dominant(self):
        with patch("utils.sentiment.score_headline_tone") as mock_tone:
            mock_tone.side_effect = [
                {"bullish": 0.2, "bearish": 0.7, "neutral": 0.1},
                {"bullish": 0.1, "bearish": 0.8, "neutral": 0.1},
                {"bullish": 0.8, "bearish": 0.1, "neutral": 0.1}
            ]
            result = aggregate_market_sentiment_tone([
                "Negative news 1",
                "Negative news 2",
                "Positive news"
            ])
            assert result["bearish_pct"] == 53.3
            assert result["bullish_pct"] == 36.7
            assert result["neutral_pct"] == 10.0
            assert result["dominant"] == "bearish"
            assert result["confidence"] == 53.3

    def test_score_headline_backward_compatibility_unchanged(self):
        with patch("utils.sentiment.requests.post", side_effect=Exception("API down")):
            result = score_headline("Real estate prices surge in Bengaluru", api_key="test_key")
            assert result is None

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            [{"label": "positive", "score": 0.95},
             {"label": "negative", "score": 0.03},
             {"label": "neutral", "score": 0.02}]
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = score_headline("Property values soar in North Bengaluru", api_key="test_key")
            assert result is not None
            assert result > 0