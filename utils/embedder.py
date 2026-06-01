"""
RE_OS — Embedder
─────────────────
Semantic indexing of market intel reports and agent memories using
nomic-embed-text served by the existing Ollama container (CPU, zero cost).

Architecture:
  - Embeddings: Ollama API → nomic-embed-text (274MB, ~1-2K tok/s on CPU)
  - Storage:    ChromaDB PersistentClient (already in requirements)
  - No torch, no local model loading in the agents container.

Collections:
  re_os_intel    — market intel reports (outputs/*.md files)
  re_os_memories — agent_memories table snapshots (for semantic recall)

Usage:
  from utils.embedder import IntelEmbedder
  embedder = IntelEmbedder()
  embedder.index_intel_reports()                         # nightly batch
  results = embedder.search("affordable housing Yelahanka", n=5)
"""

import math
import os
from datetime import datetime
from pathlib import Path

import requests
from loguru import logger

import chromadb
from chromadb import EmbeddingFunction, Documents, Embeddings

from config.settings import OLLAMA_BASE_URL

# ChromaDB persistent path — maps to a volume in Docker so data survives restarts
_CHROMA_PATH = os.getenv("CHROMA_PATH", "/app/chroma_data")
_EMBED_MODEL = "nomic-embed-text"
_INTEL_COLLECTION = "re_os_intel"
_MEMORY_COLLECTION = "re_os_memories"
_EMBED_TIMEOUT = 30  # seconds — generous for CPU inference


class OllamaEmbeddingFunction(EmbeddingFunction):
    """ChromaDB-compatible embedding function backed by Ollama nomic-embed-text."""

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = _EMBED_MODEL):
        self._base_url = base_url.rstrip("/")
        self._model = model

    def __call__(self, input: Documents) -> Embeddings:
        results = []
        for text in input:
            vec = embed_text(text, base_url=self._base_url, model=self._model)
            results.append(vec)
        return results


def embed_text(
    text: str,
    base_url: str = OLLAMA_BASE_URL,
    model: str = _EMBED_MODEL,
) -> list[float]:
    """
    Get a single embedding vector from Ollama.
    Returns empty list on failure — callers must guard against this.
    """
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=_EMBED_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("embedding", [])
    except Exception as exc:
        logger.warning(f"[Embedder] embed_text failed: {exc}")
        return []


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity — no numpy, no torch."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_chroma_client() -> chromadb.PersistentClient:
    os.makedirs(_CHROMA_PATH, exist_ok=True)
    return chromadb.PersistentClient(path=_CHROMA_PATH)


class IntelEmbedder:
    """
    Indexes market intel reports into ChromaDB for semantic search.
    Designed for nightly batch runs — not real-time embedding.
    """

    def __init__(self):
        self._client = _get_chroma_client()
        self._embed_fn = OllamaEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=_INTEL_COLLECTION,
            embedding_function=self._embed_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def _ollama_available(self) -> bool:
        try:
            r = requests.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def index_intel_reports(self, outputs_dir: str = "/app/outputs") -> dict:
        """
        Scan outputs/ for market intel .md files, embed any not yet indexed.
        Returns: {"indexed": N, "skipped": N, "failed": N}
        """
        if not self._ollama_available():
            logger.warning("[Embedder] Ollama unreachable — skipping intel indexing")
            return {"indexed": 0, "skipped": 0, "failed": 0}

        indexed = skipped = failed = 0
        existing_ids: set[str] = set(self._collection.get()["ids"])

        # Intel reports saved as .txt (intel_report_*.txt) or .md
        report_files = (
            list(Path(outputs_dir).rglob("intel_report_*.txt"))
            + list(Path(outputs_dir).rglob("*.md"))
        )
        logger.info(f"[Embedder] Found {len(report_files)} intel report(s) to consider")

        for path in report_files:
            doc_id = f"intel:{path.stem}"
            if doc_id in existing_ids:
                skipped += 1
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                if len(text.strip()) < 100:
                    skipped += 1
                    continue
                # Chunk at 2K chars — nomic-embed-text has 8K token context but
                # smaller chunks give sharper retrieval for paragraph-level search
                chunks = [text[i : i + 2000] for i in range(0, min(len(text), 8000), 2000)]
                for j, chunk in enumerate(chunks):
                    chunk_id = f"{doc_id}:chunk{j}"
                    if chunk_id in existing_ids:
                        continue
                    self._collection.add(
                        documents=[chunk],
                        ids=[chunk_id],
                        metadatas=[{
                            "source": str(path),
                            "market": _infer_market(str(path)),
                            "indexed_at": datetime.now().isoformat(),
                        }],
                    )
                indexed += 1
                logger.debug(f"[Embedder] Indexed {path.name} ({len(chunks)} chunk(s))")
            except Exception as exc:
                logger.error(f"[Embedder] Failed to index {path}: {exc}")
                failed += 1

        logger.info(f"[Embedder] Intel index done — indexed={indexed} skipped={skipped} failed={failed}")
        return {"indexed": indexed, "skipped": skipped, "failed": failed}

    def search(self, query: str, n: int = 5, market: str | None = None) -> list[dict]:
        """
        Semantic search over indexed intel reports.
        Returns list of {text, source, market, distance}.
        """
        if not self._ollama_available():
            return []
        where = {"market": market} if market else None
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n, self._collection.count() or 1),
                where=where,
            )
            hits = []
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                hits.append({
                    "text": doc,
                    "source": meta.get("source", ""),
                    "market": meta.get("market", ""),
                    "distance": dist,
                })
            return hits
        except Exception as exc:
            logger.warning(f"[Embedder] search failed: {exc}")
            return []


class MemoryEmbedder:
    """
    Indexes agent_memories into ChromaDB for semantic recall.
    Used by Board Room context assembly — returns top-K relevant memories
    for a pitch by cosine similarity rather than SQL keyword match.
    """

    def __init__(self):
        self._client = _get_chroma_client()
        self._embed_fn = OllamaEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=_MEMORY_COLLECTION,
            embedding_function=self._embed_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_memory(
        self,
        memory_id: str,
        fact: str,
        agent_id: str,
        market: str,
        confidence: float,
    ) -> None:
        """Upsert a single memory fact into the vector store."""
        try:
            self._collection.upsert(
                documents=[fact],
                ids=[memory_id],
                metadatas=[{
                    "agent_id": agent_id,
                    "market": market,
                    "confidence": confidence,
                    "updated_at": datetime.now().isoformat(),
                }],
            )
        except Exception as exc:
            logger.warning(f"[Embedder] upsert_memory failed for {memory_id}: {exc}")

    def search_memories(
        self,
        query: str,
        market: str | None = None,
        agent_id: str | None = None,
        n: int = 10,
        min_confidence: float = 0.4,
    ) -> list[dict]:
        """
        Semantic search over agent memories.
        Returns facts ranked by relevance to query, filtered by confidence.
        """
        where: dict = {}
        if market:
            where["market"] = market
        if agent_id:
            where["agent_id"] = agent_id

        try:
            count = self._collection.count()
            if count == 0:
                return []
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n * 2, count),
                where=where if where else None,
            )
            hits = []
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                if meta.get("confidence", 0) >= min_confidence:
                    hits.append({
                        "fact": doc,
                        "agent_id": meta.get("agent_id"),
                        "market": meta.get("market"),
                        "confidence": meta.get("confidence"),
                        "distance": dist,
                    })
            # Sort by distance (lower = more similar in cosine space)
            hits.sort(key=lambda x: x["distance"])
            return hits[:n]
        except Exception as exc:
            logger.warning(f"[Embedder] search_memories failed: {exc}")
            return []


def _infer_market(path_str: str) -> str:
    """Guess market from file path (checks directory name, then filename)."""
    p = path_str.lower().replace("\\", "/")
    if "yelahanka" in p:
        return "Yelahanka"
    if "devanahalli" in p:
        return "Devanahalli"
    if "hebbal" in p:
        return "Hebbal"
    return "unknown"


if __name__ == "__main__":
    import sys
    logger.add("logs/embedder.log", rotation="10 MB")
    embedder = IntelEmbedder()
    stats = embedder.index_intel_reports(outputs_dir="outputs")
    print(f"Indexed: {stats}")
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        results = embedder.search(query, n=3)
        print(f"\nTop results for: '{query}'")
        for r in results:
            print(f"  [{r['market']}] {r['text'][:120]}... (dist={r['distance']:.3f})")
