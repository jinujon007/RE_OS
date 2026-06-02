import pytest
from unittest.mock import patch
from scrapers.scout_memory import ScoutMemory
pytestmark = pytest.mark.unit


class FakeModel:
    """Stand-in for SentenceTransformer.encode() returning deterministic 384-dim unit vectors."""

    def encode(self, text, normalize_embeddings=True):
        import hashlib
        np = __import__("numpy")
        seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        rng = np.random.RandomState(seed)
        vec = rng.randn(384).astype(np.float32)
        norm = np.linalg.norm(vec)
        return (vec / norm).reshape(1, -1)


class TestSemanticDedup:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        ScoutMemory.clear_cache()

    def _make_scout(self, market="Yelahanka", tmp_path=None):
        from scrapers.scout_memory import ScoutMemory
        base = str(tmp_path) if tmp_path else None
        return ScoutMemory(market, base_dir=base)

    def _patch_model(self):
        """Mock _get_semantic_model to return FakeModel."""
        return patch("scrapers.scout_memory._get_semantic_model", return_value=FakeModel())

    def test_sha_fastpath_skips_semantic(self, tmp_path):
        """Known CID should hit SHA fast-path, never call semantic check."""
        scout = self._make_scout(tmp_path=tmp_path)
        cid = scout.cid_project("Brigade", "Golden Gate", "Yelahanka")
        scout.record(cid, {"project_name": "Golden Gate", "developer_name": "Brigade"})
        with self._patch_model() as mock_model_fn:
            result = scout.record(cid, {"project_name": "Golden Gate", "developer_name": "Brigade"})
            assert result is False
            assert mock_model_fn.called is False

    def test_near_identical_text_blocked(self, tmp_path):
        """Near-duplicate text should be blocked by semantic check."""
        scout = self._make_scout(tmp_path=tmp_path)
        data1 = {"project_name": "Prestige Lakeside Habitat", "developer_name": "Prestige"}
        cid1 = scout.cid_project("Prestige", "Lakeside", "Yelahanka")
        with self._patch_model():
            r1 = scout.record(cid1, data1)
            assert r1 is True
            cid2 = scout.cid_project("Prestige", "Lakeside-2", "Yelahanka")
            r2 = scout.record(cid2, {"project_name": "Prestige Lakeside Habitat", "developer_name": "Prestige"})
            assert r2 is False

    def test_different_text_stored_and_cached(self, tmp_path):
        """Clearly different text should pass through and be cached."""
        scout = self._make_scout(tmp_path=tmp_path)
        data1 = {"project_name": "Sobha Azure", "developer_name": "Sobha"}
        data2 = {"project_name": "Godrej Woods", "developer_name": "Godrej"}
        cid1 = scout.cid_project("Sobha", "Azure", "Yelahanka")
        cid2 = scout.cid_project("Godrej", "Woods", "Yelahanka")
        with self._patch_model():
            assert scout.record(cid1, data1) is True
            assert scout.record(cid2, data2) is True
            market = "yelahanka"
            assert len(ScoutMemory._recent_embeddings[market]) == 2

    def test_market_isolation(self, tmp_path):
        """Yelahanka dedup should not affect Devanahalli cache."""
        yel = self._make_scout("Yelahanka", tmp_path=tmp_path)
        dev = self._make_scout("Devanahalli", tmp_path=tmp_path)
        data = {"project_name": "Brigade Gateway", "developer_name": "Brigade"}
        cid_yel = yel.cid_project("Brigade", "Gateway", "Yelahanka")
        cid_dev = dev.cid_project("Brigade", "Gateway", "Devanahalli")
        with self._patch_model():
            assert yel.record(cid_yel, data) is True
            market_key = "yelahanka"
            assert len(ScoutMemory._recent_embeddings[market_key]) == 1
            market_key_d = "devanahalli"
            assert len(ScoutMemory._recent_embeddings.get(market_key_d, [])) == 0
            assert dev.record(cid_dev, data) is True
            assert len(ScoutMemory._recent_embeddings[market_key_d]) == 1

    def test_cache_cap(self, tmp_path):
        """Cache should not exceed _MAX_CACHE_PER_MARKET entries."""
        scout = self._make_scout(tmp_path=tmp_path)
        with self._patch_model():
            for i in range(510):
                cid = scout.cid_project("Dev", f"Proj{i}", "Yelahanka")
                scout.record(cid, {"project_name": f"Project {i} Unique Name", "developer_name": "Dev"})
            market = "yelahanka"
            assert len(ScoutMemory._recent_embeddings[market]) <= 500

    def test_orthogonal_vector_passes_threshold(self, tmp_path):
        """Orthogonal vectors with sim ≈ 0.0 should pass (below 0.92 threshold)."""
        scout = self._make_scout(tmp_path=tmp_path)
        from scrapers.scout_memory import _cosine_sim_norm
        vec_a = [1.0] + [0.0] * 383
        vec_b = [0.0] + [1.0] + [0.0] * 382
        sim = _cosine_sim_norm(vec_a, vec_b)
        assert sim == pytest.approx(0.0, abs=0.01)
        assert sim < 0.92

    def test_identical_vector_blocked(self, tmp_path):
        """Identical vectors with sim == 1.0 should be blocked (above 0.92 threshold)."""
        from scrapers.scout_memory import _cosine_sim_norm
        vec = [1.0] + [0.0] * 383
        sim = _cosine_sim_norm(vec, vec)
        assert sim == pytest.approx(1.0, abs=0.01)
        assert sim > 0.93

    def test_graceful_on_model_load_failure(self, tmp_path):
        """Semantic dedup should gracefully no-op if model fails to load."""
        scout = self._make_scout(tmp_path=tmp_path)
        with patch("scrapers.scout_memory._get_semantic_model", return_value=None):
            cid = scout.cid_project("Brigade", "New Proj", "Yelahanka")
            result = scout.record(cid, {"project_name": "Brigade New Proj"})
            assert result is True

    def test_empty_market_no_crash(self, tmp_path):
        """Empty market string should not crash semantic check."""
        scout = self._make_scout("", tmp_path=tmp_path)
        with self._patch_model():
            cid = scout.cid_project("Test", "Proj", "")
            result = scout.record(cid, {"project_name": "Test Project"})
            assert result is True

    def test_semantic_miss_records_new_discovery(self, tmp_path):
        """Items that pass both SHA and semantic checks should be recorded as new."""
        scout = self._make_scout(tmp_path=tmp_path)
        with self._patch_model():
            cid1 = scout.cid_project("Brigade", "Alpha", "Yelahanka")
            assert scout.record(cid1, {"project_name": "Brigade Alpha"}) is True
            cid2 = scout.cid_project("Brigade", "Omega", "Yelahanka")
            assert scout.record(cid2, {"project_name": "Brigade Omega"}) is True
            stats = scout.stats()
            assert stats["total_known"] == 2

