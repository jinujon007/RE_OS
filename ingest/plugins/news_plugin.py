"""
RE_OS — News Plugin (Sprint 61)
Wraps NewsScout to scrape real-estate news articles. Applies inline
FinBERT sentiment scoring via ThreadPoolExecutor for parallelism
so N articles complete in roughly 1× latency instead of N×.
"""

from __future__ import annotations

from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger
from ingest.base import DataPlugin, ParsedRecord

__all__ = ["NewsPlugin", "ArticleScore"]

ArticleScore = namedtuple(
    "ArticleScore",
    ["sentiment_score", "sentiment_label", "tone_label", "tone_score_val"],
)
ArticleScore.__doc__ = """
Aggregated sentiment + 6-label tone result for one article.
sentiment_score: float [-1, 1] or None
sentiment_label: str (positive/negative/neutral/unscored)
tone_label: str (Risk/Uncertainty/...) or None
tone_score_val: float [0, 1] or None
"""


def _score_article(headline: str) -> ArticleScore:
    """Single-article sentiment scoring task for executor.
    Returns ArticleScore namedtuple with sentiment and 6-label tone."""
    from utils.sentiment import score_headline, label_from_score, score_tone

    score = score_headline(headline)
    label = label_from_score(score)
    tones = score_tone(headline)
    if tones:
        dominant = max(tones, key=tones.get)
        tone_score_val = round(tones[dominant], 4)
    else:
        dominant = None
        tone_score_val = None
    return ArticleScore(score, label, dominant, tone_score_val)


_DEFAULT_SCORE = ArticleScore(None, "unscored", None, None)


class NewsPlugin(DataPlugin):
    plugin_id = "news_scout"
    source_id = "news_sources"

    def run(self, market: str) -> list[ParsedRecord]:
        from scrapers.news_scout import NewsScout

        scout = NewsScout(market=market)
        articles = scout.scout(days_back=60)

        # Parallel sentiment scoring
        headlines = {
            str(a.get("cid", "")): str(a.get("headline", ""))
            for a in articles
            if a.get("cid")
        }
        sentiment_cache: dict[str, ArticleScore] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            fut_map = {
                pool.submit(_score_article, h): cid for cid, h in headlines.items()
            }
            for fut in as_completed(fut_map):
                cid = fut_map[fut]
                try:
                    sentiment_cache[cid] = fut.result()
                except Exception:
                    sentiment_cache[cid] = _DEFAULT_SCORE

        records: list[ParsedRecord] = []
        for article in articles:
            cid = str(article.get("cid", "")).strip()
            if not cid:
                continue
            result = sentiment_cache.get(cid, _DEFAULT_SCORE)
            data = {
                "cid": cid,
                "source": str(article.get("source", "")),
                "market": market,
                "headline": str(article.get("headline", "")),
                "published_date": str(article.get("published_date", "")),
                "signal_type": str(article.get("signal_type", "other")),
                "projects_mentioned": str(article.get("projects_mentioned", "")),
                "developers_mentioned": str(article.get("developers_mentioned", "")),
                "price_signal": str(article.get("price_signal", "")),
                "key_insight": str(article.get("key_insight", "")),
                "source_url": str(article.get("source_url", "")),
                "sentiment_score": result.sentiment_score,
                "sentiment_label": result.sentiment_label,
                "tone_label": result.tone_label,
                "tone_score": result.tone_score_val,
                "scraped_at": str(article.get("scraped_at", "")),
            }
            records.append(
                ParsedRecord(
                    entity_type="news_article",
                    source_id=cid,
                    market=market,
                    data=data,
                )
            )
        logger.info("[NewsPlugin] {} articles for {}", len(records), market)
        return records
