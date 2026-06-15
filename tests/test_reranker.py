import pytest
from unittest.mock import patch

pytestmark = pytest.mark.unit


class FakeCrossEncoder:
    def predict(self, pairs, show_progress_bar=False):
        """Return deterministic scores in REVERSE index order.

        First pair gets lowest score, last pair gets highest.
        This proves the reranker actually reorders hits."""
        import numpy as np

        return np.array([float(i) for i in range(len(pairs))])


class TestCrossEncoderReranker:
    def _make_reranker(self):
        from utils.reranker import CrossEncoderReranker

        return CrossEncoderReranker()

    def _patch_model(self, return_value=...):
        if return_value is ...:
            return_value = FakeCrossEncoder()
        return patch("utils.reranker._get_model", return_value=return_value)

    def test_reranker_changes_order(self):
        """Reranker should reorder hits by relevance score."""
        hits = [
            {"text": "low relevance doc"},
            {"text": "high relevance doc"},
        ]
        reranker = self._make_reranker()
        with self._patch_model():
            results = reranker.rerank("test query", hits, top_n=2)
        assert len(results) == 2
        assert results[0]["ce_score"] > results[1]["ce_score"]
        assert results[0]["text"] == "high relevance doc"

    def test_empty_hits_returns_empty(self):
        """Empty hits should return empty list."""
        reranker = self._make_reranker()
        with self._patch_model():
            results = reranker.rerank("test", [], top_n=5)
        assert results == []

    def test_single_hit_unchanged(self):
        """Single hit should be returned as-is with ce_score added."""
        hits = [{"text": "single doc"}]
        reranker = self._make_reranker()
        with self._patch_model():
            results = reranker.rerank("query", hits, top_n=5)
        assert len(results) == 1
        assert results[0]["text"] == "single doc"
        assert "ce_score" in results[0]

    def test_top_n_clamp(self):
        """top_n should not exceed hits length."""
        hits = [
            {"text": "doc A"},
            {"text": "doc B"},
            {"text": "doc C"},
        ]
        reranker = self._make_reranker()
        with self._patch_model():
            results = reranker.rerank("q", hits, top_n=10)
        assert len(results) == 3

    def test_top_n_floored_at_one(self):
        """top_n=0 should be clamped to 1."""
        hits = [{"text": "doc"}]
        reranker = self._make_reranker()
        with self._patch_model():
            results = reranker.rerank("q", hits, top_n=0)
        assert len(results) == 1

    def test_model_failure_returns_original_order(self):
        """On model failure, return original hits unchanged."""
        hits = [
            {"text": "first"},
            {"text": "second"},
        ]
        reranker = self._make_reranker()
        with self._patch_model(return_value=None):
            results = reranker.rerank("query", hits, top_n=2)
        assert len(results) == 2
        assert results[0]["text"] == "first"
        assert results[1]["text"] == "second"
        assert "ce_score" not in results[0]

    def test_top_n_equals_len_all_returned(self):
        """top_n == len(hits) should return all hits."""
        hits = [
            {"text": "doc A"},
            {"text": "doc B"},
            {"text": "doc C"},
        ]
        reranker = self._make_reranker()
        with self._patch_model():
            results = reranker.rerank("q", hits, top_n=3)
        assert len(results) == 3
