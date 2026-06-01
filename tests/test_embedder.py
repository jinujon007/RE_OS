import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestIntelEmbedder:
    def test_index_empty_dir(self, tmp_path):
        mock_coll = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with patch("utils.embedder._get_chroma_client", return_value=mock_client), \
             patch("utils.embedder.OllamaEmbeddingFunction"), \
             patch("utils.embedder._ollama_tags_ok", return_value=True):
            from utils.embedder import IntelEmbedder
            e = IntelEmbedder()
            stats = e.index_intel_reports(str(tmp_path))
            assert stats["indexed"] == 0
            assert stats["failed"] == 0

    def test_index_nonexistent_dir(self):
        mock_coll = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with patch("utils.embedder._get_chroma_client", return_value=mock_client), \
             patch("utils.embedder.OllamaEmbeddingFunction"), \
             patch("utils.embedder._ollama_tags_ok", return_value=True):
            from utils.embedder import IntelEmbedder
            e = IntelEmbedder()
            stats = e.index_intel_reports("/nonexistent/path")
            assert stats["indexed"] == 0

    def test_search_returns_empty_when_ollama_unavailable(self):
        with patch("utils.embedder.OllamaEmbeddingFunction"), \
             patch("utils.embedder._get_chroma_client") as mock_cc:
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
        with patch("utils.embedder._get_chroma_client", return_value=mock_client), \
             patch("utils.embedder.OllamaEmbeddingFunction"):
            from utils.embedder import IntelEmbedder
            e = IntelEmbedder()
            with patch.object(e, "_ollama_available", return_value=True):
                with patch.object(mock_coll, "count", return_value=5):
                    result = e.search("test")
                    assert result == []

    def test_ollama_unavailable_skips_indexing(self):
        with patch("utils.embedder.OllamaEmbeddingFunction"), \
             patch("utils.embedder._get_chroma_client") as mock_cc:
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
        with patch("utils.embedder._get_chroma_client", return_value=mock_client), \
             patch("utils.embedder.OllamaEmbeddingFunction"):
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
        with patch("utils.embedder._get_chroma_client", return_value=mock_client), \
             patch("utils.embedder.OllamaEmbeddingFunction"):
            from utils.embedder import IntelEmbedder
            e = IntelEmbedder()
            with patch.object(e, "_ollama_available", return_value=True):
                results = e.search("\u20b97,500 PSF \u092f\u0947\u0932\u0939\u0928\u094d\u0915\u093e")
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
        with patch("utils.embedder._get_chroma_client", return_value=mock_client), \
             patch("utils.embedder.OllamaEmbeddingFunction"):
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
            "metadatas": [[{"agent_id": "analyst", "market": "Yelahanka", "confidence": 0.8}]],
            "distances": [[0.1]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with patch("utils.embedder._get_chroma_client", return_value=mock_client), \
             patch("utils.embedder.OllamaEmbeddingFunction"):
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
        with patch("utils.embedder._get_chroma_client", return_value=mock_client), \
             patch("utils.embedder.OllamaEmbeddingFunction"):
            from utils.embedder import MemoryEmbedder
            m = MemoryEmbedder()
            results = m.search_memories("test", min_confidence=0.5)
            assert len(results) == 0

    def test_search_filters_by_agent_id(self):
        mock_coll = MagicMock()
        mock_coll.count.return_value = 2
        mock_coll.query.return_value = {
            "documents": [["analyst fact", "scraper fact"]],
            "metadatas": [[
                {"agent_id": "analyst", "confidence": 0.8},
                {"agent_id": "scraper", "confidence": 0.7},
            ]],
            "distances": [[0.1, 0.2]],
        }
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with patch("utils.embedder._get_chroma_client", return_value=mock_client), \
             patch("utils.embedder.OllamaEmbeddingFunction"):
            from utils.embedder import MemoryEmbedder
            m = MemoryEmbedder()
            results = m.search_memories("test", agent_id="analyst")
            assert len(results) == 2  # agent_id filter is passed as where, not post-filter

    def test_search_returns_empty_for_empty_collection(self):
        mock_coll = MagicMock()
        mock_coll.count.return_value = 0
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with patch("utils.embedder._get_chroma_client", return_value=mock_client), \
             patch("utils.embedder.OllamaEmbeddingFunction"):
            from utils.embedder import MemoryEmbedder
            m = MemoryEmbedder()
            results = m.search_memories("test")
            assert results == []

    def test_search_handles_collection_error(self):
        mock_coll = MagicMock()
        mock_coll.count.side_effect = Exception("chroma error")
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_coll
        with patch("utils.embedder._get_chroma_client", return_value=mock_client), \
             patch("utils.embedder.OllamaEmbeddingFunction"):
            from utils.embedder import MemoryEmbedder
            m = MemoryEmbedder()
            results = m.search_memories("test")
            assert results == []
