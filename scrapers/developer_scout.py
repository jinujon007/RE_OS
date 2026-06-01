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
    GEMINI_API_KEY,
    GEMINI_CEO_MODEL,
    CEREBRAS_API_KEY,
    CEREBRAS_BASE_URL,
    CEREBRAS_MODEL,
)
from scrapers.scout_memory import ScoutMemory


# ── Developer registry ────────────────────────────────────────────────────────

DEVELOPER_SITES: dict[str, dict] = {
    "Brigade": {
        "name": "Brigade Enterprises",
        "listing_url": "https://www.brigadegroup.com/residential/projects/bengaluru",
        "projects_url": "https://www.brigadegroup.com/residential/projects/bengaluru/brigade-insignia",
        "alt_url": "https://www.brigadegroup.com/residential/projects/bengaluru/brigade-insignia",
        "use_playwright": True,
        "north_blr_keywords": [
            "yelahanka",
            "jakkur",
            "hebbal",
            "kogilu",
            "thanisandra",
            "north bangalore",
            "devanahalli",
            "bagalur",
            "yelahanka new town",
            "yelahanka satellite town",
            "yelahanka phase 2",
            "yelahanka phase 3",
        ],
    },
    "Prestige": {
        "name": "Prestige Group",
        "listing_url": "https://www.prestigeconstructions.com/residential-projects/bangalore",
        "projects_url": "https://www.prestigeconstructions.com/residential-projects/bangalore/prestige-finsbury-park",
        "alt_url": "https://www.prestigeconstructions.com/residential-projects/bangalore/prestige-finsbury-park",
        "use_playwright": True,
        "north_blr_keywords": [
            "yelahanka",
            "hebbal",
            "devanahalli",
            "north bangalore",
            "thanisandra",
            "jakkur",
            "finsbury",
            "yelahanka new town",
            "yelahanka satellite town",
            "yelahanka phase 2",
            "yelahanka phase 3",
        ],
    },
    "Sobha": {
        "name": "Sobha Limited",
        "listing_url": "https://www.sobha.com/locations/bengaluru/",
        "projects_url": "https://www.sobha.com/bengaluru/sobha-palm-court/",
        "alt_url": "https://www.sobha.com/bengaluru/sobha-palm-court/",
        "use_playwright": False,
        "north_blr_keywords": [
            "yelahanka",
            "devanahalli",
            "north bangalore",
            "hebbal",
            "jakkur",
            "yelahanka new town",
            "yelahanka satellite town",
            "yelahanka phase 2",
            "yelahanka phase 3",
        ],
    },
    "Godrej": {
        "name": "Godrej Properties",
        "projects_url": "https://www.godrejproperties.com/bengaluru",
        "alt_url": "https://www.godrejproperties.com/all-projects?city=bengaluru",
        "use_playwright": False,
        "north_blr_keywords": ["yelahanka", "north bangalore", "devanahalli", "hebbal"],
    },
    "Adarsh": {
        "name": "Adarsh Developers",
        "projects_url": "https://www.adarshgroup.com/all-projects/",
        "alt_url": "https://www.adarshgroup.com/ongoing-projects/",
        "use_playwright": False,
        "north_blr_keywords": ["yelahanka", "satellite town", "north bangalore"],
    },
    "Salarpuria": {
        "name": "Salarpuria Sattva Group",
        "projects_url": "https://www.salarpuriasattva.com/residential-projects/",
        "alt_url": "https://www.salarpuriasattva.com/ongoing-projects/",
        "use_playwright": False,
        "north_blr_keywords": ["yelahanka", "hebbal", "north bangalore", "thanisandra"],
    },
    "Shriram": {
        "name": "Shriram Properties",
        "projects_url": "https://www.shriramproperties.com/projects/bangalore/",
        "alt_url": "https://www.shriramproperties.com/all-projects/",
        "use_playwright": False,
        "north_blr_keywords": ["yelahanka", "north bangalore"],
    },
    "Mantri": {
        "name": "Mantri Developers",
        "projects_url": "https://www.mantrideveloper.com/projects/",
        "alt_url": "https://www.mantrideveloper.com/ongoing-projects/",
        "use_playwright": False,
        "north_blr_keywords": ["yelahanka", "north bangalore"],
    },
}

# Yelahanka-specific keyword weight (for scoring relevance)
MARKET_KEYWORDS: dict[str, list[str]] = {
    "Yelahanka": [
        "yelahanka",
        "yelahanka new town",
        "yelahanka satellite town",
        "kogilu",
        "singanayakanahalli",
        "bagalur",
        "jakkur",
        "north bangalore",
    ],
    "Devanahalli": [
        "devanahalli",
        "sadahalli",
        "rachenahalli",
        "kiadb aerospace",
        "namma metro devanahalli",
        "bial",
        "international airport",
    ],
    "Hebbal": ["hebbal", "nagawara", "thanisandra", "rt nagar", "banaswadi"],
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
Look for project names, launch dates, BHK configurations, and price ranges.
If this page is a homepage or generic marketing page with NO project listings,
return an empty JSON array `[]`. Do not guess or fabricate projects.

Return ONLY the JSON array, no commentary.

DEVELOPER WEBSITE TEXT:
"""


# ── AI extraction (Gemini Flash — full-page marketing comprehension) ──────────


def _ai_extract_developer(
    text: str, developer_name: str, dom_snippets: str = ""
) -> list[dict]:
    # Filter text to market-relevant sections first
    filtered = _filter_relevant_text(text, developer_name)
    if len(filtered) < 100 and len(dom_snippets) < 100:
        return []

    # T-147: DOM-targeted extraction takes priority — project cards/lists tagged with
    # North Bengaluru keywords. Even 200 chars of DOM snippets (5-6 project cards) beats
    # the full-text path which is dominated by nav/footer noise. Fall back to sampling
    # only if DOM < 200 chars.
    if dom_snippets and len(dom_snippets) >= 200:
        truncated = dom_snippets[:12000]
        prompt = DEVELOPER_EXTRACTION_PROMPT + truncated
    elif len(filtered) >= len(text) - 10 and len(filtered) > 8000:
        mid = len(filtered) // 2
        truncated = filtered[:5000] + "\n...\n" + filtered[mid : mid + 5000]
        prompt = DEVELOPER_EXTRACTION_PROMPT + truncated
    else:
        # No meaningful DOM snippets AND text is noisy. Append any available snippets
        # to the prompt so AI has at least some signal.
        fallback = dom_snippets if dom_snippets else filtered[:8000]
        prompt = DEVELOPER_EXTRACTION_PROMPT + fallback

    raw = ""
    import litellm  # inside function — optional dep, not required at module level

    # ── Primary: Gemini Flash ─────────────────────────────────────────────────
    gemini_error = None
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
        except Exception as exc:
            gemini_error = exc
            logger.warning(
                f"[DeveloperScout] Gemini extraction error ({type(exc).__name__}): {exc}"
            )

    # ── Fallback: Cerebras 8b (truncate to stay within 8 192-token context) ───
    if (not raw) and CEREBRAS_API_KEY:
        cerebras_prompt = prompt[:7000] + "\n... [TRUNCATED for Cerebras 8K]"
        try:
            resp = litellm.completion(
                model=f"openai/{CEREBRAS_MODEL}",
                api_key=CEREBRAS_API_KEY,
                base_url=CEREBRAS_BASE_URL,
                messages=[{"role": "user", "content": cerebras_prompt}],
                max_tokens=800,
                temperature=0.0,
            )
            raw = resp.choices[0].message.content.strip()
            if gemini_error:
                logger.warning(
                    "[DeveloperScout] Cerebras fallback succeeded after Gemini failure "
                    f"({type(gemini_error).__name__})"
                )
        except Exception as exc:
            logger.warning(
                f"[DeveloperScout] Cerebras extraction error ({type(exc).__name__}): {exc}"
            )

    if not raw:
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
        "yelahanka",
        "hebbal",
        "devanahalli",
        "jakkur",
        "thanisandra",
        "kogilu",
        "bagalur",
        "singanayakanahalli",
        "nagawara",
        "north bangalore",
        "north bengaluru",
        "bial",
        "airport",
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
    for tag in soup(
        ["script", "style", "nav", "header", "footer", "aside", "noscript", "iframe"]
    ):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s{3,}", "\n", text)


def _extract_dom_snippets(html: str) -> str:
    """
    T-147 fix: Extract project-specific elements using BHK+keyword dual-filter.

    Old approach: any element with keyword hit → dominated by nav/footer noise
    (39k chars for Godrej, but mostly "About Us", "Leadership", "Sustainability")

    New approach (tiered):
      Tier 1: Elements with BOTH keyword AND BHK pattern (2 Bhk, 3 Bhk, etc.)
              → guaranteed project cards, minimal noise
      Tier 2: Elements with keyword + price/location patterns + noise filter
              → nav items stripped (know us, leadership, projects residential, etc.)
              → minimum 30 chars threshold to exclude buttons/crumbs
    """
    north_blr = {
        "yelahanka",
        "hebbal",
        "devanahalli",
        "jakkur",
        "thanisandra",
        "kogilu",
        "bagalur",
        "singanayakanahalli",
        "nagawara",
        "north bangalore",
        "north bengaluru",
        "bial",
        "airport",
        "finsbury",
    }
    soup = BeautifulSoup(html, "lxml")

    # Tier 1: BHK + keyword — project cards
    bhk_re = re.compile(r"\d+\s*bhk", re.IGNORECASE)
    bhk_snippets: list[str] = []
    for tag in soup.find_all(["a", "h2", "h3", "h4", "span", "p", "li"]):
        text = tag.get_text(" ", strip=True)
        if len(text) < 20:
            continue
        text_lower = text.lower()
        has_kw = any(kw in text_lower for kw in north_blr)
        has_bhk = bool(bhk_re.search(text_lower))
        if has_kw and has_bhk:
            bhk_snippets.append(text)

    if bhk_snippets:
        return "\n".join(bhk_snippets)

    # Tier 2: Keyword elements with noise filter
    skip_starts = (
        "home",
        "about",
        "career",
        "contact",
        "investor",
        "media",
        "gallery",
        "legal",
        "privacy",
        "terms",
        "close",
        "menu",
        "leadership",
        "sustainability",
    )
    skip_contains = {
        "know us",
        "projects residential",
        "projects location",
        "residential projects",
        "investor relations",
        "media centre",
    }
    tier2_snippets: list[str] = []
    for tag in soup.find_all(["a", "span", "p", "div", "h2", "h3", "li"]):
        text = tag.get_text(" ", strip=True)
        if len(text) < 30:
            continue
        text_lower = text.lower()
        if not any(kw in text_lower for kw in north_blr):
            continue
        # Noise filter
        stripped = text_lower.strip()
        if stripped.startswith(skip_starts):
            continue
        if any(sc in text_lower for sc in skip_contains):
            continue
        # Require meaningful content (at least 3 words)
        if text.count(" ") < 2:
            continue
        tier2_snippets.append(text)

    return "\n".join(tier2_snippets)


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
                new, known = self.memory.mark_all(
                    findings, source=f"dev_{dev_key.lower()}"
                )
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
        listing_url = dev_info.get("listing_url", "")
        url = dev_info["projects_url"]
        alt_url = dev_info.get("alt_url", "")
        developer_name = dev_info["name"]

        raw_html = ""
        fetch_url = ""

        if listing_url:
            if dev_info.get("use_playwright"):
                raw_html = self._playwright_fetch_raw(listing_url)
            else:
                raw_html = self._requests_fetch_raw(listing_url)
            fetch_url = listing_url
            if len(raw_html) < 1000 and url:
                logger.debug(f"[DeveloperScout][{dev_key}] Listing page too short ({len(raw_html)} chars), falling back to {url}")
                if dev_info.get("use_playwright"):
                    raw_html = self._playwright_fetch_raw(url)
                else:
                    raw_html = self._requests_fetch_raw(url)
                fetch_url = url

        if len(raw_html) < 500 and alt_url:
            logger.debug(f"[DeveloperScout][{dev_key}] Still insufficient, trying alt: {alt_url}")
            if dev_info.get("use_playwright"):
                raw_html = self._playwright_fetch_raw(alt_url)
            else:
                raw_html = self._requests_fetch_raw(alt_url)
            fetch_url = alt_url

        if len(raw_html) < 500:
            logger.debug(f"[DeveloperScout][{dev_key}] No usable content from any URL")
            return []

        text = _clean_html(raw_html)
        dom_snippets = _extract_dom_snippets(raw_html)
        raw_items = _ai_extract_developer(
            text, developer_name, dom_snippets=dom_snippets
        )
        results = [
            _normalize_developer_finding(r, dev_key, developer_name, self.market, fetch_url)
            for r in raw_items
        ]
        return [r for r in results if r is not None]

    def _requests_fetch_raw(self, url: str) -> str:
        try:
            resp = self.session.get(url, timeout=25)
            time.sleep(1)
            if resp.status_code == 200:
                return resp.text
            logger.debug(f"[DeveloperScout] HTTP {resp.status_code} for {url}")
        except requests.exceptions.RequestException as exc:
            logger.debug(f"[DeveloperScout] Request error: {exc}")
        return ""

    def _playwright_fetch_raw(self, url: str) -> str:
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
                page.wait_for_timeout(6000)
                # Scroll to trigger lazy-loaded project cards
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
                html = page.content()
                browser.close()
                return html
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
        "outputs",
        market.lower().replace(" ", "_"),
    )
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = os.path.join(output_dir, f"developer_scout_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, default=str)

    new_findings = [f for f in findings if f.get("is_new")]
    new_total = len(new_findings)
    try:
        from utils.discord_notifier import send_competitor_alert
        for project in new_findings:
            dev = project.get("developer") or project.get("developer_name") or "Unknown"
            send_competitor_alert(
                developer=dev,
                project=project.get("project_name", "Unknown"),
                market=market,
            )
    except Exception as _alert_err:
        logger.warning(f"[DeveloperScout] Competitor alert failed for {market}: {_alert_err}")

    print(f"\n{'=' * 55}")
    print(f"DEVELOPER SCOUT — {market.upper()}")
    print(f"{'=' * 55}")
    print(f"Total findings : {len(findings)}")
    print(f"New pre-launch : {new_total}")
    print(f"Output         : {out_path}")
    for f in [x for x in findings if x.get("is_new")][:5]:
        print(
            f"  [{f['source']:<18}] "
            f"{f.get('project_name', '?')[:30]:<32} | "
            f"{f.get('launch_status', '?'):<20} | "
            f"{f.get('price_display', '?')}"
        )
    return findings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Developer Scout — direct developer website crawler"
    )
    parser.add_argument(
        "--market", default="Yelahanka", choices=["Yelahanka", "Devanahalli", "Hebbal"]
    )
    parser.add_argument(
        "--developer", default="", help="Comma-separated developer keys (default: all)"
    )
    args = parser.parse_args()
    logger.add("/tmp/logs/developer_scout.log", rotation="10 MB")
    devs = [d.strip() for d in args.developer.split(",") if d.strip()] or None
    scout_developers(args.market, developers=devs)
