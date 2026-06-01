"""
RE_OS — Sentiment Scorer
─────────────────────────
Financial domain sentiment for real estate news headlines using FinBERT.
Runs via HuggingFace Inference API (free tier, always warm for BERT-class models).
No local model download. No torch. No GPU.

Sentiment labels:
  positive  → bullish signal (new launches, price appreciation, strong demand)
  negative  → bearish signal (distress, delays, oversupply, policy risks)
  neutral   → informational (regulatory filings, general market data)

Scores stored in news_articles.sentiment_score (FLOAT, -1.0 to +1.0):
  +1.0 = strong positive, -1.0 = strong negative, 0.0 = neutral

Usage:
  from utils.sentiment import score_headline, score_batch
  score = score_headline("Prestige launches 500-unit project in Yelahanka at ₹7,500 PSF")
  # → 0.82

  scores = score_batch(["headline 1", "headline 2"], hf_api_key="hf_...")
  # → [0.82, -0.34]
"""

import time

import requests
from loguru import logger

from config.settings import HF_API_KEY, HF_INFERENCE_BASE, FINBERT_MODEL_ID

_FINBERT_URL = f"{HF_INFERENCE_BASE}/{FINBERT_MODEL_ID}"
_LABEL_TO_SCORE = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
_REQUEST_TIMEOUT = 20
_RETRY_SLEEP = 2


def score_headline(headline: str, api_key: str = HF_API_KEY) -> float | None:
    """
    Score a single headline via FinBERT.
    Returns float in [-1.0, 1.0] or None if API unavailable/unconfigured.
    Positive = bullish, negative = bearish.
    """
    if not api_key:
        return None
    if not headline or not headline.strip():
        return None

    try:
        resp = requests.post(
            _FINBERT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"inputs": headline[:512]},  # FinBERT max 512 tokens
            timeout=_REQUEST_TIMEOUT,
        )
        # 503 = model loading (cold start for non-BERT models; FinBERT is warm)
        if resp.status_code == 503:
            logger.debug("[Sentiment] FinBERT loading, retrying once...")
            time.sleep(_RETRY_SLEEP)
            resp = requests.post(
                _FINBERT_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"inputs": headline[:512]},
                timeout=_REQUEST_TIMEOUT,
            )
        if resp.status_code != 200:
            logger.warning(f"[Sentiment] HF API {resp.status_code}: {resp.text[:100]}")
            return None

        data = resp.json()
        # HF pipeline response: [[{"label": "positive", "score": 0.92}, ...]]
        if not data or not isinstance(data, list):
            return None
        candidates = data[0] if isinstance(data[0], list) else data
        # Pick the highest-confidence label
        best = max(candidates, key=lambda x: x.get("score", 0))
        label = best.get("label", "").lower()
        confidence = best.get("score", 0.5)
        base_score = _LABEL_TO_SCORE.get(label, 0.0)
        # Scale by confidence so a low-confidence positive is near 0
        return round(base_score * confidence, 4)

    except Exception as exc:
        logger.debug(f"[Sentiment] score_headline error: {exc}")
        return None


def score_batch(
    headlines: list[str],
    api_key: str = HF_API_KEY,
    delay_between: float = 0.1,
) -> list[float | None]:
    """
    Score a list of headlines. Adds a small delay between requests
    to stay within HF free tier rate limits.
    Returns list of floats (same length as input), None where scoring failed.
    """
    results = []
    for headline in headlines:
        score = score_headline(headline, api_key=api_key)
        results.append(score)
        if delay_between > 0:
            time.sleep(delay_between)
    return results


def aggregate_market_sentiment(scores: list[float | None]) -> dict:
    """
    Aggregate headline scores into a market-level sentiment summary.
    Ignores None values (failed API calls).

    Returns:
      {
        "avg_score": float,     # -1 to +1
        "label": str,           # "positive" | "negative" | "neutral"
        "scored": int,          # how many headlines were scored
        "positive_pct": float,  # % of scored headlines that are positive
        "negative_pct": float,
      }
    """
    valid = [s for s in scores if s is not None]
    if not valid:
        return {"avg_score": 0.0, "label": "neutral", "scored": 0, "positive_pct": 0.0, "negative_pct": 0.0}

    avg = sum(valid) / len(valid)
    positive_pct = round(sum(1 for s in valid if s > 0.2) / len(valid) * 100, 1)
    negative_pct = round(sum(1 for s in valid if s < -0.2) / len(valid) * 100, 1)

    if avg > 0.2:
        label = "positive"
    elif avg < -0.2:
        label = "negative"
    else:
        label = "neutral"

    return {
        "avg_score": round(avg, 4),
        "label": label,
        "scored": len(valid),
        "positive_pct": positive_pct,
        "negative_pct": negative_pct,
    }


if __name__ == "__main__":
    import sys
    test_headlines = [
        "Prestige launches 500-unit project in Yelahanka at ₹7,500 PSF",
        "Developer delays possession of Devanahalli project by 18 months",
        "RERA Karnataka registers 317 new projects in FY 2026",
        "Brigade Group reports 40% absorption in North Bengaluru in Q1",
        "Unsold inventory rises in Hebbal amid slowdown in IT hiring",
    ]
    key = sys.argv[1] if len(sys.argv) > 1 else HF_API_KEY
    if not key:
        print("No HF_API_KEY set. Pass as argument: python utils/sentiment.py hf_xxx")
        sys.exit(1)

    print("Testing FinBERT sentiment via HF Inference API...\n")
    scores = score_batch(test_headlines, api_key=key)
    for headline, score in zip(test_headlines, scores):
        marker = "✓" if score is not None else "✗"
        score_str = f"{score:+.3f}" if score is not None else "failed"
        print(f"  {marker} [{score_str}] {headline[:70]}")

    summary = aggregate_market_sentiment(scores)
    print(f"\nMarket sentiment: {summary['label']} (avg={summary['avg_score']:+.3f}, "
          f"scored={summary['scored']}/{len(test_headlines)})")
