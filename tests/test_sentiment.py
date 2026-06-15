import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit

from utils.sentiment import score_headline, label_from_score, aggregate_market_sentiment

API_KEY = "hf_test"


class TestScoreHeadline:
    def test_returns_none_when_no_api_key(self):
        result = score_headline("Real estate prices surge in Bengaluru", api_key="")
        assert result is None

    def test_positive_sentiment(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            [
                {"label": "positive", "score": 0.95},
                {"label": "negative", "score": 0.03},
                {"label": "neutral", "score": 0.02},
            ]
        ]
        with patch("requests.post", return_value=mock_resp):
            result = score_headline(
                "Property values soar in North Bengaluru", api_key=API_KEY
            )
            assert result is not None
            assert result > 0

    def test_negative_sentiment(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            [
                {"label": "negative", "score": 0.88},
                {"label": "neutral", "score": 0.10},
                {"label": "positive", "score": 0.02},
            ]
        ]
        with patch("requests.post", return_value=mock_resp):
            result = score_headline("Real estate market crashes", api_key=API_KEY)
            assert result is not None
            assert result < 0

    def test_api_error_returns_none(self):
        with patch("requests.post", side_effect=Exception("timeout")):
            result = score_headline("Market report", api_key=API_KEY)
            assert result is None

    def test_non_200_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal server error"
        with patch("requests.post", return_value=mock_resp):
            result = score_headline("Test", api_key=API_KEY)
            assert result is None

    def test_empty_text_returns_none(self):
        result = score_headline("", api_key=API_KEY)
        assert result is None

    def test_whitespace_text_returns_none(self):
        result = score_headline("   ", api_key=API_KEY)
        assert result is None

    def test_neutral_sentiment(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            [
                {"label": "neutral", "score": 0.90},
                {"label": "positive", "score": 0.05},
                {"label": "negative", "score": 0.05},
            ]
        ]
        with patch("requests.post", return_value=mock_resp):
            result = score_headline("RERA publishes guidelines", api_key=API_KEY)
            assert result is not None
            assert result == 0.0

    def test_401_unauthorized_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = '{"error":"Unauthorized"}'
        with patch("requests.post", return_value=mock_resp):
            result = score_headline("Test headline", api_key="bad_key")
            assert result is None

    def test_503_retry_then_success(self):
        """Verify 503 → retry → 200 path works."""
        fail_resp = MagicMock()
        fail_resp.status_code = 503
        fail_resp.text = "Model loading"
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = [[{"label": "positive", "score": 0.9}]]
        with patch("requests.post", side_effect=[fail_resp, ok_resp]):
            with patch("time.sleep"):
                result = score_headline("Test", api_key=API_KEY)
                assert result is not None
                assert result > 0

    def test_503_retry_exhausted_returns_none(self):
        """All 3 retries fail → None."""
        fail_resp = MagicMock()
        fail_resp.status_code = 503
        fail_resp.text = "Still loading"
        with patch("requests.post", return_value=fail_resp):
            with patch("time.sleep"):
                result = score_headline("Test", api_key=API_KEY)
                assert result is None

    def test_unicode_headline(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [[{"label": "positive", "score": 0.7}]]
        with patch("requests.post", return_value=mock_resp):
            result = score_headline(
                "Prestige launches 500 units in यelahanka at ₹7,500", api_key=API_KEY
            )
            assert result is not None
            assert result > 0

    def test_very_long_headline_truncated(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [[{"label": "neutral", "score": 0.6}]]
        long_text = "Market " * 200  # 1400 chars, will be truncated to ~512 tokens
        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = score_headline(long_text, api_key=API_KEY)
            # Verify truncation: the inputs sent to HF API are ≤512 chars
            call_arg = mock_post.call_args[1]["json"]["inputs"]
            assert len(call_arg) <= 512
            # Verify the API response is still parseable after truncation
            assert result is not None
            assert result == 0.0  # neutral label * 0.6 confidence


class TestLabelFromScore:
    def test_positive_label(self):
        assert label_from_score(0.5) == "positive"

    def test_negative_label(self):
        assert label_from_score(-0.5) == "negative"

    def test_neutral_label(self):
        assert label_from_score(0.1) == "neutral"

    def test_boundary_positive(self):
        assert label_from_score(0.21) == "positive"

    def test_boundary_negative(self):
        assert label_from_score(-0.21) == "negative"

    def test_none_returns_unscored(self):
        assert label_from_score(None) == "unscored"


class TestAggregateMarketSentiment:
    def test_empty_list_returns_neutral(self):
        result = aggregate_market_sentiment([])
        assert result["label"] == "neutral"
        assert result["scored"] == 0
        assert result["avg_score"] == 0.0

    def test_all_none_returns_neutral(self):
        result = aggregate_market_sentiment([None, None, None])
        assert result["label"] == "neutral"
        assert result["scored"] == 0

    def test_positive_majority(self):
        result = aggregate_market_sentiment([0.8, 0.6, 0.7])
        assert result["label"] == "positive"
        assert result["scored"] == 3
        assert result["positive_pct"] == 100.0

    def test_negative_majority(self):
        result = aggregate_market_sentiment([-0.5, -0.7, -0.3])
        assert result["label"] == "negative"
        assert result["negative_pct"] == 100.0

    def test_mixed_scores_ignores_none(self):
        result = aggregate_market_sentiment([0.8, None, -0.2, None])
        assert result["scored"] == 2
        assert result["avg_score"] == round((0.8 + (-0.2)) / 2, 4)

    def test_avg_score_precision(self):
        result = aggregate_market_sentiment([0.3, 0.5])
        assert result["avg_score"] == 0.4
