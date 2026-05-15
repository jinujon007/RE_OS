"""
RE_OS — Portal Scout
─────────────────────
Scouts 7 property portals for active project listings and unit-level data.
Sources: 99acres (sale+rent), Housing.com, MagicBricks, PropTiger,
         NoBroker, SquareYards

Strategy:
  1. requests + BeautifulSoup (fast, works when sites render server-side)
  2. Playwright fallback for JS-heavy SPAs
  3. Cerebras 8b AI extraction: raw HTML text → structured JSON
     (8192 token cap → truncate to 2500 chars before AI call)
  4. ScoutMemory dedup: only new projects/listings are flagged is_new=True

Model: Cerebras llama3.1-8b — fastest structured extraction, handles short prompts.
       Falls back to Gemini if Cerebras unavailable.

Run standalone:
  python scrapers/portal_scout.py --market Yelahanka
  python scrapers/portal_scout.py --market Yelahanka --source 99acres_sale
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from loguru import logger

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import (
    CEREBRAS_API_KEY, CEREBRAS_BASE_URL, CEREBRAS_MODEL,
    GEMINI_API_KEY, GEMINI_CEO_MODEL,
)
from scrapers.scout_memory import ScoutMemory


# ── Market → portal URL map ───────────────────────────────────────────────────

PORTAL_URLS: dict[str, dict[str, str]] = {
    "Yelahanka": {
        "99acres_sale":  "https://www.99acres.com/property-for-sale-in-yelahanka-bangalore-ffid",
        "99acres_rent":  "https://www.99acres.com/property-for-rent-in-yelahanka-bangalore-ffid",
        "housing_sale":  "https://housing.com/in/buy/searches/bangalore--yelahanka",
        "magicbricks":   "https://www.magicbricks.com/property-for-sale/residential-real-estate?proptype=Multistorey-Apartment,Builder-Floor-Apartment&cityName=Bangalore&Area=Yelahanka",
        "proptiger":     "https://www.proptiger.com/bangalore/north-bangalore/yelahanka/property-sale",
        "nobroker":      "https://www.nobroker.in/property/residential/sale/bangalore/Yelahanka",
        "squareyards":   "https://www.squareyards.com/sale/property-for-sale-in-yelahanka-bangalore",
    },
    "Devanahalli": {
        "99acres_sale":  "https://www.99acres.com/property-for-sale-in-devanahalli-bangalore-ffid",
        "99acres_rent":  "https://www.99acres.com/property-for-rent-in-devanahalli-bangalore-ffid",
        "housing_sale":  "https://housing.com/in/buy/searches/bangalore--devanahalli",
        "magicbricks":   "https://www.magicbricks.com/property-for-sale/residential-real-estate?proptype=Multistorey-Apartment,Builder-Floor-Apartment&cityName=Bangalore&Area=Devanahalli",
        "proptiger":     "https://www.proptiger.com/bangalore/devanahalli/property-sale",
        "nobroker":      "https://www.nobroker.in/property/residential/sale/bangalore/Devanahalli",
        "squareyards":   "https://www.squareyards.com/sale/property-for-sale-in-devanahalli-bangalore",
    },
    "Hebbal": {
        "99acres_sale":  "https://www.99acres.com/property-for-sale-in-hebbal-bangalore-ffid",
        "99acres_rent":  "https://www.99acres.com/property-for-rent-in-hebbal-bangalore-ffid",
        "housing_sale":  "https://housing.com/in/buy/searches/bangalore--hebbal",
        "magicbricks":   "https://www.magicbricks.com/property-for-sale/residential-real-estate?proptype=Multistorey-Apartment,Builder-Floor-Apartment&cityName=Bangalore&Area=Hebbal",
        "proptiger":     "https://www.proptiger.com/bangalore/hebbal/property-sale",
        "nobroker":      "https://www.nobroker.in/property/residential/sale/bangalore/Hebbal",
        "squareyards":   "https://www.squareyards.com/sale/property-for-sale-in-hebbal-bangalore",
    },
}

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

# Sources that require Playwright (heavy JS SPAs with bot detection workarounds)
PLAYWRIGHT_SOURCES = {"housing_sale", "nobroker"}

EXTRACTION_PROMPT = """\
You are extracting real estate listings data from raw webpage text.
Return ONLY a JSON array. Each object must use exactly these keys:
  project_name   (string: project or building name)
  developer      (string: builder/promoter name)
  bhk            (string: e.g. "2 BHK, 3 BHK" or "3 BHK")
  price_display  (string: e.g. "₹85 L", "₹1.2 Cr onwards", "₹6,500/sqft")
  area_sqft      (string: e.g. "1200" or "1100-1650")
  locality       (string: neighbourhood/area name)
  status         (string: one of New Launch | Under Construction | Ready to Move | Completed)
  rera_number    (string or null)
  source_url     (string or null: page URL if visible in text)

Rules:
- Only include listings where you can extract at least project_name AND price_display.
- If a field is missing, use null.
- Return ONLY valid JSON array, no explanation, no markdown fences.

WEBPAGE TEXT:
"""


# ── AI extraction ─────────────────────────────────────────────────────────────

def _ai_extract(text: str, market: str) -> list[dict]:
    """
    Send truncated page text to Cerebras for structured extraction.
    Cerebras 8192 token cap: truncate to 2500 chars to leave room for response.
    Falls back to Gemini Flash if Cerebras unavailable.
    """
    truncated = text[:2500]
    prompt = EXTRACTION_PROMPT + truncated

    raw_response = ""
    try:
        import litellm
        if CEREBRAS_API_KEY:
            resp = litellm.completion(
                model=f"openai/{CEREBRAS_MODEL}",
                api_key=CEREBRAS_API_KEY,
                base_url=CEREBRAS_BASE_URL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.0,
            )
            raw_response = resp.choices[0].message.content.strip()
        elif GEMINI_API_KEY:
            resp = litellm.completion(
                model=GEMINI_CEO_MODEL,
                api_key=GEMINI_API_KEY,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.0,
            )
            raw_response = resp.choices[0].message.content.strip()
        else:
            logger.warning("[PortalScout] No AI key available for extraction")
            return []
    except Exception as exc:
        logger.warning(f"[PortalScout] AI extraction error: {exc}")
        return []

    return _parse_json_response(raw_response)


def _parse_json_response(raw: str) -> list[dict]:
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
    logger.debug(f"[PortalScout] JSON parse failed: {raw[:100]}")
    return []


# ── HTML cleaning ─────────────────────────────────────────────────────────────

def _clean_html(html: str) -> str:
    """Strip boilerplate tags → clean dense text for AI extraction."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer",
                     "aside", "noscript", "iframe", "form"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s{3,}", "\n", text)
    return text


# ── Normalization ─────────────────────────────────────────────────────────────

def _parse_price(s: str | None) -> float:
    if not s:
        return 0.0
    clean = re.sub(r"[₹,\s]", "", str(s)).upper()
    m = re.search(r"[\d.]+", clean)
    if not m:
        return 0.0
    num = float(m.group())
    if "CR" in clean:
        return num * 10_000_000
    if any(x in clean for x in ("L", "LAC", "LAKH")):
        return num * 100_000
    if "K" in clean:
        return num * 1_000
    return num


def _normalize(raw: dict, source: str, market: str, page_url: str = "") -> dict | None:
    name = (raw.get("project_name") or "").strip()
    developer = (raw.get("developer") or "").strip()
    locality = (raw.get("locality") or market).strip()

    if not name:
        return None

    rera = (raw.get("rera_number") or "").strip()
    url = (raw.get("source_url") or page_url or "").strip()
    if rera in ("null", "None", ""):
        rera = ""

    # Canonical ID hierarchy: RERA number > project identity > listing URL
    if rera:
        cid = ScoutMemory.cid_rera(rera)
    elif name and developer:
        cid = ScoutMemory.cid_project(developer, name, locality)
    elif url:
        cid = ScoutMemory.cid_listing(source, url)
    else:
        return None

    price_str = raw.get("price_display") or ""
    price_val = _parse_price(price_str)

    bhk_raw = raw.get("bhk") or ""
    bhk_configs = [b.strip() for b in bhk_raw.split(",") if b.strip()] if bhk_raw else []

    status = raw.get("status") or "Unknown"

    return {
        "cid": cid,
        "source": source,
        "market": market,
        "project_name": name,
        "developer": developer,
        "bhk_configs": bhk_configs,
        "price_display": price_str,
        "price_min": price_val,
        "price_max": price_val,
        "area_sqft": str(raw.get("area_sqft") or ""),
        "locality": locality,
        "launch_status": status,
        "is_new_launch": "new launch" in status.lower(),
        "rera_number": rera,
        "source_url": url,
        "scraped_at": datetime.now().isoformat(),
    }


# ── Portal Scout ──────────────────────────────────────────────────────────────

class PortalScout:
    """
    Scouts 7 property portals for Bengaluru micro-market listings.
    Deduplicates via ScoutMemory. New discoveries flagged with is_new=True.
    """

    def __init__(self, market: str, memory: ScoutMemory | None = None):
        self.market = market
        self.memory = memory or ScoutMemory(market)
        self.urls = PORTAL_URLS.get(market, {})
        self.session = requests.Session()
        self.session.headers.update(SCRAPE_HEADERS)

    def scout(self, sources: list[str] | None = None) -> list[dict]:
        """
        Run all portals (or specified subset). Returns all findings with is_new flag.
        sources: list of source keys from PORTAL_URLS, e.g. ["99acres_sale", "housing_sale"]
        """
        all_findings: list[dict] = []
        all_sources = list(self.urls.keys())
        targets = sources if sources else all_sources

        for src in targets:
            if src not in self.urls:
                logger.warning(f"[PortalScout] Unknown source key: {src}")
                continue
            try:
                findings = self._scout_source(src)
                new, known = self.memory.mark_all(findings, source=src)
                all_findings.extend(new + known)
                logger.info(
                    f"[PortalScout][{src}] "
                    f"{len(findings)} found | {len(new)} new | {len(known)} known"
                )
                time.sleep(0.5)
            except Exception as exc:
                logger.warning(f"[PortalScout][{src}] Failed: {exc}")

        new_total = sum(1 for f in all_findings if f.get("is_new"))
        logger.info(
            f"[PortalScout] {self.market}: "
            f"{len(all_findings)} total | {new_total} new discoveries"
        )
        return all_findings

    def _scout_source(self, src: str) -> list[dict]:
        url = self.urls[src]
        if src in PLAYWRIGHT_SOURCES:
            text = self._playwright_fetch(url)
            if not text:
                text = self._requests_fetch(url)
        else:
            text = self._requests_fetch(url)

        if not text:
            logger.debug(f"[PortalScout][{src}] No content retrieved")
            return []

        raw_items = _ai_extract(text, self.market)
        results = [_normalize(r, src, self.market, url) for r in raw_items]
        return [r for r in results if r is not None]

    def _requests_fetch(self, url: str) -> str:
        try:
            resp = self.session.get(url, timeout=25)
            time.sleep(1)
            if resp.status_code == 200:
                return _clean_html(resp.text)
            logger.debug(f"[PortalScout] HTTP {resp.status_code} for {url}")
        except requests.exceptions.RequestException as exc:
            logger.debug(f"[PortalScout] Request error: {exc}")
        return ""

    def _playwright_fetch(self, url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
                )
                ctx = browser.new_context(
                    user_agent=SCRAPE_HEADERS["User-Agent"], locale="en-IN"
                )
                page = ctx.new_page()
                page.set_default_timeout(30_000)
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()
                return _clean_html(html)
        except Exception as exc:
            logger.debug(f"[PortalScout][Playwright] Failed for {url}: {exc}")
            return ""


# ── Standalone runner ─────────────────────────────────────────────────────────

def scout_market(market: str, sources: list[str] | None = None) -> list[dict]:
    memory = ScoutMemory(market)
    scout = PortalScout(market, memory)
    findings = scout.scout(sources=sources)

    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "outputs", market.lower().replace(" ", "_")
    )
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = os.path.join(output_dir, f"portal_scout_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, default=str)

    new_total = sum(1 for f in findings if f.get("is_new"))
    print(f"\n{'='*55}")
    print(f"PORTAL SCOUT — {market.upper()}")
    print(f"{'='*55}")
    print(f"Total findings : {len(findings)}")
    print(f"New (unseen)   : {new_total}")
    print(f"Memory stats   : {memory.stats()}")
    print(f"Output         : {out_path}")
    if findings:
        new_items = [f for f in findings if f.get("is_new")][:5]
        if new_items:
            print(f"\nNew discoveries (top 5):")
            for f in new_items:
                print(
                    f"  [{f['source']:<14}] "
                    f"{f.get('developer','?')[:20]:<22} | "
                    f"{f.get('project_name','?')[:30]:<32} | "
                    f"{f.get('price_display','?')}"
                )
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Portal Scout — multi-source property listings")
    parser.add_argument("--market", default="Yelahanka",
                        choices=["Yelahanka", "Devanahalli", "Hebbal"])
    parser.add_argument("--source", default="",
                        help="Comma-separated source keys to run (default: all)")
    args = parser.parse_args()
    logger.add("logs/portal_scout.log", rotation="10 MB")
    sources = [s.strip() for s in args.source.split(",") if s.strip()] or None
    scout_market(args.market, sources=sources)
