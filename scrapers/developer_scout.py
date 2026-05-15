"""
RE_OS — Developer Scout
────────────────────────
Goes directly to developer websites — not the portals, not RERA.
This is the "street intelligence" layer. Developer sites often carry:
  • Pre-launch projects (not yet on portals or RERA)
  • Soft-launch pricing (before official listing)
  • Phase-wise updates (Phase 2 launch while Phase 1 is on portals)
  • Micro-market expansion signals (when a developer enters a new zone)

Covered developers (North Bengaluru focus):
  Brigade Enterprises, Prestige Group, Sobha Limited, Godrej Properties,
  Adarsh Developers, Salarpuria Sattva, Shriram Properties, Mantri Developers

Model: Gemini Flash — handles unstructured developer marketing pages better
       than structured extraction models. Large context = full-page comprehension.

Market filter: Each developer's project list is filtered for North Bengaluru
keywords (yelahanka, hebbal, devanahalli, jakkur, kogilu, thanisandra, etc.)

Dedup: canonical ID = dev:{sha16(developer+name+locality)} — cross-source.
       If the same project later appears on 99acres, the cid_project() call
       from portal_scout will match because it uses the same hash inputs.

Run standalone:
  python scrapers/developer_scout.py --market Yelahanka
  python scrapers/developer_scout.py --developer Brigade
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
    GEMINI_API_KEY, GEMINI_CEO_MODEL,
    CEREBRAS_API_KEY, CEREBRAS_BASE_URL, CEREBRAS_MODEL,
)
from scrapers.scout_memory import ScoutMemory


# ── Developer registry ────────────────────────────────────────────────────────

DEVELOPER_SITES: dict[str, dict] = {
    "Brigade": {
        "name": "Brigade Enterprises",
        "projects_url": "https://www.brigade.in/all-properties?city=bangalore",
        "alt_url": "https://www.brigade.in/residential",
        "use_playwright": True,
        "north_blr_keywords": [
            "yelahanka", "jakkur", "hebbal", "kogilu", "thanisandra",
            "north bangalore", "devanahalli", "bagalur"
        ],
    },
    "Prestige": {
        "name": "Prestige Group",
        "projects_url": "https://www.prestige.co.in/residential-projects/bangalore",
        "alt_url": "https://www.prestige.co.in/all-projects",
        "use_playwright": True,
        "north_blr_keywords": [
            "yelahanka", "hebbal", "devanahalli", "north bangalore",
            "thanisandra", "jakkur", "finsbury"
        ],
    },
    "Sobha": {
        "name": "Sobha Limited",
        "projects_url": "https://www.sobha.com/ongoing-projects/bengaluru/",
        "alt_url": "https://www.sobha.com/projects/",
        "use_playwright": False,
        "north_blr_keywords": [
            "yelahanka", "devanahalli", "north bangalore", "hebbal", "jakkur"
        ],
    },
    "Godrej": {
        "name": "Godrej Properties",
        "projects_url": "https://www.godrejproperties.com/bengaluru",
        "alt_url": "https://www.godrejproperties.com/all-projects?city=bengaluru",
        "use_playwright": False,
        "north_blr_keywords": [
            "yelahanka", "north bangalore", "devanahalli", "hebbal"
        ],
    },
    "Adarsh": {
        "name": "Adarsh Developers",
        "projects_url": "https://www.adarshgroup.com/all-projects/",
        "alt_url": "https://www.adarshgroup.com/ongoing-projects/",
        "use_playwright": False,
        "north_blr_keywords": [
            "yelahanka", "satellite town", "north bangalore"
        ],
    },
    "Salarpuria": {
        "name": "Salarpuria Sattva Group",
        "projects_url": "https://www.salarpuriasattva.com/residential-projects/",
        "alt_url": "https://www.salarpuriasattva.com/ongoing-projects/",
        "use_playwright": False,
        "north_blr_keywords": [
            "yelahanka", "hebbal", "north bangalore", "thanisandra"
        ],
    },
    "Shriram": {
        "name": "Shriram Properties",
        "projects_url": "https://www.shriramproperties.com/projects/bangalore/",
        "alt_url": "https://www.shriramproperties.com/all-projects/",
        "use_playwright": False,
        "north_blr_keywords": [
            "yelahanka", "north bangalore"
        ],
    },
    "Mantri": {
        "name": "Mantri Developers",
        "projects_url": "https://www.mantrideveloper.com/projects/",
        "alt_url": "https://www.mantrideveloper.com/ongoing-projects/",
        "use_playwright": False,
        "north_blr_keywords": [
            "yelahanka", "north bangalore"
        ],
    },
}

# Yelahanka-specific keyword weight (for scoring relevance)
MARKET_KEYWORDS: dict[str, list[str]] = {
    "Yelahanka": [
        "yelahanka", "yelahanka new town", "yelahanka satellite town",
        "kogilu", "singanayakanahalli", "bagalur", "jakkur", "north bangalore"
    ],
    "Devanahalli": [
        "devanahalli", "sadahalli", "rachenahalli", "kiadb aerospace",
        "namma metro devanahalli", "bial", "international airport"
    ],
    "Hebbal": [
        "hebbal", "nagawara", "thanisandra", "rt nagar", "banaswadi"
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

DEVELOPER_EXTRACTION_PROMPT = """\
You are reading a real estate developer's website listing their projects.
Extract all projects you can find, filtered to North Bengaluru locations only.

North Bengaluru locations include: Yelahanka, Hebbal, Devanahalli, Jakkur,
Thanisandra, Kogilu, Bagalur, Singanayakanahalli, Nagawara, RT Nagar.

For each matching project, return a JSON array of objects with:
  project_name     (string)
  developer        (string: the developer company name)
  bhk              (string: e.g. "3 BHK, 4 BHK")
  price_display    (string: asking price or "Price on Request")
  area_sqft        (string)
  locality         (string: specific location within North Bengaluru)
  status           (string: Pre-Launch | New Launch | Under Construction | Ready to Move)
  possession_date  (string or null)
  rera_number      (string or null)
  highlights       (array of up to 5 key USPs)
  source_url       (string or null)

Include ONLY North Bengaluru projects. Skip South/East/West Bengaluru.
Return ONLY the JSON array, no commentary.

DEVELOPER WEBSITE TEXT:
"""


# ── AI extraction (Gemini Flash — full-page marketing comprehension) ──────────

def _ai_extract_developer(text: str, developer_name: str) -> list[dict]:
    # Filter text to market-relevant sections first
    filtered = _filter_relevant_text(text, developer_name)
    if len(filtered) < 100:
        return []

    # Gemini Flash can handle larger context
    truncated = filtered[:6000]
    prompt = DEVELOPER_EXTRACTION_PROMPT + truncated

    raw = ""
    try:
        import litellm
        if GEMINI_API_KEY:
            resp = litellm.completion(
                model=GEMINI_CEO_MODEL,
                api_key=GEMINI_API_KEY,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.0,
            )
            raw = resp.choices[0].message.content.strip()
        elif CEREBRAS_API_KEY:
            # Fallback — truncate more aggressively for Cerebras context limit
            short_prompt = DEVELOPER_EXTRACTION_PROMPT + filtered[:2000]
            resp = litellm.completion(
                model=f"openai/{CEREBRAS_MODEL}",
                api_key=CEREBRAS_API_KEY,
                base_url=CEREBRAS_BASE_URL,
                messages=[{"role": "user", "content": short_prompt}],
                max_tokens=800,
                temperature=0.0,
            )
            raw = resp.choices[0].message.content.strip()
        else:
            return []
    except Exception as exc:
        logger.warning(f"[DeveloperScout] AI extraction error: {exc}")
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
    logger.debug(f"[DeveloperScout] JSON parse failed: {raw[:100]}")
    return []


def _filter_relevant_text(text: str, developer_name: str) -> str:
    """
    Keep lines that mention North Bengaluru keywords.
    This reduces noise from South/East Bengaluru projects before AI processing.
    """
    north_blr = {
        "yelahanka", "hebbal", "devanahalli", "jakkur", "thanisandra",
        "kogilu", "bagalur", "singanayakanahalli", "nagawara", "north bangalore",
        "north bengaluru", "bial", "airport"
    }
    lines = text.split("\n")
    relevant = []
    window: list[str] = []

    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in north_blr):
            # Include context window (3 lines before + current + 3 after)
            relevant.extend(window[-3:])
            relevant.append(line)
            window = []
        else:
            window.append(line)

    if not relevant:
        # No keyword hits — return full text for AI to decide
        return text
    return "\n".join(relevant)


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer",
                     "aside", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s{3,}", "\n", text)


# ── Normalization ─────────────────────────────────────────────────────────────

def _parse_price(s: str | None) -> float:
    if not s or str(s).lower() in ("price on request", "null", "none", ""):
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
    return num


def _normalize_developer_finding(
    raw: dict, developer_key: str, developer_name: str, market: str, page_url: str
) -> dict | None:
    name = (raw.get("project_name") or "").strip()
    locality = (raw.get("locality") or market).strip()
    if not name:
        return None

    rera = (raw.get("rera_number") or "").strip()
    if rera in ("null", "None"):
        rera = ""

    url = (raw.get("source_url") or page_url or "").strip()

    if rera:
        cid = ScoutMemory.cid_rera(rera)
    else:
        cid = ScoutMemory.cid_developer(developer_name, name, locality)

    price_str = raw.get("price_display") or "Price on Request"
    price_val = _parse_price(price_str)
    bhk_raw = raw.get("bhk") or ""
    bhk_configs = [b.strip() for b in bhk_raw.split(",") if b.strip()]

    return {
        "cid": cid,
        "source": f"dev_{developer_key.lower()}",
        "market": market,
        "project_name": name,
        "developer": developer_name,
        "bhk_configs": bhk_configs,
        "price_display": price_str,
        "price_min": price_val,
        "area_sqft": str(raw.get("area_sqft") or ""),
        "locality": locality,
        "launch_status": raw.get("status") or "Unknown",
        "is_new_launch": "launch" in (raw.get("status") or "").lower(),
        "possession_date": raw.get("possession_date") or "",
        "rera_number": rera,
        "highlights": raw.get("highlights") or [],
        "source_url": url,
        "scraped_at": datetime.now().isoformat(),
    }


# ── Developer Scout ───────────────────────────────────────────────────────────

class DeveloperScout:
    """
    Crawls developer websites directly for North Bengaluru projects.
    Catches pre-launch and soft-launch projects before they hit portals.
    Uses Gemini Flash for full-page marketing content comprehension.
    """

    def __init__(self, market: str, memory: ScoutMemory | None = None):
        self.market = market
        self.memory = memory or ScoutMemory(market)
        self.session = requests.Session()
        self.session.headers.update(SCRAPE_HEADERS)

    def scout(self, developers: list[str] | None = None) -> list[dict]:
        """
        Crawl developer sites. Returns all findings with is_new flag.
        developers: list of keys from DEVELOPER_SITES, e.g. ["Brigade", "Sobha"]
        """
        all_findings: list[dict] = []
        targets = developers if developers else list(DEVELOPER_SITES.keys())

        for dev_key in targets:
            dev_info = DEVELOPER_SITES.get(dev_key)
            if not dev_info:
                logger.warning(f"[DeveloperScout] Unknown developer key: {dev_key}")
                continue
            try:
                findings = self._scout_developer(dev_key, dev_info)
                new, known = self.memory.mark_all(findings, source=f"dev_{dev_key.lower()}")
                all_findings.extend(new + known)
                logger.info(
                    f"[DeveloperScout][{dev_key}] "
                    f"{len(findings)} found | {len(new)} new | {len(known)} known"
                )
                time.sleep(2)
            except Exception as exc:
                logger.warning(f"[DeveloperScout][{dev_key}] Failed: {exc}")

        new_total = sum(1 for f in all_findings if f.get("is_new"))
        logger.info(
            f"[DeveloperScout] {self.market}: "
            f"{len(all_findings)} total | {new_total} new pre-launch finds"
        )
        return all_findings

    def _scout_developer(self, dev_key: str, dev_info: dict) -> list[dict]:
        url = dev_info["projects_url"]
        alt_url = dev_info.get("alt_url", "")
        developer_name = dev_info["name"]

        # Fetch page content
        if dev_info.get("use_playwright"):
            text = self._playwright_fetch(url)
            if len(text) < 200 and alt_url:
                text = self._playwright_fetch(alt_url)
        else:
            text = self._requests_fetch(url)
            if len(text) < 200 and alt_url:
                text = self._requests_fetch(alt_url)

        if len(text) < 100:
            logger.debug(f"[DeveloperScout][{dev_key}] No usable content from {url}")
            return []

        raw_items = _ai_extract_developer(text, developer_name)
        results = [
            _normalize_developer_finding(r, dev_key, developer_name, self.market, url)
            for r in raw_items
        ]
        return [r for r in results if r is not None]

    def _requests_fetch(self, url: str) -> str:
        try:
            resp = self.session.get(url, timeout=25)
            time.sleep(1)
            if resp.status_code == 200:
                return _clean_html(resp.text)
            logger.debug(f"[DeveloperScout] HTTP {resp.status_code} for {url}")
        except requests.exceptions.RequestException as exc:
            logger.debug(f"[DeveloperScout] Request error: {exc}")
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
            logger.debug(f"[DeveloperScout][Playwright] Failed for {url}: {exc}")
            return ""


# ── Standalone runner ─────────────────────────────────────────────────────────

def scout_developers(market: str, developers: list[str] | None = None) -> list[dict]:
    memory = ScoutMemory(market)
    scout = DeveloperScout(market, memory)
    findings = scout.scout(developers=developers)

    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "outputs", market.lower().replace(" ", "_")
    )
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = os.path.join(output_dir, f"developer_scout_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, default=str)

    new_total = sum(1 for f in findings if f.get("is_new"))
    print(f"\n{'='*55}")
    print(f"DEVELOPER SCOUT — {market.upper()}")
    print(f"{'='*55}")
    print(f"Total findings : {len(findings)}")
    print(f"New pre-launch : {new_total}")
    print(f"Output         : {out_path}")
    for f in [x for x in findings if x.get("is_new")][:5]:
        print(
            f"  [{f['source']:<18}] "
            f"{f.get('project_name','?')[:30]:<32} | "
            f"{f.get('launch_status','?'):<20} | "
            f"{f.get('price_display','?')}"
        )
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Developer Scout — direct developer website crawler")
    parser.add_argument("--market", default="Yelahanka",
                        choices=["Yelahanka", "Devanahalli", "Hebbal"])
    parser.add_argument("--developer", default="",
                        help="Comma-separated developer keys (default: all)")
    args = parser.parse_args()
    logger.add("logs/developer_scout.log", rotation="10 MB")
    devs = [d.strip() for d in args.developer.split(",") if d.strip()] or None
    scout_developers(args.market, developers=devs)
