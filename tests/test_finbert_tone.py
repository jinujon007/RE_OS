import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit

from utils.sentiment import score_tone, dominant_tone


class TestScoreTone:
    def test_score_tone_returns_6_keys(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            {"label": "Positive", "score": 0.7},
            {"label": "Negative", "score": 0.1},
            {"label": "Risk", "score": 0.05},
            {"label": "Uncertainty", "score": 0.05},
            {"label": "Litigious", "score": 0.05},
            {"label": "Constraining", "score": 0.05},
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = score_tone("RERA project progressing well", api_key="test_key")
            assert result is not None
            assert len(result) == 6
            for tone in ("Positive", "Negative", "Risk", "Uncertainty", "Litigious", "Constraining"):
                assert tone in result

    def test_returns_none_when_no_api_key(self):
        result = score_tone("Real estate prices surge in Bengaluru")
        assert result is None

    def test_returns_none_on_empty_text(self):
        result = score_tone("", api_key="test_key")
        assert result is None

    def test_api_error_returns_none(self):
        with patch("utils.sentiment.requests.post", side_effect=Exception("timeout")):
            result = score_tone("Market report", api_key="test_key")
            assert result is None

    def test_non_200_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal server error"
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = score_tone("Test", api_key="test_key")
            assert result is None

    def test_503_retry_then_success(self):
        fail_resp = MagicMock()
        fail_resp.status_code = 503
        fail_resp.text = "Loading"
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json = lambda: [
            {"label": "Positive", "score": 0.6},
            {"label": "Negative", "score": 0.2},
            {"label": "Risk", "score": 0.1},
            {"label": "Uncertainty", "score": 0.05},
            {"label": "Litigious", "score": 0.03},
            {"label": "Constraining", "score": 0.02},
        ]
        with patch("utils.sentiment.requests.post", side_effect=[fail_resp, ok_resp]):
            with patch("time.sleep"):
                result = score_tone("Test", api_key="test_key")
                assert result is not None
                assert result["Positive"] > 0.5

    def test_503_retry_exhausted_returns_none(self):
        fail_resp = MagicMock()
        fail_resp.status_code = 503
        fail_resp.text = "Still loading"
        with patch("utils.sentiment.requests.post", return_value=fail_resp):
            with patch("time.sleep"):
                result = score_tone("Test", api_key="test_key")
                assert result is None

    def test_preserves_all_6_tones_when_api_returns_partial(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            {"label": "Risk", "score": 0.9},
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = score_tone("Risk warning", api_key="test_key")
            assert result is not None
            assert len(result) == 6
            assert result["Risk"] == 0.9
            for tone in ("Positive", "Negative", "Uncertainty", "Litigious", "Constraining"):
                assert result[tone] == 0.0


class TestDominantTone:
    def test_dominant_tone_returns_string(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            {"label": "Positive", "score": 0.8},
            {"label": "Negative", "score": 0.1},
            {"label": "Risk", "score": 0.03},
            {"label": "Uncertainty", "score": 0.03},
            {"label": "Litigious", "score": 0.02},
            {"label": "Constraining", "score": 0.02},
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = dominant_tone("Property market surges", api_key="test_key")
            assert result == "Positive"

    def test_dominant_tone_returns_none_without_key(self):
        result = dominant_tone("Test headline")
        assert result is None

    def test_dominant_tone_risk_text(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            {"label": "Risk", "score": 0.85},
            {"label": "Negative", "score": 0.1},
            {"label": "Positive", "score": 0.02},
            {"label": "Uncertainty", "score": 0.01},
            {"label": "Litigious", "score": 0.01},
            {"label": "Constraining", "score": 0.01},
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = dominant_tone("RERA project stalled, builder facing insolvency", api_key="test_key")
            assert result == "Risk"

    def test_dominant_tone_uncertainty_text(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            {"label": "Uncertainty", "score": 0.75},
            {"label": "Risk", "score": 0.1},
            {"label": "Negative", "score": 0.08},
            {"label": "Positive", "score": 0.03},
            {"label": "Litigious", "score": 0.02},
            {"label": "Constraining", "score": 0.02},
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = dominant_tone("Market uncertainty looms", api_key="test_key")
            assert result == "Uncertainty"

    def test_dominant_tone_tie_returns_first_max(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: [
            {"label": "Uncertainty", "score": 0.5},
            {"label": "Risk", "score": 0.5},
            {"label": "Negative", "score": 0.0},
            {"label": "Positive", "score": 0.0},
            {"label": "Litigious", "score": 0.0},
            {"label": "Constraining", "score": 0.0},
        ]
        with patch("utils.sentiment.requests.post", return_value=mock_resp):
            result = dominant_tone("Tie", api_key="test_key")
            assert result in ("Uncertainty", "Risk")


class TestToneIntegration:
    def test_tone_integration_in_news_plugin(self):
        from ingest.plugins.news_plugin import _score_article
        with patch("utils.sentiment.score_headline", return_value=0.5):
            with patch("utils.sentiment.score_tone") as mock_tone:
                mock_tone.return_value = {
                    "Positive": 0.7, "Negative": 0.1, "Risk": 0.05,
                    "Uncertainty": 0.05, "Litigious": 0.05, "Constraining": 0.05,
                }
                result = _score_article("Test headline")
                assert result.tone_label == "Positive"
                assert result.tone_score_val == 0.7

    def test_tone_integration_handles_api_failure(self):
        from ingest.plugins.news_plugin import _score_article
        with patch("utils.sentiment.score_headline", return_value=0.0):
            with patch("utils.sentiment.score_tone", return_value=None):
                result = _score_article("Test")
                assert result.tone_label is None
                assert result.tone_score_val is None

    def test_tone_integration_preserves_sentiment_when_tone_fails(self):
        from ingest.plugins.news_plugin import _score_article
        with patch("utils.sentiment.score_headline", return_value=0.75):
            with patch("utils.sentiment.score_tone", return_value=None):
                result = _score_article("Positive news")
                assert result.sentiment_score == 0.75
                assert result.sentiment_label == "positive"
                assert result.tone_label is None
                assert result.tone_score_val is None
