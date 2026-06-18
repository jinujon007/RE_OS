"""T-1247: ChromaDB maintenance job tests."""
import pytest
from unittest.mock import MagicMock, patch, call

pytestmark = pytest.mark.unit


def test_chromadb_purge_deletes_stale():
    """purge_stale_embeddings deletes documents older than cutoff."""
    mock_client = MagicMock()
    now_ts = 1800000000000  # well past 2026 in ms
    stale_ts = (now_ts / 1000 - 100 * 86400) * 1000  # 100 days ago in ms
    fresh_ts = (now_ts / 1000 - 10 * 86400) * 1000  # 10 days ago in ms

    stale_doc_id = "stale_doc_1"
    fresh_doc_id = "fresh_doc_1"

    mock_collection = MagicMock()
    # First page: stale doc
    mock_collection.get.side_effect = [
        {"ids": [stale_doc_id], "metadatas": [{"indexed_at": "2026-03-09T12:00:00"}]},
        {"ids": [], "metadatas": []},
        {"ids": [], "metadatas": []},  # second collection has nothing
    ]
    mock_client.get_collection.return_value = mock_collection
    mock_client.get_or_create_collection.return_value = mock_collection

    with patch("utils.embedder._get_chroma_client", return_value=mock_client):
        from utils.embedder import purge_stale_embeddings

        deleted = purge_stale_embeddings(days=90)
        assert deleted == 1
        mock_collection.delete.assert_called_once_with(ids=[stale_doc_id])


def test_chromadb_purge_returns_count():
    """purge_stale_embeddings returns total deleted count (0 when no stale docs)."""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_collection.get.side_effect = [
        {"ids": [], "metadatas": []},
        {"ids": [], "metadatas": []},
    ]
    mock_client.get_collection.return_value = mock_collection

    with patch("utils.embedder._get_chroma_client", return_value=mock_client):
        from utils.embedder import purge_stale_embeddings

        deleted = purge_stale_embeddings(days=90)
        assert deleted == 0


def test_chromadb_maintenance_job_registered():
    """run_chromadb_maintenance is callable from config.scheduler."""
    from config.scheduler import run_chromadb_maintenance

    assert callable(run_chromadb_maintenance)

    with patch("utils.embedder.purge_stale_embeddings", return_value=0):
        run_chromadb_maintenance()
