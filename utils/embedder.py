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

Graceful Degradation Matrix:
  Dependency        | Down behavior                                  | User-visible impact
  ──────────────────┼────────────────────────────────────────────────┼─────────────────────────
  Ollama            | Falls back to keyword grep on outputs/         | Results are lexical not semantic
  ChromaDB          | Falls back to keyword grep on outputs/         | Same Ollama-down behavior
  Both Ollama+Chroma| Keyword grep (no embedding, no vector store)   | Reduced recall quality
  Outputs dir empty | Returns [], logged at DEBUG                    | Empty search results
  HF API (sentiment)| Returns None, logged at DEBUG                  | sentiment_score stays NULL
  
  The keyword fallback is a flat grep over intel_report_*.txt files.
  It does not support semantic similarity — results are scored by
  number of query terms that appear in the document (0..1).

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
_OLLAMA_HEALTH_TTL = 10  # cache Ollama health-check result for N seconds
_ollama_last_check: float = 0.0
_ollama_last_status: bool = False

# Module-level metrics counters — zero-initialized, incremented by each operation
_metrics: dict[str, int] = {
    "search_calls": 0,
    "search_chroma_hits": 0,
    "search_fallback_hits": 0,
    "search_empty": 0,
    "index_calls": 0,
    "index_chunks_indexed": 0,
    "index_chunks_skipped": 0,
    "index_chunks_failed": 0,
    "ollama_unavailable_count": 0,
    "chroma_unavailable_count": 0,
    "embed_text_calls": 0,
    "embed_text_failures": 0,
}


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
    _metrics["embed_text_calls"] += 1
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=_EMBED_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("embedding", [])
    except Exception as exc:
        _metrics["embed_text_failures"] += 1
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
    """Quick health-check of Ollama via /api/tags. Results cached for _OLLAMA_HEALTH_TTL seconds."""
    global _ollama_last_check, _ollama_last_status
    now = time_module.time()
    if now - _ollama_last_check < _OLLAMA_HEALTH_TTL:
        return _ollama_last_status
    try:
        r = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        _ollama_last_status = r.status_code == 200
    except Exception:
        _ollama_last_status = False
    _ollama_last_check = now
    return _ollama_last_status


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
        Converts cosine distance to similarity score: score = max(0, 1 - distance).
        ChromaDB cosine distances are in [0, 2]; clamping prevents negative scores
        for highly dissimilar results. Missing metadata keys default to empty string.
        """
        hits = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            hit = {"text": doc or "", "score": round(max(0.0, 1.0 - dist), 4)}
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

    def get_metrics(self) -> dict:
        """Return module-level metrics counters. Useful for dashboard health endpoint."""
        return dict(_metrics)

    @staticmethod
    def log_metrics_summary():
        """Log a one-line summary of all metrics counters at INFO level."""
        logger.info(f"[Embedder Metrics] {_metrics}")

    def index_intel_reports(self, outputs_dir: str = "/app/outputs") -> dict:
        """
        Scan outputs/ for market intel .md files, embed any not yet indexed.
        Returns: {"indexed": N, "skipped": N, "failed": N, "duration_s": float}
        """
        _start = time_module.time()
        _metrics["index_calls"] += 1
        if not self._ollama_available():
            _metrics["ollama_unavailable_count"] += 1
            logger.warning("[Embedder] Ollama unreachable — skipping intel indexing")
            return {"indexed": 0, "skipped": 0, "failed": 0, "duration_s": 0}

        indexed = skipped = failed = 0
        try:
            self._ensure_initialized()
        except Exception as exc:
            _metrics["chroma_unavailable_count"] += 1
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
                # Sentence-aware chunking: 2000-char windows with 300-char overlap,
                # aligned to sentence boundaries to prevent mid-sentence cuts.
                # Higher overlap improves recall for entity-spanning queries like
                # "Yelahanka PSF trend" where name and metric are 500+ chars apart.
                import re as _re
                _CHUNK_SIZE = 2000
                _CHUNK_OVERLAP = 300
                _MAX_CHARS = 8000
                _MAX_CHUNKS = 10
                _limit = len(text)
                if _limit > _MAX_CHARS:
                    logger.debug(f"[Embedder] Truncating {path.name} from {_limit} to {_MAX_CHARS} chars")
                    _limit = _MAX_CHARS
                text = text[:_limit]
                # Split on sentence boundaries (newline or period + space)
                sentences = _re.split(r'(?<=[.\n])\s+', text)
                chunks = []
                current = []
                current_len = 0
                for sent in sentences:
                    if current_len + len(sent) > _CHUNK_SIZE and current:
                        chunks.append(" ".join(current))
                        # Keep overlap sentences from the tail of current window
                        overlap = []
                        overlap_len = 0
                        for s in reversed(current):
                            if overlap_len + len(s) > _CHUNK_OVERLAP:
                                break
                            overlap.insert(0, s)
                            overlap_len += len(s)
                        current = overlap
                        current_len = overlap_len
                    current.append(sent)
                    current_len += len(sent)
                if current:
                    chunks.append(" ".join(current))
                if len(chunks) > _MAX_CHUNKS:
                    logger.debug(f"[Embedder] Report {path.name} generated {len(chunks)} chunks — capping at {_MAX_CHUNKS}")
                    chunks = chunks[:_MAX_CHUNKS]
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

        _metrics["index_chunks_indexed"] += indexed
        _metrics["index_chunks_skipped"] += skipped
        _metrics["index_chunks_failed"] += failed
        _dur = time_module.time() - _start
        # Log ChromaDB collection size if available
        try:
            coll_size = self._collection.count()
            logger.info(f"[Embedder] Intel index done — indexed={indexed} skipped={skipped} failed={failed} "
                        f"in {_dur:.1f}s | ChromaDB collection size: {coll_size}")
        except Exception:
            logger.info(f"[Embedder] Intel index done — indexed={indexed} skipped={skipped} failed={failed} in {_dur:.1f}s")
        return {"indexed": indexed, "skipped": skipped, "failed": failed, "duration_s": round(_dur, 1)}

    def _keyword_search_fallback(self, query: str, n: int = 5, market: str | None = None) -> list[dict]:
        """Grep-based fallback when Ollama is unavailable. Scans report files for query terms."""
        outputs_dir = "/app/outputs"
        output_path = Path(outputs_dir)
        if not output_path.exists():
            return []
        terms = query.lower().split()[:5]
        if not terms:
            return []
        results = []
        for market_dir in output_path.iterdir():
            if not market_dir.is_dir():
                continue
            dir_market = _infer_market(str(market_dir))
            if market and market.lower() != dir_market.lower():
                continue
            for report in market_dir.glob("intel_report_*.txt"):
                try:
                    text = report.read_text(encoding="utf-8", errors="ignore")
                    text_lower = text.lower()
                    match_count = sum(1 for t in terms if t in text_lower)
                    if match_count > 0:
                        score = round(min(match_count / max(len(terms), 1), 1.0), 4)
                        results.append({
                            "text": text[:2000],
                            "source": report.name,
                            "market": dir_market,
                            "score": score,
                        })
                except Exception:
                    continue
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:n]

    def search(self, query: str, n: int = 5, market: str | None = None) -> list[dict]:
        """
        Semantic search over indexed intel reports.
        Falls back to keyword grep when Ollama unavailable.
        Returns list of {text, source, market, score} sorted by relevance.
        Score is in [0, 1] — higher is more relevant.

        Latency budget:
          - Ollama available: ~2-5s (embed + query round-trip to ChromaDB)
          - Keyword fallback: ~0.1-0.5s (file grep on outputs/)
          - Ollama health check: cached 10s TTL — first call hits API, subsequent calls return cached
        """
        _metrics["search_calls"] += 1
        if not self._ollama_available():
            _metrics["search_fallback_hits"] += 1
            _metrics["ollama_unavailable_count"] += 1
            logger.debug("[Embedder] Ollama down — using keyword fallback search")
            return self._keyword_search_fallback(query, n=n, market=market)
        try:
            self._ensure_initialized()
        except Exception as exc:
            _metrics["chroma_unavailable_count"] += 1
            logger.warning(f"[Embedder] ChromaDB unavailable: {exc}")
            return self._keyword_search_fallback(query, n=n, market=market)

        where = {"market": market} if market else None
        try:
            count = self._collection.count()
            if count == 0:
                keyword_results = self._keyword_search_fallback(query, n=n, market=market)
                if keyword_results:
                    _metrics["search_fallback_hits"] += 1
                    logger.debug("[Embedder] ChromaDB empty — falling back to keyword search")
                    return keyword_results
                _metrics["search_empty"] += 1
                return []
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n, count),
                where=where,
            )
            _metrics["search_chroma_hits"] += 1
            return self._format_hits(results)
        except Exception as exc:
            logger.warning(f"[Embedder] search failed: {exc}")
            keyword_results = self._keyword_search_fallback(query, n=n, market=market)
            if keyword_results:
                _metrics["search_fallback_hits"] += 1
                logger.debug("[Embedder] ChromaDB query failed — falling back to keyword search")
                return keyword_results
            _metrics["search_empty"] += 1
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
