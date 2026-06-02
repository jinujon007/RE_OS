"""
RE_OS — Cross-Encoder Reranker (Sprint 33 — HF Search Quality)
Reranks ChromaDB search results using a cross-encoder model for precision.
Lazy-loads cross-encoder/ms-marco-MiniLM-L-6-v2 on first call (GPU-accelerated).
Gracefully returns original hits on any failure — never blocks the pipeline.
"""
import threading
from typing import Any
from loguru import logger

__all__ = ["CrossEncoderReranker"]

_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                try:
                    from sentence_transformers import CrossEncoder
                    _model = CrossEncoder(
                        "cross-encoder/ms-marco-MiniLM-L-6-v2",
                        device="cuda",
                    )
                except Exception as exc:
                    logger.warning(f"[Reranker] Failed to load cross-encoder: {exc}")
                    _model = False
    return _model if _model is not False else None


class CrossEncoderReranker:
    """Rerank search hits using a cross-encoder model for relevance precision.

    Usage:
        reranker = CrossEncoderReranker()
        results = reranker.rerank("affordable housing Yelahanka", hits, top_n=5)

    Returns new dicts — input hits are never mutated.
    Gracefully degrades to original order on any failure.
    """

    def rerank(
        self,
        query: str,
        hits: list[dict[str, Any]],
        text_key: str = "text",
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """Score each (query, hit[text_key]) pair, sort descending, return top_n.

        Adds 'ce_score' key to each returned hit.
        Returns new dicts — input hits are never mutated.
        Graceful fallback: returns original hits unchanged on any failure.
        """
        if not query or not query.strip():
            return hits
        model = _get_model()
        if model is None or not hits:
            return hits

        try:
            pairs = [(query, h.get(text_key) or "") for h in hits]
            scores = model.predict(pairs, show_progress_bar=False)
            if hasattr(scores, "tolist"):
                scores = scores.tolist()
            if isinstance(scores, list) and scores and isinstance(scores[0], list):
                scores = [round(float(s[0]), 4) for s in scores]
            elif isinstance(scores, list):
                scores = [round(float(s), 4) for s in scores]
            else:
                scores = [round(float(scores), 4)]
            reranked = sorted(
                [{**h, "ce_score": s} for h, s in zip(hits, scores)],
                key=lambda x: float(x.get("ce_score", 0)),
                reverse=True,
            )
            top_n = max(1, min(top_n, len(reranked)))
            return reranked[:top_n]
        except Exception as exc:
            logger.warning(f"[Reranker] Reranking failed: {exc}")
            return hits


if __name__ == "__main__":
    try:
        reranker = CrossEncoderReranker()
        sample_hits = [
            {"text": "Yelahanka sees 20% price jump in Q1 2026", "source": "report_1.txt"},
            {"text": "Brigade launches new project in Hebbal", "source": "report_2.txt"},
        ]
        results = reranker.rerank("Yelahanka price trend", sample_hits, top_n=2)
        for r in results:
            print(f"  score={r.get('ce_score', 'N/A')} | {r.get('text', '')[:60]}")
        print("Reranker OK")
    except ImportError as exc:
        print(f"[Reranker] Missing dependency: {exc}")
        print("Run: pip install sentence-transformers")
    except Exception as exc:
        print(f"[Reranker] Error: {exc}")
