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
  re_os_intel    — market intel reports (outputs/*.txt / *.md files)
  re_os_memories — agent_memories table snapshots (for semantic recall)

Usage:
  from utils.embedder import IntelEmbedder
  embedder = IntelEmbedder()
  embedder.index_intel_reports()                            # nightly batch
  results = embedder.search("affordable housing Yelahanka", n=5)
  results = embedder.query("affordable housing Yelahanka")  # alias for search()
"""

import math
import os
import time as time_module
from datetime import datetime
from pathlib import Path

import requests
from loguru import logger

import chromadb
from chromadb import EmbeddingFunction, Documents, Embeddings

from config.settings import OLLAMA_BASE_URL, CHROMA_DB_PATH

# ChromaDB persistent path — maps to chroma_data volume in Docker.
# Read from settings at module load time (Docker env is stable after container start).
_CHROMA_PATH = os.getenv("CHROMA_DB_PATH") or CHROMA_DB_PATH
_EMBED_MODEL = "nomic-embed-text"
_INTEL_COLLECTION = "re_os_intel"
_MEMORY_COLLECTION = "re_os_memories"
_EMBED_TIMEOUT = 30  # seconds — generous for CPU inference
_OLLAMA_AVAILABILITY_CACHE_SEC = 60


class OllamaEmbeddingFunction(EmbeddingFunction):
    """ChromaDB-compatible embedding function backed by Ollama nomic-embed-text."""

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = _EMBED_MODEL):
        self._base_url = base_url.rstrip("/")
        self._model = model

    def __call__(self, input: Documents) -> Embeddings:
        results = []
        for text in input:
            vec = embed_text(text, base_url=self._base_url, model=self._model)
            results.append(vec or [0.0] * 768)
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


def _ollama_tags_ok(base_url: str = OLLAMA_BASE_URL, timeout: int = 5) -> bool:
    """Quick health-check of Ollama via /api/tags. No cache."""
    try:
        r = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


class _BaseChromaStore:
    """
    Shared base for ChromaDB-backed stores.
    Provides lazy initialisation, common retry wrappers,
    and consistent result formatting.

    Subclasses define _collection_name and may override
    _format_hits for custom metadata key handling.
    """

    def __init__(self, collection_name: str):
        self._collection_name = collection_name
        self._client = None
        self._embed_fn = None
        self._collection = None

    def _ensure_initialized(self):
        if self._collection is not None:
            return
        self._client = _get_chroma_client()
        self._embed_fn = OllamaEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            embedding_function=self._embed_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def _format_hits(self, results: dict) -> list[dict]:
        """Normalise ChromaDB query results into {text, ..., score} list.
        Converts cosine distance to similarity score: score = 1 - distance.
        Missing metadata keys are replaced with empty string defaults."""
        hits = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            hit = {"text": doc or "", "score": round(1.0 - dist, 4)}
            if isinstance(meta, dict):
                hit.update(meta)
            else:
                hit.update({"source": "", "market": "unknown"})
            hits.append(hit)
        return hits

    def count(self) -> int:
        try:
            self._ensure_initialized()
            return self._collection.count()
        except Exception:
            return 0


class IntelEmbedder(_BaseChromaStore):
    """
    Indexes market intel reports into ChromaDB for semantic search.
    Designed for nightly batch runs — not real-time embedding.
    """

    def __init__(self):
        super().__init__(_INTEL_COLLECTION)

    def _ollama_available(self) -> bool:
        return _ollama_tags_ok()

    def index_intel_reports(self, outputs_dir: str = "/app/outputs") -> dict:
        """
        Scan outputs/ for market intel .md files, embed any not yet indexed.
        Returns: {"indexed": N, "skipped": N, "failed": N, "duration_s": float}
        """
        _start = time_module.time()
        if not self._ollama_available():
            logger.warning("[Embedder] Ollama unreachable — skipping intel indexing")
            return {"indexed": 0, "skipped": 0, "failed": 0, "duration_s": 0}

        indexed = skipped = failed = 0
        try:
            self._ensure_initialized()
        except Exception as exc:
            logger.warning(f"[Embedder] ChromaDB init failed: {exc}")
            return {"indexed": 0, "skipped": 0, "failed": 0, "duration_s": 0}

        outputs = Path(outputs_dir)
        if not outputs.exists():
            logger.debug(f"[Embedder] outputs_dir not found: {outputs_dir}")
            return {"indexed": 0, "skipped": 0, "failed": 0, "duration_s": 0}

        # Intel reports saved as .txt (intel_report_*.txt) or .md
        report_files = (
            list(outputs.rglob("intel_report_*.txt"))
            + list(outputs.rglob("*.md"))
        )
        logger.info(f"[Embedder] Found {len(report_files)} intel report(s) to consider")

        for path in report_files:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                if len(text.strip()) < 100:
                    skipped += 1
                    continue
                # Chunk at 2K chars with 150-char overlap — prevents sentence
                # boundary cuts and improves recall for queries that span cuts
                _step = 2000 - 150
                _limit = len(text)
                if _limit > 8000:
                    logger.debug(f"[Embedder] Truncating {path.name} from {_limit} to 8000 chars")
                    _limit = 8000
                chunks = [text[i : i + 2000] for i in range(0, _limit, _step)]
                if len(chunks) > 10:
                    logger.debug(f"[Embedder] Report {path.name} generated {len(chunks)} chunks — capping at 10")
                    chunks = chunks[:10]
                market = _infer_market(str(path))
                for j, chunk in enumerate(chunks):
                    chunk_id = f"intel:{path.stem}:chunk{j}"
                    # Check per-document — avoids loading all IDs into memory
                    existing = self._collection.get(ids=[chunk_id])
                    if existing["ids"]:
                        skipped += 1
                        continue
                    self._collection.add(
                        documents=[chunk],
                        ids=[chunk_id],
                        metadatas=[{
                            "source": str(path.name),
                            "market": market,
                            "indexed_at": datetime.now().isoformat(),
                        }],
                    )
                    indexed += 1
                logger.debug(f"[Embedder] Indexed {path.name} ({len(chunks)} chunk(s))")
            except Exception as exc:
                logger.error(f"[Embedder] Failed to index {path}: {exc}")
                failed += 1

        _dur = time_module.time() - _start
        logger.info(f"[Embedder] Intel index done — indexed={indexed} skipped={skipped} failed={failed} in {_dur:.1f}s")
        return {"indexed": indexed, "skipped": skipped, "failed": failed, "duration_s": round(_dur, 1)}

    def search(self, query: str, n: int = 5, market: str | None = None) -> list[dict]:
        """
        Semantic search over indexed intel reports.
        Returns list of {text, source, market, score} sorted by relevance.
        Score is in [0, 1] — higher is more relevant.
        """
        if not self._ollama_available():
            return []
        try:
            self._ensure_initialized()
        except Exception as exc:
            logger.warning(f"[Embedder] ChromaDB unavailable: {exc}")
            return []

        where = {"market": market} if market else None
        try:
            count = self._collection.count()
            if count == 0:
                return []
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n, count),
                where=where,
            )
            return self._format_hits(results)
        except Exception as exc:
            logger.warning(f"[Embedder] search failed: {exc}")
            return []

    def query(self, question: str, market: str | None = None, n: int = 5) -> list[dict]:
        """Alias for search() with parameter ordering matching TASK_BRIEFS spec."""
        return self.search(question, n=n, market=market)


class MemoryEmbedder(_BaseChromaStore):
    """
    Indexes agent_memories into ChromaDB for semantic recall.
    Used by Board Room context assembly — returns top-K relevant memories
    for a pitch by cosine similarity rather than SQL keyword match.
    """

    def __init__(self):
        super().__init__(_MEMORY_COLLECTION)

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
            self._ensure_initialized()
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
        Results include 'score' in [0, 1] — higher is more relevant.
        """
        where: dict = {}
        if market:
            where["market"] = market
        if agent_id:
            where["agent_id"] = agent_id

        try:
            self._ensure_initialized()
            count = self._collection.count()
            if count == 0:
                return []
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n * 2, count),
                where=where if where else None,
            )
            hits = self._format_hits(results)
            # Filter by confidence threshold
            hits = [h for h in hits if h.get("confidence", 0) >= min_confidence]
            # Sort by score descending (higher = more similar)
            hits.sort(key=lambda x: x["score"], reverse=True)
            return hits[:n]
        except Exception as exc:
            logger.warning(f"[Embedder] search_memories failed: {exc}")
            return []


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
            market = r.get("market", "?")
            source = r.get("source", "?")
            text = (r.get("text") or "")[:120]
            score = r.get("score", 0)
            print(f"  [{market}] {text}... (score={score:.3f})")
