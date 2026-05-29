"""
RE_OS — News Scout
────────────────────
Market intelligence from property news and announcements.
Catches signals that portals and RERA miss:
  • Soft-launch announcements (pre-RERA, pre-portal)
  • Price revision announcements
  • Regulatory news (BDA zone changes, metro alignment)
  • Developer financial distress signals
  • Absorption and demand trend articles

Sources:
  1. Google News RSS — most comprehensive, no API key needed
  2. ET Realty search — structured property news
  3. Times of India Property — print media + digital
  4. Moneycontrol Real Estate section
  5. 99acres Blog/News — portal-native coverage

Model: Gemini Flash — article comprehension + entity extraction
       Cerebras fallback for shorter articles

Dedup: canonical ID = news:{sha16(url)} — article-level.
       Same story from different sources gets separate entries.

Run standalone:
  python scrapers/news_scout.py --market Yelahanka
  python scrapers/news_scout.py --market Yelahanka --days 30
"""

import argparse
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from loguru import logger

from config.settings import (
    GEMINI_API_KEY,
    GEMINI_CEO_MODEL,
    CEREBRAS_API_KEY,
    CEREBRAS_BASE_URL,
    CEREBRAS_MODEL,
)
from scrapers.scout_memory import ScoutMemory


# ── Search query templates per market ────────────────────────────────────────

NEWS_QUERIES: dict[str, list[str]] = {
    "Yelahanka": [
        "Yelahanka real estate project launch Bangalore",
        "Yelahanka property price 2026",
        "Yelahanka apartment new launch",
        "Kogilu Jakkur real estate project",
        "North Bangalore new residential project 2026",
    ],
    "Devanahalli": [
        "Devanahalli real estate project launch",
        "Devanahalli property prices 2026",
        "Devanahalli BIAL aerospace park residential",
        "Bangalore airport zone property launch",
    ],
    "Hebbal": [
        "Hebbal real estate project launch",
        "Hebbal property prices 2026",
        "Hebbal Nagawara Thanisandra new project",
    ],
}

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

NEWS_EXTRACTION_PROMPT = """\
You are extracting real estate intelligence from property news articles.
For each article, extract signals relevant to residential real estate in Bangalore.

Return a JSON array of objects, one per article, with:
  headline         (string: article title)
  published_date   (string: date if visible, else null)
  market           (string: which Bangalore micro-market/locality this is about)
  signal_type      (string: one of "new_launch" | "price_change" | "regulatory" |
                    "developer_news" | "demand_trend" | "infrastructure" | "other")
  projects_mentioned (array of strings: project names if named)
  developers_mentioned (array of strings: developer names if named)
  price_signal     (string or null: any price/psf mentioned, e.g. "₹7,500/sqft")
  key_insight      (string: one sentence — the most actionable intelligence)
  url              (string: article URL if present in text)

Include only articles relevant to residential real estate in North Bangalore.
Skip articles about South/East/West Bengaluru unless they have market-wide implications.
Return ONLY the JSON array, no commentary.

ARTICLES TEXT:
"""


# ── Google News RSS fetch ─────────────────────────────────────────────────────


def _fetch_google_news_rss(query: str, days_back: int = 60) -> list[dict]:
    """
    Fetch Google News RSS for a query. Returns list of article dicts.
    No API key required — uses public RSS endpoint.
    """
    encoded_query = quote(query)
    rss_url = (
        f"https://news.google.com/rss/search"
        f"?q={encoded_query}"
        f"&hl=en-IN&gl=IN&ceid=IN:en"
    )
    articles = []
    try:
        resp = requests.get(rss_url, headers=SCRAPE_HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.debug(
                f"[NewsScout] Google News RSS HTTP {resp.status_code} for '{query}'"
            )
            return []

        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return []

        cutoff = datetime.now() - timedelta(days=days_back)
        total_items = 0
        filtered_count = 0
        for item in channel.findall("item"):
            total_items += 1
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            pub_date_str = item.findtext("pubDate") or ""
            description = item.findtext("description") or ""

            # Date filter (parse RFC 2822 date)
            try:
                from email.utils import parsedate_to_datetime

                pub_dt = parsedate_to_datetime(pub_date_str)
                if pub_dt.replace(tzinfo=None) < cutoff:
                    filtered_count += 1
                    continue
            except Exception as exc:
                logger.warning(
                    f"[NewsScout] Could not parse pub date '{pub_date_str}': {exc} — including article without date filter"
                )

            articles.append(
                {
                    "title": title,
                    "url": link,
                    "published": pub_date_str,
                    "snippet": description,
                    "source": "google_news_rss",
                }
            )

        if filtered_count > 0:
            logger.debug(
                f"[NewsScout] Google News RSS '{query}': "
                f"{total_items} items, {filtered_count} filtered (>{days_back}d old), "
                f"{len(articles)} passed"
            )

    except Exception as exc:
        logger.warning(f"[NewsScout] Google News RSS fetch failed for '{query}': {exc}")

    return articles


# ── ET Realty search fetch ────────────────────────────────────────────────────


def _fetch_et_realty(query: str, session: requests.Session) -> list[dict]:
    """Scrape ET Realty search results page."""
    encoded = quote(query)
    url = f"https://realty.economictimes.indiatimes.com/search?query={encoded}"
    articles = []
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            logger.debug(
                f"[NewsScout] ET Realty HTTP {resp.status_code} for query '{query}'"
            )
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(".eachStory, .story-box, article, .article-box")
        for item in items[:10]:
            title_el = item.select_one("h3, h4, .title, .headline")
            link_el = item.select_one("a[href]")
            snippet_el = item.select_one("p, .summary, .description")

            title = title_el.get_text(strip=True) if title_el else ""
            link = link_el["href"] if link_el else ""
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            if not title:
                continue
            if not link.startswith("http"):
                link = "https://realty.economictimes.indiatimes.com" + link

            articles.append(
                {
                    "title": title,
                    "url": link,
                    "published": "",
                    "snippet": snippet,
                    "source": "et_realty",
                }
            )
    except Exception as exc:
        logger.debug(f"[NewsScout] ET Realty fetch error: {exc}")
    return articles


# ── AI article analysis ───────────────────────────────────────────────────────


def _ai_analyze_articles(articles: list[dict], market: str) -> list[dict]:
    if not articles:
        return []

    # Build combined text (title + snippet for each article)
    text_parts = []
    for i, a in enumerate(articles[:20]):
        text_parts.append(
            f"[{i + 1}] {a.get('title', '')} | "
            f"URL: {a.get('url', '')} | "
            f"Date: {a.get('published', '')} | "
            f"{a.get('snippet', '')[:200]}"
        )
    combined = "\n".join(text_parts)
    # Gemini can handle larger context; truncate for Cerebras fallback
    truncated = combined[:5000]
    prompt = NEWS_EXTRACTION_PROMPT + truncated

    raw = ""

    def _is_rate_limited(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "429" in msg
            or "rate limit" in msg
            or "ratelimit" in msg
            or "too many requests" in msg
            or "requests per minute" in msg
            or "tokens per day" in msg
        )

    def _call_cerebras_fallback(litellm_module):
        if not CEREBRAS_API_KEY:
            logger.error(
                "[NewsScout] Gemini fallback requested but CEREBRAS_API_KEY missing"
            )
            return ""
        short_prompt = NEWS_EXTRACTION_PROMPT + combined[:2000]
        resp = litellm_module.completion(
            model=f"openai/{CEREBRAS_MODEL}",
            api_key=CEREBRAS_API_KEY,
            base_url=CEREBRAS_BASE_URL,
            messages=[{"role": "user", "content": short_prompt}],
            max_tokens=800,
            temperature=0.0,
        )
        return resp.choices[0].message.content.strip()

    try:
        import litellm

        if GEMINI_API_KEY:
            try:
                resp = litellm.completion(
                    model=GEMINI_CEO_MODEL,
                    api_key=GEMINI_API_KEY,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1500,
                    temperature=0.0,
                )
                raw = resp.choices[0].message.content.strip()
            except Exception as gem_exc:
                if _is_rate_limited(gem_exc):
                    logger.warning(
                        f"[NewsScout] Gemini rate-limited (429/quota): {gem_exc} | falling back to Cerebras"
                    )
                    try:
                        raw = _call_cerebras_fallback(litellm)
                    except Exception as fb_exc:
                        logger.error(
                            f"[NewsScout] Cerebras fallback failed after Gemini rate-limit: {fb_exc}"
                        )
                        return []
                else:
                    raise
        elif CEREBRAS_API_KEY:
            raw = _call_cerebras_fallback(litellm)
        else:
            return []
    except Exception as exc:
        logger.warning(f"[NewsScout] AI analysis error: {exc}")
        return []

    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`")
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logger.debug(f"[NewsScout] JSON parse failed: {raw[:100]}")
    return []


# ── Normalization ─────────────────────────────────────────────────────────────


def _normalize_article(raw: dict, market: str) -> dict | None:
    headline = (raw.get("headline") or "").strip()
    url = (raw.get("url") or "").strip()

    if not headline and not url:
        return None

    cid = ScoutMemory.cid_news(url or headline)
    signal = raw.get("signal_type") or "other"

    return {
        "cid": cid,
        "source": "news",
        "market": raw.get("market") or market,
        "headline": headline,
        "published_date": raw.get("published_date") or "",
        "signal_type": signal,
        "projects_mentioned": raw.get("projects_mentioned") or [],
        "developers_mentioned": raw.get("developers_mentioned") or [],
        "price_signal": raw.get("price_signal") or "",
        "key_insight": raw.get("key_insight") or "",
        "source_url": url,
        "scraped_at": datetime.now().isoformat(),
    }


# ── News Scout ────────────────────────────────────────────────────────────────


class NewsScout:
    """
    Scrapes property news from multiple sources.
    Extracts project launches, price signals, and regulatory news.
    """

    def __init__(self, market: str, memory: ScoutMemory | None = None):
        self.market = market
        self.memory = memory or ScoutMemory(market)
        self.queries = NEWS_QUERIES.get(market, NEWS_QUERIES["Yelahanka"])
        self.session = requests.Session()
        self.session.headers.update(SCRAPE_HEADERS)

    def scout(self, days_back: int = 60) -> list[dict]:
        """
        Fetch articles from all sources for all market queries.
        Returns all news findings with is_new flag.
        """
        all_raw_articles: list[dict] = []

        for query in self.queries:
            # Source 1: Google News RSS
            articles = _fetch_google_news_rss(query, days_back=days_back)
            all_raw_articles.extend(articles)
            time.sleep(0.5)

            # Source 2: ET Realty
            et_articles = _fetch_et_realty(query, self.session)
            all_raw_articles.extend(et_articles)
            time.sleep(0.5)

        # Deduplicate raw articles by URL before AI analysis
        seen_urls: set[str] = set()
        unique_raw: list[dict] = []
        for a in all_raw_articles:
            u = a.get("url", a.get("title", ""))
            if u and u not in seen_urls:
                seen_urls.add(u)
                unique_raw.append(a)

        logger.info(
            f"[NewsScout] {self.market}: "
            f"{len(all_raw_articles)} raw articles → "
            f"{len(unique_raw)} unique for AI analysis"
        )

        # AI analysis: extract structured intelligence
        analyzed = _ai_analyze_articles(unique_raw, self.market)
        findings = [_normalize_article(a, self.market) for a in analyzed]
        findings = [f for f in findings if f is not None]

        new, known = self.memory.mark_all(findings, source="news")
        all_findings = new + known

        new_total = sum(1 for f in all_findings if f.get("is_new"))
        logger.info(
            f"[NewsScout] {self.market}: "
            f"{len(findings)} articles analyzed | {new_total} new signals"
        )
        return all_findings


# ── Standalone runner ─────────────────────────────────────────────────────────


def scout_news(market: str, days_back: int = 60) -> list[dict]:
    memory = ScoutMemory(market)
    scout = NewsScout(market, memory)
    findings = scout.scout(days_back=days_back)

    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "outputs",
        market.lower().replace(" ", "_"),
    )
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = os.path.join(output_dir, f"news_scout_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, default=str)

    new_total = sum(1 for f in findings if f.get("is_new"))
    print(f"\n{'=' * 55}")
    print(f"NEWS SCOUT — {market.upper()}")
    print(f"{'=' * 55}")
    print(f"Total articles  : {len(findings)}")
    print(f"New signals     : {new_total}")
    print(f"Output          : {out_path}")

    for signal_type in ("new_launch", "price_change", "regulatory"):
        matches = [f for f in findings if f.get("signal_type") == signal_type]
        if matches:
            print(f"\n  {signal_type.upper()} ({len(matches)}):")
            for f in matches[:3]:
                print(f"    • {f.get('headline', '?')[:70]}")
                if f.get("key_insight"):
                    print(f"      → {f['key_insight'][:80]}")
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="News Scout — property news intelligence"
    )
    parser.add_argument(
        "--market", default="Yelahanka", choices=["Yelahanka", "Devanahalli", "Hebbal"]
    )
    parser.add_argument(
        "--days",
        type=int,
        default=60,
        help="How many days back to search (default: 60)",
    )
    args = parser.parse_args()
    logger.add("logs/news_scout.log", rotation="10 MB")
    scout_news(args.market, days_back=args.days)
