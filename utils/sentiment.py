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

Tone functions (Sprint 35):
  score_headline_tone(text, api_key) → {bullish, bearish, neutral} or None
  aggregate_market_sentiment_tone(headlines, api_key) → aggregate dict

6-label tone functions (Sprint 35 deferred — Sprint 50):
  score_tone(text, api_key) → {Risk, Uncertainty, Litigious, Constraining, Positive, Negative}
  dominant_tone(text, api_key) → highest-probability tone label (str)

Usage:
  from utils.sentiment import score_headline, score_batch, score_headline_tone
  from utils.sentiment import score_tone, dominant_tone
  score = score_headline("Prestige launches 500-unit project in Yelahanka at ₹7,500 PSF")
  # → 0.82
  tone = score_headline_tone("Property market surges")
  # → {"bullish": 0.9, "bearish": 0.05, "neutral": 0.05}
  tones = score_tone("RERA project stalled, builder facing insolvency")
  # → {"Risk": 0.82, "Negative": 0.12, ...}
  dominant = dominant_tone("Market uncertainty looms")
  # → "Uncertainty"
  aggregate = aggregate_market_sentiment_tone(["headline 1", "headline 2"])
  # → {"bullish_pct": 65.0, "bearish_pct": 20.0, "neutral_pct": 15.0,
  #     "dominant": "bullish", "confidence": 65.0}
"""

import time

import requests
from loguru import logger

from config.settings import HF_API_KEY, FINBERT_MODEL_ID, FINBERT_TONE_MODEL_ID, FINBERT_TONE_6LABEL_MODEL_ID

# HuggingFace migrated from api-inference.huggingface.co to router.huggingface.co
# in 2025 as part of the Inference Providers rollout.
_FINBERT_BASE_URL = "https://router.huggingface.co/hf-inference/models/"
_LABEL_TO_SCORE = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
_REQUEST_TIMEOUT = 20
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 2  # seconds, doubles each attempt


_SENTINEL = object()


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter (±25%) to prevent thundering herd."""
    import random
    base = _RETRY_BASE_DELAY * (2 ** attempt)
    jitter = base * random.uniform(-0.25, 0.25)
    return base + jitter


def _call_hf_api(headline: str, model_id: str, api_key: str) -> list | None:
    """Shared HF Inference API call with retry logic.
    Retries on 503 (model loading), 429 (rate limit), and network errors with jittered backoff.
    Returns parsed JSON list or None on failure."""
    url = f"{_FINBERT_BASE_URL}{model_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"inputs": headline[:512]}

    for attempt in range(_RETRY_ATTEMPTS):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=_REQUEST_TIMEOUT)
            if resp.status_code in (503, 429) and attempt < _RETRY_ATTEMPTS - 1:
                delay = _retry_delay(attempt)
                logger.debug("[Sentiment] HF API {} (attempt {}/{}), retrying in {:.1f}s...",
                             resp.status_code, attempt + 1, _RETRY_ATTEMPTS, delay)
                time.sleep(delay)
                continue
            if resp.status_code != 200:
                logger.warning("[Sentiment] HF API {}: {}", resp.status_code, resp.text[:100])
                return None
            data = resp.json()
            if not data or not isinstance(data, list):
                return None
            return data[0] if isinstance(data[0], list) else data
        except Exception as exc:
            if attempt < _RETRY_ATTEMPTS - 1:
                delay = _retry_delay(attempt)
                logger.debug("[Sentiment] HF API error (attempt {}/{}), retrying in {:.1f}s: {}",
                             attempt + 1, _RETRY_ATTEMPTS, delay, exc)
                time.sleep(delay)
                continue
            logger.debug("[Sentiment] HF API call failed after {} attempts: {}", _RETRY_ATTEMPTS, exc)
            return None
    return None


def score_headline(headline: str, api_key: str | object = _SENTINEL, model_id: str = FINBERT_MODEL_ID) -> float | None:
    """
    Score a single headline via FinBERT.
    Returns float in [-1.0, 1.0] or None if API unavailable/unconfigured.
    Positive = bullish, negative = bearish.
    Uses sentinel default so HF_API_KEY is read fresh on each call
    (thread-safe, supports runtime env changes).
    """
    key: str = HF_API_KEY if api_key is _SENTINEL else api_key  # type: ignore
    if not key:
        return None

    candidates = _call_hf_api(headline, model_id, key)
    if not candidates:
        return None

    try:
        best = max(candidates, key=lambda x: x.get("score", 0))
        label = best.get("label", "").lower()
        confidence = best.get("score", 0.5)
        base_score = _LABEL_TO_SCORE.get(label, 0.0)
        return round(base_score * confidence, 4)
    except Exception as exc:
        logger.debug(f"[Sentiment] score_headline parse error: {exc}")
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


def score_headline_tone(headline: str, api_key: str | object = _SENTINEL) -> dict[str, float] | None:
    """
    Score a single headline for tone (bullish/bearish/neutral) using FinBERT-tone.
    Returns dict with keys 'bullish', 'bearish', 'neutral' (each 0.0-1.0) or None if API unavailable.
    """
    key: str = HF_API_KEY if api_key is _SENTINEL else api_key  # type: ignore
    if not key:
        return None

    candidates = _call_hf_api(headline, FINBERT_TONE_MODEL_ID, key)
    if not candidates:
        return None

    try:
        tone_scores = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
        for candidate in candidates:
            label = candidate.get("label", "").lower()
            score = candidate.get("score", 0.0)
            if label in tone_scores:
                tone_scores[label] = score
        return tone_scores
    except Exception as exc:
        logger.debug(f"[Sentiment] score_headline_tone parse error: {exc}")
        return None


def aggregate_market_sentiment_tone(headlines: list[str], api_key: str | object = _SENTINEL) -> dict[str, float | str]:
    """
    Aggregate headline tone scores into a market-level sentiment summary.
    Ignores None values (failed API calls). Adds 0.1s delay between requests
    to stay within HF free tier rate limits.
    Always returns a dict (never None).

    Returns:
        {
            "bullish_pct": float,     # 0-100
            "bearish_pct": float,     # 0-100
            "neutral_pct": float,     # 0-100
            "dominant": str,          # "bullish" | "bearish" | "neutral"
            "confidence": float,      # 0-100, percentage of dominant tone
        }
    """
    tone_results = []
    for headline in headlines:
        tone_score = score_headline_tone(headline, api_key=api_key)
        if tone_score is not None:
            tone_results.append(tone_score)
            time.sleep(0.1)  # rate-limit guard
    
    if not tone_results:
        return {"bullish_pct": 0.0, "bearish_pct": 0.0, "neutral_pct": 0.0, "dominant": "neutral", "confidence": 0.0}
    
    # Calculate averages
    avg_bullish = sum(t["bullish"] for t in tone_results) / len(tone_results)
    avg_bearish = sum(t["bearish"] for t in tone_results) / len(tone_results)
    avg_neutral = sum(t["neutral"] for t in tone_results) / len(tone_results)
    
    # Convert to percentages
    bullish_pct = round(avg_bullish * 100, 1)
    bearish_pct = round(avg_bearish * 100, 1)
    neutral_pct = round(avg_neutral * 100, 1)
    
    # Determine dominant tone
    if bullish_pct > bearish_pct and bullish_pct > neutral_pct:
        dominant = "bullish"
        confidence = bullish_pct
    elif bearish_pct > bullish_pct and bearish_pct > neutral_pct:
        dominant = "bearish"
        confidence = bearish_pct
    else:
        dominant = "neutral"
        confidence = neutral_pct
    
    return {
        "bullish_pct": bullish_pct,
        "bearish_pct": bearish_pct,
        "neutral_pct": neutral_pct,
        "dominant": dominant,
        "confidence": round(confidence, 1)
    }


def label_from_score(score: float | None) -> str:
    """Convert float score to human label."""
    if score is None:
        return "unscored"
    if score > 0.2:
        return "positive"
    if score < -0.2:
        return "negative"
    return "neutral"


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


def score_tone(text: str, api_key: str | object = _SENTINEL) -> dict[str, float] | None:
    """
    Score text with yiyanghkust/finbert-tone (6-label: Risk, Uncertainty,
    Litigious, Constraining, Positive, Negative).
    Returns dict with one key per tone (0.0-1.0) or None if API unavailable.
    """
    key: str = HF_API_KEY if api_key is _SENTINEL else api_key
    if not key or not text:
        return None

    candidates = _call_hf_api(text, FINBERT_TONE_6LABEL_MODEL_ID, key)
    if not candidates:
        return None

    try:
        tones = {"Risk": 0.0, "Uncertainty": 0.0, "Litigious": 0.0,
                 "Constraining": 0.0, "Positive": 0.0, "Negative": 0.0}
        for candidate in candidates:
            label = candidate.get("label", "")
            score = candidate.get("score", 0.0)
            if label in tones:
                tones[label] = score
        return tones
    except Exception as exc:
        logger.debug("[Sentiment] score_tone parse error: {}", exc)
        return None


def dominant_tone(text: str, api_key: str | object = _SENTINEL) -> str | None:
    """
    Return the highest-probability tone label from yiyanghkust/finbert-tone.
    Returns None if API unavailable.
    """
    tones = score_tone(text, api_key=api_key)
    if not tones:
        return None
    return max(tones, key=tones.get)


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
