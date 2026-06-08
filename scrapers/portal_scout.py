"""
RE_OS — Portal Scout
─────────────────────
Scouts 7 property portals for active project listings and unit-level data.
Sources: 99acres (sale+rent), Housing.com, MagicBricks, PropTiger,
         NoBroker, SquareYards

Fetch strategy (tiered — each level falls back to the next on failure):
  1a. Scrapling Fetcher (TLS fingerprint spoofing) — bot-protected portals
      that block plain requests: 99acres, MagicBricks, PropTiger, SquareYards
  1b. Scrapling DynamicFetcher (stealth Playwright) — JS SPAs:
      Housing.com, NoBroker
  2.  Raw Playwright — fallback if Scrapling unavailable or fails
  3.  requests + BeautifulSoup — last resort
  4.  Cerebras 8b AI extraction: cleaned text → structured JSON
      (8192 token cap → truncate to 2500 chars before AI call)
  5.  ScoutMemory dedup: only new projects/listings are flagged is_new=True

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
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from loguru import logger

try:
    from scrapling.fetchers import Fetcher, DynamicFetcher
    _SCRAPLING_OK = True
except Exception:
    _SCRAPLING_OK = False

from config.settings import (
    CEREBRAS_API_KEY,
    CEREBRAS_BASE_URL,
    CEREBRAS_MODEL,
    GEMINI_API_KEY,
    GEMINI_CEO_MODEL,
    PORTAL_SCOUT_MIN_LISTINGS_CANARY,
)
from config.metrics import scraper_runs_total
from config.locality_aliases import get_locality_aliases
from scrapers.scout_memory import ScoutMemory

# Counter for filtered-out mis-geocoded listings (exposed for metrics / tests)
scraper_locality_filtered = 0


# ── Market → portal URL map ───────────────────────────────────────────────────

PORTAL_URLS: dict[str, dict[str, str]] = {
    "Yelahanka": {
        "99acres_sale": "https://www.99acres.com/property-for-sale-in-yelahanka-bangalore-ffid",
        "99acres_rent": "https://www.99acres.com/property-for-rent-in-yelahanka-bangalore-ffid",
        "housing_sale": "https://housing.com/in/buy/searches/bangalore--yelahanka",
        "magicbricks": "https://www.magicbricks.com/property-for-sale/residential-real-estate?proptype=Multistorey-Apartment,Builder-Floor-Apartment&cityName=Bangalore&Area=Yelahanka",
        "proptiger": "https://www.proptiger.com/bangalore/north-bangalore/yelahanka/property-sale",
        "nobroker": "https://www.nobroker.in/property/residential/sale/bangalore/Yelahanka",
        "squareyards": "https://www.squareyards.com/sale/property-for-sale-in-yelahanka-bangalore",
    },
    "Devanahalli": {
        "99acres_sale": "https://www.99acres.com/property-for-sale-in-devanahalli-bangalore-ffid",
        "99acres_rent": "https://www.99acres.com/property-for-rent-in-devanahalli-bangalore-ffid",
        "housing_sale": "https://housing.com/in/buy/searches/bangalore--devanahalli",
        "magicbricks": "https://www.magicbricks.com/property-for-sale/residential-real-estate?proptype=Multistorey-Apartment,Builder-Floor-Apartment&cityName=Bangalore&Area=Devanahalli",
        "proptiger": "https://www.proptiger.com/bangalore/devanahalli/property-sale",
        "nobroker": "https://www.nobroker.in/property/residential/sale/bangalore/Devanahalli",
        "squareyards": "https://www.squareyards.com/sale/property-for-sale-in-devanahalli-bangalore",
    },
    "Hebbal": {
        "99acres_sale": "https://www.99acres.com/property-for-sale-in-hebbal-bangalore-ffid",
        "99acres_rent": "https://www.99acres.com/property-for-rent-in-hebbal-bangalore-ffid",
        "housing_sale": "https://housing.com/in/buy/searches/bangalore--hebbal",
        "magicbricks": "https://www.magicbricks.com/property-for-sale/residential-real-estate?proptype=Multistorey-Apartment,Builder-Floor-Apartment&cityName=Bangalore&Area=Hebbal",
        "proptiger": "https://www.proptiger.com/bangalore/hebbal/property-sale",
        "nobroker": "https://www.nobroker.in/property/residential/sale/bangalore/Hebbal",
        "squareyards": "https://www.squareyards.com/sale/property-for-sale-in-hebbal-bangalore",
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

_USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

_UA_BAN_ROTATION = 0


def _get_rotated_headers(source_key: str = "") -> dict[str, str]:
    import random
    return {
        "User-Agent": random.choice(_USER_AGENT_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    }

# Minimal stealth patches injected before page load — removes the most-checked
# bot signals without requiring playwright-stealth or any extra dependency.
_STEALTH_SCRIPT = """\
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-IN', 'en-US', 'en']});
window.chrome = {runtime: {}};
"""

# Sources that require Playwright (heavy JS SPAs with bot detection workarounds)
PLAYWRIGHT_SOURCES = {"housing_sale", "nobroker"}

# Scrapling routing — checked before Playwright/requests fallback.
# HTTP: TLS fingerprint spoofing via curl_cffi — no browser needed.
_SCRAPLING_HTTP = {"99acres_sale", "99acres_rent", "magicbricks", "proptiger", "squareyards"}
# Dynamic: stealth Playwright — reuses PLAYWRIGHT_BROWSERS_PATH, no extra download.
_SCRAPLING_DYNAMIC = {"housing_sale", "nobroker"}

# Portal-specific CSS selectors for listing card extraction.
# Tried in order — first selector returning ≥3 cards wins. Wrong selectors are
# harmless (no match → empty → fallback to full BeautifulSoup clean).
# These target the repeating card containers, not individual fields — AI reads
# the card text and infers structure, which is more resilient than field selectors.
_PORTAL_CARD_SELECTORS: dict[str, list[str]] = {
    "99acres_sale":  ["[id^='srp_tuple_']", ".card-container", "[class*='srpList'] li"],
    "99acres_rent":  ["[id^='srp_tuple_']", ".card-container", "[class*='srpList'] li"],
    "magicbricks":   ["[class*='projectCard']", ".mb-srp__list__items li", "[class*='PropertyList'] li"],
    "housing_sale":  ["[data-q='property-card']", "[class*='listingCard']", "[class*='listing-card']"],
    "proptiger":     ["[class*='projectTile']", "[class*='newCard']", "[class*='tilesList'] li"],
    "nobroker":      ["[class*='propertyCard']", ".resultTile", "[class*='tuple']"],
    "squareyards":   ["[class*='property-card']", "[class*='listing-card']", "[class*='projectCard']"],
}

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
    Cerebras budget: 8192 total - 1000 response - ~150 prompt ≈ 7042 input tokens
    (~28k chars). 6000-char cap is safe and 2.4× more signal than the old 2500 limit.
    Falls back to Gemini Flash if Cerebras unavailable.
    """
    truncated = text[:6000]
    prompt = EXTRACTION_PROMPT + truncated

    raw_response = ""
    import litellm

    cerebras_error = None
    if CEREBRAS_API_KEY:
        try:
            resp = litellm.completion(
                model=f"openai/{CEREBRAS_MODEL}",
                api_key=CEREBRAS_API_KEY,
                base_url=CEREBRAS_BASE_URL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.0,
            )
            content = resp.choices[0].message.content
            raw_response = content.strip() if content else ""
            if not raw_response:
                logger.warning("[PortalScout] Cerebras returned empty content")
        except Exception as exc:
            cerebras_error = exc
            logger.warning(f"[PortalScout] Cerebras extraction error ({type(exc).__name__}): {exc}")

    if not raw_response and GEMINI_API_KEY:
        try:
            resp = litellm.completion(
                model=GEMINI_CEO_MODEL,
                api_key=GEMINI_API_KEY,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.0,
            )
            content = resp.choices[0].message.content
            raw_response = content.strip() if content else ""
            if raw_response and cerebras_error:
                logger.info(
                    "[PortalScout] Gemini fallback succeeded after Cerebras error "
                    f"({type(cerebras_error).__name__})"
                )
            elif not raw_response:
                logger.warning("[PortalScout] Gemini returned empty content")
        except Exception as exc:
            logger.warning(f"[PortalScout] Gemini extraction error ({type(exc).__name__}): {exc}")

    if not raw_response:
        if not CEREBRAS_API_KEY and not GEMINI_API_KEY:
            logger.warning("[PortalScout] No AI key available for extraction")
        else:
            logger.warning("[PortalScout] All extraction paths returned empty — no listings parsed")
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
    for tag in soup(
        [
            "script",
            "style",
            "nav",
            "header",
            "footer",
            "aside",
            "noscript",
            "iframe",
            "form",
        ]
    ):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s{3,}", "\n", text)
    return text


def _scrapling_targeted_text(page, src: str, max_cards: int = 30) -> str:
    """
    Use Scrapling's native CSS to extract listing card text — zero AI cost,
    runs before BeautifulSoup. Each card becomes one line of pipe-separated
    field values. Returns empty string if no selector matches ≥3 cards,
    so the caller falls back to the full HTML clean path gracefully.

    Why this matters: full-page BeautifulSoup produces ~10-20k chars of mixed
    nav/footer/content. We then truncate to 6000 and hand it to AI. With
    targeted CSS we feed AI 30 × 400-char listing snippets = pure signal,
    no noise. Extraction accuracy goes up, token waste goes down.
    """
    for selector in _PORTAL_CARD_SELECTORS.get(src, []):
        try:
            elements = page.css(selector)
            if not elements:
                continue
            snippets: list[str] = []
            for el in elements[:max_cards]:
                parts = el.css("::text").getall()
                card = " | ".join(p.strip() for p in parts if p.strip() and len(p.strip()) > 1)
                if len(card) > 30:
                    snippets.append(card[:600])
            if len(snippets) >= 3:
                logger.debug(
                    f"[PortalScout][Scrapling CSS][{src}] selector '{selector}' → "
                    f"{len(snippets)} cards"
                )
                return "\n".join(snippets)
        except Exception:
            continue
    return ""


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


def _locality_matches_market(locality: str, market: str) -> bool:
    clean_loc = locality.strip().lower() if locality else ""
    if not clean_loc or clean_loc == market.strip().lower():
        return True
    loc_lower = locality.lower()
    aliases = get_locality_aliases(market)
    for alias in aliases:
        if alias in loc_lower:
            return True
    return False


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
    bhk_configs = (
        [b.strip() for b in bhk_raw.split(",") if b.strip()] if bhk_raw else []
    )

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
        # Shared browser instance — lazy-init on first Playwright fallback call,
        # kept alive for the duration of scout() to avoid repeated browser spawns.
        self._pw_ctx = None
        self._pw_browser = None

    def scout(self, sources: list[str] | None = None) -> list[dict]:
        """
        Run all portals (or specified subset). Returns all findings with is_new flag.
        sources: list of source keys from PORTAL_URLS, e.g. ["99acres_sale", "housing_sale"]
        """
        all_findings: list[dict] = []
        all_sources = list(self.urls.keys())
        targets = sources if sources else all_sources

        try:
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
        finally:
            self._close_playwright()

        new_total = sum(1 for f in all_findings if f.get("is_new"))
        logger.info(
            f"[PortalScout] {self.market}: "
            f"{len(all_findings)} total | {new_total} new discoveries"
        )
        return all_findings

    def _close_playwright(self) -> None:
        """Tear down the shared browser instance if it was started."""
        if self._pw_browser:
            try:
                self._pw_browser.close()
            except Exception:
                pass
            self._pw_browser = None
        if self._pw_ctx:
            try:
                self._pw_ctx.stop()
            except Exception:
                pass
            self._pw_ctx = None

    def _scout_source(self, src: str) -> list[dict]:
        url = self.urls[src]
        text = ""

        if _SCRAPLING_OK:
            if src in _SCRAPLING_DYNAMIC:
                text = self._scrapling_dynamic_fetch(url, src)
            elif src in _SCRAPLING_HTTP:
                text = self._scrapling_http_fetch(url, src)

        if not text:
            # Fallback: existing Playwright / requests path
            if src in PLAYWRIGHT_SOURCES:
                logger.info(f"[PortalScout][{src}] Scrapling unavailable or empty → Playwright fallback")
                text = self._playwright_fetch(url)
                if not text:
                    logger.info(f"[PortalScout][{src}] Playwright empty → requests fallback")
                    text = self._requests_fetch(url)
            else:
                logger.info(f"[PortalScout][{src}] Scrapling unavailable or empty → requests fallback")
                text = self._requests_fetch(url)

        if not text:
            logger.debug(f"[PortalScout][{src}] No content retrieved")
            return []

        raw_items = _ai_extract(text, self.market)
        results = []
        for r in raw_items:
            item = _normalize(r, src, self.market, url)
            if item is None:
                continue
            locality = str(item.get("locality") or "").strip()
            if locality and not _locality_matches_market(locality, self.market):
                global scraper_locality_filtered
                scraper_locality_filtered += 1
                logger.warning(f"[PortalScout][{src}] Filtered out mis-geocoded listing: locality={locality!r}, market={self.market}, project={item.get('project_name', '?')[:40]}")
                continue
            results.append(item)
        return results

    # ── Scrapling fetchers ────────────────────────────────────────────────────

    def _scrapling_http_fetch(self, url: str, src: str) -> str:
        """TLS fingerprint spoofing via curl_cffi — no browser, bypasses bot headers."""
        try:
            page = Fetcher.get(url, stealthy_headers=True, timeout=30)
            if page is None:
                return ""
            html = getattr(page, "body", None) or ""
            if len(html) < 500:
                logger.debug(f"[PortalScout][Scrapling HTTP][{src}] {len(html)} chars — bot-wall, skipping")
                return ""
            # CSS-targeted extraction first — pure listing signal, no nav/footer noise
            targeted = _scrapling_targeted_text(page, src)
            if targeted:
                return targeted
            # Fallback: full BeautifulSoup clean
            result = _clean_html(html)
            logger.debug(f"[PortalScout][Scrapling HTTP][{src}] full clean: {len(result)} chars")
            return result
        except Exception as exc:
            logger.debug(f"[PortalScout][Scrapling HTTP][{src}] {exc}")
        return ""

    def _scrapling_dynamic_fetch(self, url: str, src: str) -> str:
        """Stealth Playwright — patches webdriver flag, reuses existing Chromium."""
        try:
            page = DynamicFetcher.fetch(
                url, headless=True, network_idle=True, disable_resources=True, timeout=30000
            )
            if page is None:
                return ""
            html = getattr(page, "body", None) or ""
            if len(html) < 500:
                logger.debug(f"[PortalScout][Scrapling Dynamic][{src}] {len(html)} chars — bot-wall, skipping")
                return ""
            # CSS-targeted extraction first — pure listing signal, no nav/footer noise
            targeted = _scrapling_targeted_text(page, src)
            if targeted:
                return targeted
            # Fallback: full BeautifulSoup clean
            result = _clean_html(html)
            logger.debug(f"[PortalScout][Scrapling Dynamic][{src}] full clean: {len(result)} chars")
            return result
        except Exception as exc:
            logger.debug(f"[PortalScout][Scrapling Dynamic][{src}] {exc}")
        return ""

    # ── Legacy fetchers (fallback) ────────────────────────────────────────────

    def _requests_fetch(self, url: str) -> str:
        try:
            source_key = next(
                (k for k, v in self.urls.items() if v == url), None
            )
            headers = _get_rotated_headers(source_key or "")
            resp = self.session.get(url, headers=headers, timeout=25)
            time.sleep(1)
            if resp.status_code == 200:
                return _clean_html(resp.text)
            logger.debug(f"[PortalScout] HTTP {resp.status_code} for {url}")
        except requests.exceptions.RequestException as exc:
            logger.debug(f"[PortalScout] Request error: {exc}")
        return ""

    def _playwright_fetch(self, url: str) -> str:
        """
        Last-resort Playwright fallback. Reuses a single browser instance across
        all calls in a scout() run (session pool). Each URL gets a fresh context
        so cookies/state don't leak between portals. Stealth JS patches applied
        before page load to remove the most-checked bot signals.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ""
        try:
            if self._pw_browser is None:
                self._pw_ctx = sync_playwright().start()
                self._pw_browser = self._pw_ctx.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
                )
            ctx = self._pw_browser.new_context(
                user_agent=SCRAPE_HEADERS["User-Agent"],
                locale="en-IN",
            )
            page = ctx.new_page()
            page.add_init_script(_STEALTH_SCRIPT)
            page.set_default_timeout(30_000)
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3000)
            html = page.content()
            ctx.close()
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
        "outputs",
        market.lower().replace(" ", "_"),
    )
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = os.path.join(output_dir, f"portal_scout_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, default=str)

    new_total = sum(1 for f in findings if f.get("is_new"))
    try:
        from utils.db import get_engine
        from utils.discord_notifier import send_price_alert
        from sqlalchemy import text
        with get_engine().connect() as conn:
            prev = conn.execute(text("""
                SELECT avg_psf_sale FROM market_snapshots
                WHERE micro_market_id = (SELECT id FROM micro_markets WHERE name ILIKE :m)
                ORDER BY snapshot_date DESC LIMIT 1
            """), {"m": f"%{market}%"}).fetchone()
            curr = conn.execute(text("""
                SELECT ROUND(AVG(price_psf)) FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.name ILIKE :m AND price_psf > 1000 AND price_psf < 50000
            """), {"m": f"%{market}%"}).fetchone()
        if prev and prev[0] and curr and curr[0]:
            old_psf, new_psf = float(prev[0]), float(curr[0])
            if abs((new_psf - old_psf) / max(old_psf, 1)) >= 0.05:
                send_price_alert(market, old_psf, new_psf)
    except Exception as _alert_err:
        logger.warning(f"[PortalScout] Price alert failed for {market}: {_alert_err}")

    # Canary: alert if listing count drops below threshold (silent failure detection)
    # Only fire when all 7 sources were attempted (not a partial/source-filtered run)
    # Skip if threshold is 0 or negative (misconfiguration guard)
    if sources is None and PORTAL_SCOUT_MIN_LISTINGS_CANARY > 0 and len(findings) < PORTAL_SCOUT_MIN_LISTINGS_CANARY:
        try:
            from utils.discord_notifier import send_scraper_alert
            send_scraper_alert(market, "portal_scout", "ZERO_LISTINGS_CANARY", record_count=len(findings))
        except Exception as _canary_err:
            logger.warning(f"[PortalScout] Canary alert failed for {market}: {_canary_err}")

    scraper_runs_total.labels(source="portal", market=market, status="success").inc()
    print(f"\n{'=' * 55}")
    print(f"PORTAL SCOUT — {market.upper()}")
    print(f"{'=' * 55}")
    print(f"Total findings : {len(findings)}")
    print(f"New (unseen)   : {new_total}")
    print(f"Memory stats   : {memory.stats()}")
    print(f"Output         : {out_path}")
    if findings:
        new_items = [f for f in findings if f.get("is_new")][:5]
        if new_items:
            print("\nNew discoveries (top 5):")
            for f in new_items:
                print(
                    f"  [{f['source']:<14}] "
                    f"{f.get('developer', '?')[:20]:<22} | "
                    f"{f.get('project_name', '?')[:30]:<32} | "
                    f"{f.get('price_display', '?')}"
                )
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Portal Scout — multi-source property listings"
    )
    parser.add_argument(
        "--market", default="Yelahanka", choices=["Yelahanka", "Devanahalli", "Hebbal"]
    )
    parser.add_argument(
        "--source", default="", help="Comma-separated source keys to run (default: all)"
    )
    args = parser.parse_args()
    logger.add("logs/portal_scout.log", rotation="10 MB")
    sources = [s.strip() for s in args.source.split(",") if s.strip()] or None
    scout_market(args.market, sources=sources)
