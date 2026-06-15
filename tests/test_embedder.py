import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestIntelEmbedder:
    def test_index_empty_dir(self, tmp_path):
        mock_coll = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
            patch("utils.embedder._ollama_tags_ok", return_value=True),
        ):
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            stats = e.index_intel_reports(str(tmp_path))
            assert stats["indexed"] == 0
            assert stats["failed"] == 0

    def test_index_nonexistent_dir(self):
        mock_coll = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
            patch("utils.embedder._ollama_tags_ok", return_value=True),
        ):
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            stats = e.index_intel_reports("/nonexistent/path")
            assert stats["indexed"] == 0

    def test_search_returns_empty_when_ollama_unavailable(self):
        with (
            patch("utils.embedder.OllamaEmbeddingFunction"),
            patch("utils.embedder._get_chroma_client") as mock_cc,
        ):
            mock_cc.return_value.get_or_create_collection.return_value = MagicMock()
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            with patch.object(e, "_ollama_available", return_value=False):
                result = e.search("test question")
                assert result == []

    def test_search_returns_empty_on_chroma_error(self):
        mock_coll = MagicMock()
        mock_coll.query.side_effect = Exception("chroma query failed")
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
        ):
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            with patch.object(e, "_ollama_available", return_value=True):
                with patch.object(mock_coll, "count", return_value=5):
                    result = e.search("test")
                    assert result == []

    def test_ollama_unavailable_skips_indexing(self):
        with (
            patch("utils.embedder.OllamaEmbeddingFunction"),
            patch("utils.embedder._get_chroma_client") as mock_cc,
        ):
            mock_cc.return_value.get_or_create_collection.return_value = MagicMock()
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            with patch.object(e, "_ollama_available", return_value=False):
                stats = e.index_intel_reports("/tmp")
                assert stats["indexed"] == 0
                assert stats["failed"] == 0

    def test_embed_text_returns_empty_on_error(self):
        with patch("requests.post", side_effect=Exception("ollama down")):
            from utils.embedder import embed_text

            result = embed_text("test")
            assert result == []

    def test_search_with_market_filter(self):
        mock_coll = MagicMock()
        mock_coll.query.return_value = {
            "documents": [["doc1"]],
            "metadatas": [[{"source": "test.txt", "market": "Yelahanka"}]],
            "distances": [[0.15]],
        }
        mock_coll.count.return_value = 10
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
        ):
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            with patch.object(e, "_ollama_available", return_value=True):
                results = e.search("trend", market="Yelahanka")
                assert len(results) == 1
                assert results[0]["market"] == "Yelahanka"
                assert results[0]["score"] == pytest.approx(0.85, rel=0.01)

    def test_search_with_unicode_query(self):
        mock_coll = MagicMock()
        mock_coll.query.return_value = {
            "documents": [["Bengaluru real estate \u20b97,500 PSF report"]],
            "metadatas": [[{"source": "r.txt", "market": "Yelahanka"}]],
            "distances": [[0.05]],
        }
        mock_coll.count.return_value = 5
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
        ):
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            with patch.object(e, "_ollama_available", return_value=True):
                results = e.search(
                    "\u20b97,500 PSF \u092f\u0947\u0932\u0939\u0928\u094d\u0915\u093e"
                )
                assert len(results) == 1
                assert results[0]["score"] == pytest.approx(0.95, rel=0.01)

    def test_query_alias_matches_search(self):
        """query() is a reordering alias for search(); both return same results."""
        mock_coll = MagicMock()
        mock_coll.query.return_value = {
            "documents": [["result text"]],
            "metadatas": [[{"source": "x.txt", "market": "Hebbal"}]],
            "distances": [[0.2]],
        }
        mock_coll.count.return_value = 5
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
        ):
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            with patch.object(e, "_ollama_available", return_value=True):
                s = e.search("test", market="Hebbal")
                q = e.query("test", market="Hebbal")
                assert len(s) == len(q) == 1
                assert s[0]["text"] == q[0]["text"]
                assert s[0]["score"] == q[0]["score"]


class TestMemoryEmbedder:
    def test_upsert_and_search(self):
        mock_coll = MagicMock()
        mock_coll.count.return_value = 1
        mock_coll.query.return_value = {
            "documents": [["fact about Yelahanka"]],
            "metadatas": [
                [{"agent_id": "analyst", "market": "Yelahanka", "confidence": 0.8}]
            ],
            "distances": [[0.1]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
        ):
            from utils.embedder import MemoryEmbedder

            m = MemoryEmbedder()
            m.upsert_memory("mem1", "fact", "analyst", "Yelahanka", 0.8)
            results = m.search_memories("query", market="Yelahanka")
            assert len(results) == 1
            assert results[0]["score"] == pytest.approx(0.9, rel=0.01)
            assert results[0].get("market") == "Yelahanka"

    def test_search_filters_by_min_confidence(self):
        mock_coll = MagicMock()
        mock_coll.count.return_value = 1
        mock_coll.query.return_value = {
            "documents": [["low confidence fact"]],
            "metadatas": [[{"agent_id": "analyst", "confidence": 0.2}]],
            "distances": [[0.3]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
        ):
            from utils.embedder import MemoryEmbedder

            m = MemoryEmbedder()
            results = m.search_memories("test", min_confidence=0.5)
            assert len(results) == 0

    def test_search_filters_by_agent_id(self):
        mock_coll = MagicMock()
        mock_coll.count.return_value = 2
        mock_coll.query.return_value = {
            "documents": [["analyst fact", "scraper fact"]],
            "metadatas": [
                [
                    {"agent_id": "analyst", "confidence": 0.8},
                    {"agent_id": "scraper", "confidence": 0.7},
                ]
            ],
            "distances": [[0.1, 0.2]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
        ):
            from utils.embedder import MemoryEmbedder

            m = MemoryEmbedder()
            results = m.search_memories("test", agent_id="analyst")
            assert (
                len(results) == 2
            )  # agent_id filter is passed as where, not post-filter

    def test_search_returns_empty_for_empty_collection(self):
        mock_coll = MagicMock()
        mock_coll.count.return_value = 0
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
        ):
            from utils.embedder import MemoryEmbedder

            m = MemoryEmbedder()
            results = m.search_memories("test")
            assert results == []

    def test_search_handles_collection_error(self):
        mock_coll = MagicMock()
        mock_coll.count.side_effect = Exception("chroma error")
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
        ):
            from utils.embedder import MemoryEmbedder

            m = MemoryEmbedder()
            results = m.search_memories("test")
            assert results == []


class TestSTFallback:
    """T-429: SentenceTransformer fallback when Ollama unavailable."""

    def test_st_fallback_used_when_ollama_down(self):
        """When _ollama_tags_ok returns False, collection name gets _st suffix."""
        mock_coll = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
            patch("utils.embedder.SentenceTransformerEmbeddingFunction"),
            patch("utils.embedder._ollama_tags_ok", return_value=False),
        ):
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            e._ensure_initialized()
            call_name = mock_client.get_or_create_collection.call_args[1]["name"]
            assert "_st" in call_name

    def test_st_fallback_384_dim(self):
        """SentenceTransformerEmbeddingFunction returns 384-dim vectors."""
        import numpy as np
        from utils.embedder import SentenceTransformerEmbeddingFunction

        fn = SentenceTransformerEmbeddingFunction()
        fn._model = MagicMock()
        fn._model.encode.return_value = np.array([[0.1] * 384])
        result = fn(["test"])
        assert len(result[0]) == 384

    def test_bge_m3_zero_vector_1024_dim(self):
        """BGE-M3 fallback zero vector is 1024-dimensional."""
        from utils.embedder import _EMBED_DIM

        zero_vec = [0.0] * _EMBED_DIM
        assert len(zero_vec) == 1024


class TestMigrationGuard:
    """T-428: Collection migration guard detects stale dims."""

    def test_migration_triggered_on_dim_mismatch(self):
        """Stale 768-dim collection triggers delete+recreate."""
        mock_coll_old = MagicMock()
        mock_coll_old.name = "re_os_intel"
        mock_coll_new = MagicMock()
        mock_coll_new.name = "re_os_intel"
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll_old
        mock_client.create_collection.return_value = mock_coll_new

        fake_embed_fn = MagicMock()
        fake_embed_fn.side_effect = lambda inp: [[0.0] * 768]  # stale 768-dim

        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
            patch("utils.embedder._ollama_tags_ok", return_value=True),
        ):
            from utils.embedder import IntelEmbedder
            from utils.embedder import _BaseChromaStore

            e = IntelEmbedder()
            e._embed_fn = fake_embed_fn
            e._client = mock_client
            e._collection = mock_coll_old
            e._check_migrate_collection()
            assert mock_client.delete_collection.called
            assert mock_client.create_collection.called


class TestIntelEmbedderRerankerIntegration:
    """T-436: CrossEncoderReranker wired into IntelEmbedder.search()."""

    pytestmark = [
        pytest.mark.skip("T-436 — _get_reranker not implemented until Sprint 33")
    ]

    def test_search_with_rerank_calls_reranker(self):
        """When rerank=True and reranker available, ChromaDB fetches 3x and reranker is called."""
        mock_coll = MagicMock()
        mock_coll.count.return_value = 10
        mock_coll.query.return_value = {
            "documents": [["doc A", "doc B", "doc C"]],
            "metadatas": [
                [
                    {"source": "a.txt", "market": "Yelahanka"},
                    {"source": "b.txt", "market": "Yelahanka"},
                    {"source": "c.txt", "market": "Yelahanka"},
                ]
            ],
            "distances": [[0.1, 0.2, 0.3]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        fake_reranker = MagicMock()
        fake_reranker.rerank.return_value = [{"text": "reranked", "ce_score": 0.9}]
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
            patch("utils.embedder._get_reranker", return_value=fake_reranker),
        ):
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            with patch.object(e, "_ollama_available", return_value=True):
                results = e.search("test query", n=2)
                assert fake_reranker.rerank.called
                call_args = fake_reranker.rerank.call_args[1]
                assert call_args["top_n"] == 2
                assert call_args["query"] == "test query"

    def test_search_with_rerank_false_bypasses_reranker(self):
        """When rerank=False, ChromaDB fetches n (not 3n) and reranker is not called."""
        mock_coll = MagicMock()
        mock_coll.count.return_value = 10
        mock_coll.query.return_value = {
            "documents": [["doc A"]],
            "metadatas": [[{"source": "a.txt", "market": "Yelahanka"}]],
            "distances": [[0.1]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        fake_reranker = MagicMock()
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
            patch("utils.embedder._get_reranker", return_value=fake_reranker),
        ):
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            with patch.object(e, "_ollama_available", return_value=True):
                results = e.search("test", n=2, rerank=False)
                assert not fake_reranker.rerank.called

    def test_search_rerank_graceful_degrade(self):
        """When reranker unavailable, search returns ChromaDB results without crash."""
        mock_coll = MagicMock()
        mock_coll.count.return_value = 5
        mock_coll.query.return_value = {
            "documents": [["doc A"]],
            "metadatas": [[{"source": "a.txt", "market": "Yelahanka"}]],
            "distances": [[0.1]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with (
            patch("utils.embedder._get_chroma_client", return_value=mock_client),
            patch("utils.embedder.OllamaEmbeddingFunction"),
            patch("utils.embedder._get_reranker", return_value=None),
        ):
            from utils.embedder import IntelEmbedder

            e = IntelEmbedder()
            with patch.object(e, "_ollama_available", return_value=True):
                results = e.search("test", n=2)
                assert len(results) == 1
                assert results[0]["text"] == "doc A"
