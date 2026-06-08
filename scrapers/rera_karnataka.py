"""
RE_OS — RERA Karnataka Scraper
────────────────────────────────
Pulls all registered projects from RERA Karnataka portal.
URL: https://rera.karnataka.gov.in

Strategy:
  Primary path: POST /projectViewDetails with district + subdistrict (taluk)
    Works for Devanahalli. Yelahanka/Hebbal POST fails (session cookie issue).
  Fallback path (T-1062): Playwright browser automation for POST-failing markets.
    Headless Chromium → fill district/subdistrict dropdown → submit → parse HTML.
  Response: full HTML page, all rows rendered server-side (no JS required)
  Parse: BeautifulSoup table extraction

Market → district/taluk mapping confirmed via live portal:
  Yelahanka  → district="Bengaluru Urban",  subdistrict="Yelahanka"     (165 projects)
  Hebbal     → district="Bengaluru Urban",  subdistrict="Bengaluru North" (734 projects)
  Devanahalli→ district="Bengaluru  Rural", subdistrict="Devanahalli"   (317 projects)

Note: listing page has project name, developer, RERA no, status, type, dates.
      Unit counts and PSF require individual project detail pages (future phase).

Run standalone: python scrapers/rera_karnataka.py --market Yelahanka
"""

import itertools
import requests
from bs4 import BeautifulSoup
import json
import re
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import MARKET_RERA_CONFIG, RERA_USE_PLAYWRIGHT_MARKETS
from config.checkpointer import Checkpointer
from config.settings import RERA_PLAYWRIGHT_LOCALITY_VALUES

_RERA_MODEL_NAME = "rera-extractor:3b"
_RERA_OLLAMA_URL = "http://ollama:11434/api/generate"
_MODEL_BATCH_SIZE = 8        # rows per batch for parallel model calls (H-2 fix)
_MODEL_MAX_WORKERS = 4       # parallel Ollama requests

# Alternate subdistrict spellings to try when first attempt returns 0 results.
# Ordered by decreasing likelihood. Scraper walks this list until non-zero results.
ALT_SUBDISTRICTS = {
    "Hebbal": ["Bangalore North", "Bengaluru North", "Hebbal"],
    "Yelahanka": ["Bengaluru North", "Bangalore North", "Yelahanka New Town"],
}

# Alternate district spellings — tries single-space variant as fallback
# (portal historically used double-space for 'Rural'; 'Urban' may vary by portal version)
ALT_DISTRICTS = {
    "Yelahanka": ["Bengaluru Urban", "Bangalore Urban"],
    "Hebbal": ["Bengaluru Urban", "Bangalore Urban"],
}


_UA_POOL = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
]

_UA_CYCLE = itertools.cycle(_UA_POOL)


class _FakeCookie:
    """T-1063: requests-compatible cookie object from Playwright cookie dict."""
    def __init__(self, name, value, domain, path):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path


# Rate-limit tracking for Discord fallback alerts (T-1065): {market: last_alert_timestamp}
_last_fallback_alert: dict[str, float] = {}


def _should_fire_fallback_alert(market: str, cooldown_seconds: int = 3600) -> bool:
    """Returns True if cooldown has elapsed since last FALLBACK_SEED alert for this market."""
    import time as _time
    last = _last_fallback_alert.get(market, 0.0)
    if _time.time() - last >= cooldown_seconds:
        _last_fallback_alert[market] = _time.time()
        return True
    return False


_PW_NAVIGATE_TIMEOUT = 30_000
_PW_FORM_FILL_DELAY = 1000
_PW_RESULTS_DELAY = 2000
_PW_DROPDOWN_DELAY = 500


def _validate_positive(label: str, value: int) -> int:
    """Clamp negative values to 0 for metric logging."""
    return max(value, 0)


def _cleanup_stale_alert_tracking(max_entries: int = 100) -> None:
    """Prevent unbounded growth of _last_fallback_alert dict."""
    if len(_last_fallback_alert) > max_entries:
        _last_fallback_alert.clear()


def _log_agent_run(market: str, record_count: int, fallback_triggered: bool, data_source: str, path_used: str, duration_ms: int) -> None:
    """Log per-market scraper health metric to agent_runs (T-1064). Non-fatal on failure."""
    import json as _json
    record_count = _validate_positive("record_count", record_count)
    duration_ms = _validate_positive("duration_ms", duration_ms)
    try:
        from utils.db import get_engine
        from sqlalchemy import text as _sa_text
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                _sa_text("""
                    INSERT INTO agent_runs (
                        agent_name, micro_market, task_type, status,
                        records_inserted, metadata, started_at, completed_at
                    ) VALUES (
                        :agent_name, :market, 'scrape_complete', 'completed',
                        :record_count, CAST(:metadata AS jsonb), NOW(), NOW()
                    )
                """),
                {
                    "agent_name": "rera_scraper",
                    "market": market,
                    "record_count": record_count,
                    "metadata": _json.dumps({
                        "record_count": record_count,
                        "fallback_triggered": fallback_triggered,
                        "data_source": data_source,
                        "path_used": path_used,
                        "duration_ms": duration_ms,
                    }),
                },
            )
    except Exception as exc:
        logger.warning(f"[RERA][AgentRun] Failed to log health metric for {market}: {exc}")


class RERAKarnatakaScraper:
    """
    Scrapes RERA Karnataka project listing via direct HTTP POST.
    No Playwright or JS rendering required — portal returns server-side HTML.
    """

    BASE_URL = "https://rera.karnataka.gov.in"
    SEARCH_URL = f"{BASE_URL}/projectViewDetails"

    _BASE_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": "https://rera.karnataka.gov.in/viewAllProjects",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    def __init__(self):
        self.session = requests.Session()
        self._rotate_ua()  # set initial UA

    def _rotate_ua(self) -> str:
        ua = next(_UA_CYCLE)
        self.session.headers.update({**self._BASE_HEADERS, "User-Agent": ua})
        logger.debug(f"[RERA] UA rotated → {ua[:60]}…")
        return ua

    def _extract_with_rera_model(self, html: str) -> list[dict] | None:
        """Try extracting project data from raw HTML using the fine-tuned rera-extractor:3b model via Ollama.

        Strategy:
          1. Parse HTML table rows via BeautifulSoup (fast, no model call)
          2. Submit each row to Ollama rera-extractor:3b in parallel (ThreadPoolExecutor, 4 workers)
          3. Parse JSON responses, build project dicts
          4. If >50% of rows fail → return None → caller falls back to _parse_html_table

        Performance budget:
          - 300 rows × ~2s per Ollama call ÷ 4 workers = ~150s theoretical max
          - Expected: 60-90s for 300 rows (Ollama inference on RTX 3050)

        Fallback triggers:
          - Ollama model not loaded: all rows return None → >50% failure → None returned
          - Ollama container down: urllib timeout on every call → >50% failure → None returned
          - Table has no rows: immediate None return

        Fix B-3: Log model failures at WARNING level so operators notice.
        Fix H-2: Parallel batch calls via ThreadPoolExecutor to handle 300+ rows efficiently.
        Fix H-4: extraction_path set only in _post_search, not per-project here.
        """
        import urllib.request

        try:
            from bs4 import BeautifulSoup as _BS
            soup = _BS(html, "lxml")
            rows = soup.select("table tbody tr")
        except Exception as exc:
            logger.debug(f"[RERA][Model] HTML parse failed: {exc}")
            return None

        if not rows:
            logger.debug("[RERA][Model] No table rows found in HTML — falling back")
            return None

        logger.info(f"[RERA][Model] Attempting extraction on {len(rows)} rows (batch={_MODEL_BATCH_SIZE}, workers={_MODEL_MAX_WORKERS})")

        projects: list[dict] = []
        errors = 0

        def _call_model(row_html: str) -> dict | None:
            """Single Ollama model call for one HTML row."""
            payload = json.dumps({
                "model": _RERA_MODEL_NAME,
                "prompt": (
                    "Extract RERA fields as JSON from this record:\n"
                    f"{row_html}\n\n"
                    "Return ONLY JSON: {\"project_name\":...,\"developer\":...,\"units\":...,\"completion_date\":...,\"rera_id\":...}"
                ),
                "stream": False,
                "options": {"temperature": 0.1, "top_p": 0.9},
            }).encode("utf-8")

            req = urllib.request.Request(
                _RERA_OLLAMA_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read())
                response_text = result.get("response", "").strip()
                return json.loads(response_text)
            except (json.JSONDecodeError, KeyError, urllib.error.URLError) as exc:
                logger.debug(f"[RERA][Model] Row extraction failed: {exc}")
                return None

        # Process rows in parallel batches
        with ThreadPoolExecutor(max_workers=_MODEL_MAX_WORKERS) as executor:
            future_map = {}
            for i, row in enumerate(rows):
                row_html = str(row)
                future = executor.submit(_call_model, row_html)
                future_map[future] = i

            for future in as_completed(future_map):
                idx = future_map[future]
                try:
                    parsed = future.result()
                    if parsed is None:
                        errors += 1
                        continue
                    project = {
                        "rera_number": parsed.get("rera_id", ""),
                        "project_name": parsed.get("project_name", ""),
                        "developer_name": parsed.get("developer", ""),
                        "total_units": int(parsed["units"]) if parsed.get("units") else 0,
                        "possession_date": str(parsed.get("completion_date", "")),
                        "data_source": "rera_karnataka_live",
                        "scraped_at": datetime.now().isoformat(),
                    }
                    projects.append(project)
                except Exception as exc:
                    errors += 1
                    logger.debug(f"[RERA][Model] Row {idx} failed: {exc}")

        if errors > len(rows) * 0.5:
            logger.warning(f"[RERA][Model] {errors}/{len(rows)} rows failed — model may not be loaded. Falling back.")
            return None

        if projects:
            logger.info(f"[RERA][Model] Extracted {len(projects)}/{len(rows)} projects via rera-extractor:3b ({errors} errors)")
            return projects

        return None

    def scrape_market(self, market_name: str) -> tuple[list[dict], list]:
        """
        Main entry point. Returns (projects, cookies) for the market.
        Falls back to hardcoded sample data if portal unreachable.
        """
        import time as _time
        _start_ts = _time.time()
        logger.info(f"Starting RERA scrape for: {market_name}")

        config = MARKET_RERA_CONFIG.get(market_name)
        if not config:
            logger.warning(f"  No RERA config for '{market_name}' — using fallback")
            return self._fallback_rera_data(market_name), []

        projects = self._post_search(
            config["district"], config["subdistrict"], market_name
        )

        if not projects:
            # Try alternate subdistrict spellings (same district)
            alt_subdistricts = ALT_SUBDISTRICTS.get(market_name, [])
            for alt in alt_subdistricts:
                logger.info(f"  Trying alternate subdistrict '{alt}' for {market_name}")
                alt_projects = self._post_search(config["district"], alt, market_name)
                if alt_projects:
                    projects = alt_projects
                    break

        if not projects:
            # Try alternate district spellings (original subdistrict + all alt subdistricts)
            alt_districts = ALT_DISTRICTS.get(market_name, [])
            subdistricts_to_try = [config["subdistrict"]] + ALT_SUBDISTRICTS.get(market_name, [])
            for alt_district in alt_districts:
                for sub in subdistricts_to_try:
                    logger.info(f"  Trying district='{alt_district}' subdistrict='{sub}'")
                    alt_projects = self._post_search(alt_district, sub, market_name)
                    if alt_projects:
                        projects = alt_projects
                        logger.info(f"  Live data found with district='{alt_district}' sub='{sub}'")
                        break
                if projects:
                    break

        used_playwright = False
        cookies = []
        if not projects:
            # T-1062: Try Playwright fallback for markets where POST fails
            pw_projects, pw_cookies = self._playwright_scrape(market_name)
            if pw_projects:
                logger.info(f"  Playwright fallback succeeded for {market_name} ({len(pw_projects)} projects)")
                projects = pw_projects
                cookies = pw_cookies
                used_playwright = True
            else:
                logger.warning("  Portal and Playwright both returned 0 results — using fallback sample data")
                # T-1065: Fire Discord alert when falling back to hardcoded seed (rate-limited to 1/hr)
                _cleanup_stale_alert_tracking()
                if _should_fire_fallback_alert(market_name):
                    try:
                        from utils.discord_notifier import send_scraper_alert
                        send_scraper_alert(market_name, "rera_karnataka", "FALLBACK_SEED", record_count=8)
                    except Exception:
                        logger.debug("[RERA] Discord scraper alert failed (non-fatal)")
                else:
                    logger.debug(f"[RERA] Fallback alert for {market_name} suppressed (rate-limited)")
                # Log health metric before returning — even fallback runs must be tracked (T-1064)
                _duration_ms = int((_time.time() - _start_ts) * 1000)
                _log_agent_run(market_name, 8, True, "fallback_sample", "seed", _duration_ms)
                return self._fallback_rera_data(market_name), []

        # Deduplicate by RERA number
        seen = set()
        unique = []
        for p in projects:
            rn = p.get("rera_number", "")
            if rn and rn not in seen:
                seen.add(rn)
                unique.append(p)
            elif not rn:
                unique.append(p)

        logger.info(f"  Found {len(unique)} unique projects in {market_name}")
        if not used_playwright:
            cookies = list(self.session.cookies)

        # T-1064: Log scraper health metric to agent_runs
        _duration_ms = int((_time.time() - _start_ts) * 1000)
        _is_fallback = any(p.get("data_source", "") == "fallback_sample" for p in unique)
        _data_source = "fallback_sample" if _is_fallback else (unique[0].get("data_source", "rera_karnataka_live") if unique else "unknown")
        _path = "seed" if _is_fallback else ("playwright" if used_playwright else "post")
        _log_agent_run(market_name, len(unique), _is_fallback, _data_source, _path, _duration_ms)

        return unique, cookies

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def _post_search(
        self, district: str, subdistrict: str, market_name: str
    ) -> list[dict]:
        """
        POST to /projectViewDetails and parse the HTML table response.
        All rows are server-rendered — no JS interception needed.
        """
        self._rotate_ua()  # T-300: rotate UA on every attempt (including retries)
        payload = {
            "project": "",
            "firm": "",
            "appNo": "",
            "regNo": "",
            "district": district,
            "subdistrict": subdistrict,
            "taluk": subdistrict,
            "btn1": "Search",
        }

        try:
            resp = self.session.post(self.SEARCH_URL, data=payload, timeout=60)
            resp.raise_for_status()

            size_mb = len(resp.content) / 1024 / 1024
            logger.info(
                f"  [POST] {district}/{subdistrict} → {resp.status_code}, {size_mb:.1f} MB"
            )

            projects = self._extract_with_rera_model(resp.text)
            extraction_path = "rera_model"
            if projects is None:
                logger.info("  [RERA] Model extraction returned None — falling back to HTML parser")
                projects = self._parse_html_table(resp.text, market_name)
                extraction_path = "html_parser"

            if not projects:
                logger.warning(
                    f"  [POST] 0 projects returned for {district}/{subdistrict}. "
                    f"Raw HTML (first 500 chars): {resp.text[:500]}"
                )
            else:
                for p in projects:
                    p["extraction_path"] = extraction_path
            return projects

        except requests.exceptions.RequestException as e:
            logger.warning(f"  [POST] Request failed: {e}")
            return []

    def _parse_html_table(self, html: str, market_name: str) -> list[dict]:
        """
        Parse the DataTables HTML response.
        Table columns (by index):
          0: S.NO
          1: ACKNOWLEDGEMENT NO
          2: REGISTRATION NO (RERA number)
          3: VIEW PROJECT DETAILS (icon/link — capture href for detail scout)
          4: PROMOTER NAME
          5: PROJECT NAME
          6: STATUS
          7: DISTRICT
          8: TALUK
          9: PROJECT TYPE
          10: APPROVED ON
          11: PROPOSED COMPLETION DATE
          12+: extension dates, certificates (skip for now)
        """
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("table tbody tr")
        logger.info(f"  [Parse] Found {len(rows)} rows in HTML table")

        projects = []
        now = datetime.now().isoformat()

        for row in rows:
            tds = row.select("td")
            cells = [td.get_text(strip=True) for td in tds]
            if len(cells) < 6:
                continue

            # Skip header repeat rows (some tables duplicate headers in tbody)
            if cells[0] == "S.NO" or cells[1] == "ACKNOWLEDGEMENT NO":
                continue

            rera_number = self._clean(cells[2]) if len(cells) > 2 else ""
            ack_number = self._clean(cells[1]) if len(cells) > 1 else ""

            # Use ack number as fallback RERA id if registration not yet issued
            project_id = rera_number or ack_number

            # Capture detail page URL from column 3 link (if present)
            detail_url = ""
            if len(tds) > 3:
                link = tds[3].select_one("a[href]")
                if link:
                    href = link.get("href", "")
                    if href.startswith("http"):
                        detail_url = href
                    elif href.startswith("/"):
                        detail_url = self.BASE_URL + href
                else:
                    action_link = tds[3].select_one("a[id]")
                    if action_link and action_link.get("id"):
                        action_id = self._clean(action_link.get("id"))
                        if action_id:
                            detail_url = (
                                f"{self.BASE_URL}/projectDetails?action={action_id}"
                            )

            project = {
                "rera_number": project_id,
                "ack_number": ack_number,
                "project_name": self._clean(cells[5]) if len(cells) > 5 else "",
                "developer_name": self._clean(cells[4]) if len(cells) > 4 else "",
                "project_status": self._clean(cells[6]) if len(cells) > 6 else "",
                "district": self._clean(cells[7]) if len(cells) > 7 else "",
                "locality": self._clean(cells[8]) if len(cells) > 8 else market_name,
                "project_type": self._clean(cells[9])
                if len(cells) > 9
                else "Residential",
                "approved_on": self._clean(cells[10]) if len(cells) > 10 else "",
                "possession_date": self._clean(cells[11]) if len(cells) > 11 else "",
                "detail_url": detail_url,
                # Unit data not available on listing page — requires detail scout
                "total_units": 0,
                "sold_units": 0,
                "unsold_units": 0,
                "data_source": "rera_karnataka_live",
                "scraped_at": now,
            }

            if project["project_name"] or project["rera_number"]:
                projects.append(project)

        return projects

    def _clean(self, text: str) -> str:
        if not text:
            return ""
        # Collapse whitespace, strip newlines and status annotations
        cleaned = re.sub(r"\s+", " ", str(text)).strip()
        # Truncate long status strings (e.g. "WITHDRAWN\n\nAS PER ORDER...")
        if len(cleaned) > 100:
            cleaned = cleaned[:100].strip()
        return cleaned

    def _fallback_rera_data(self, market_name: str) -> list[dict]:
        """
        Fallback sample data when portal is unreachable.
        source='fallback_sample' so analyst knows data is not live.
        """
        now = datetime.now().isoformat()
        meta = {
            "district": "Bangalore Urban",
            "data_source": "fallback_sample",
            "scraped_at": now,
            "note": "Live RERA portal blocked — sample data for pipeline testing",
        }
        data = {
            "Yelahanka": [
                {
                    "rera_number": "PRM/KA/RERA/1251/446/PR/180601/001792",
                    "project_name": "Shriram Suhaana",
                    "developer_name": "Shriram Properties",
                    "locality": "Yelahanka",
                    "project_status": "On-Going",
                    "project_type": "Residential Apartment",
                    "total_units": 648,
                    "sold_units": 520,
                    "unsold_units": 128,
                    "possession_date": "2025-12-31",
                },
                {
                    "rera_number": "PRM/KA/RERA/1251/446/PR/180921/002267",
                    "project_name": "Prestige Lakeside Habitat",
                    "developer_name": "Prestige Estates Projects",
                    "locality": "Yelahanka",
                    "project_status": "On-Going",
                    "project_type": "Residential Apartment",
                    "total_units": 3426,
                    "sold_units": 2900,
                    "unsold_units": 526,
                    "possession_date": "2026-03-31",
                },
                {
                    "rera_number": "PRM/KA/RERA/1251/446/PR/190415/002456",
                    "project_name": "Brigade Orchards",
                    "developer_name": "Brigade Enterprises",
                    "locality": "Yelahanka",
                    "project_status": "On-Going",
                    "project_type": "Integrated Township",
                    "total_units": 2400,
                    "sold_units": 1800,
                    "unsold_units": 600,
                    "possession_date": "2026-06-30",
                },
                {
                    "rera_number": "PRM/KA/RERA/1251/446/PR/200310/002891",
                    "project_name": "Sobha Dream Gardens",
                    "developer_name": "Sobha Limited",
                    "locality": "Yelahanka New Town",
                    "project_status": "On-Going",
                    "project_type": "Residential Apartment",
                    "total_units": 1152,
                    "sold_units": 980,
                    "unsold_units": 172,
                    "possession_date": "2025-09-30",
                },
                {
                    "rera_number": "PRM/KA/RERA/1251/446/PR/210512/003102",
                    "project_name": "Godrej Woodscape",
                    "developer_name": "Godrej Properties",
                    "locality": "Yelahanka",
                    "project_status": "New Launch",
                    "project_type": "Residential Apartment",
                    "total_units": 840,
                    "sold_units": 320,
                    "unsold_units": 520,
                    "possession_date": "2027-12-31",
                },
                {
                    "rera_number": "PRM/KA/RERA/1251/446/PR/220118/003388",
                    "project_name": "Adarsh Lumina",
                    "developer_name": "Adarsh Developers",
                    "locality": "Yelahanka Satellite Town",
                    "project_status": "On-Going",
                    "project_type": "Residential Apartment",
                    "total_units": 480,
                    "sold_units": 380,
                    "unsold_units": 100,
                    "possession_date": "2025-12-31",
                },
                {
                    "rera_number": "PRM/KA/RERA/1251/446/PR/220601/003512",
                    "project_name": "Mantri Tranquil",
                    "developer_name": "Mantri Developers",
                    "locality": "Yelahanka",
                    "project_status": "Ready To Move",
                    "project_type": "Residential Apartment",
                    "total_units": 384,
                    "sold_units": 375,
                    "unsold_units": 9,
                    "possession_date": "2024-03-31",
                },
                {
                    "rera_number": "PRM/KA/RERA/1251/446/PR/230215/003744",
                    "project_name": "Salarpuria Sattva Misty Charm",
                    "developer_name": "Salarpuria Sattva Group",
                    "locality": "Yelahanka",
                    "project_status": "New Launch",
                    "project_type": "Residential Apartment",
                    "total_units": 720,
                    "sold_units": 180,
                    "unsold_units": 540,
                    "possession_date": "2028-06-30",
                },
            ],
            "Devanahalli": [
                {
                    "rera_number": "PRM/KA/RERA/1251/446/PR/190812/002534",
                    "project_name": "Prestige Finsbury Park",
                    "developer_name": "Prestige Estates Projects",
                    "locality": "Devanahalli",
                    "project_status": "On-Going",
                    "project_type": "Residential Apartment",
                    "total_units": 1248,
                    "sold_units": 900,
                    "unsold_units": 348,
                    "possession_date": "2026-09-30",
                },
                {
                    "rera_number": "PRM/KA/RERA/1251/446/PR/200224/002812",
                    "project_name": "Brigade Xanadu",
                    "developer_name": "Brigade Enterprises",
                    "locality": "Devanahalli",
                    "project_status": "On-Going",
                    "project_type": "Residential Villa",
                    "total_units": 320,
                    "sold_units": 280,
                    "unsold_units": 40,
                    "possession_date": "2025-06-30",
                },
            ],
        }
        projects = data.get(market_name, data.get("Yelahanka", []))
        for p in projects:
            p.update(meta)
        return projects

    def _playwright_scrape(self, market_name: str) -> tuple[list[dict], list]:
        """
        T-1062: Playwright form-interaction fallback for POST-failing markets.
        Launches headless Chromium, fills the RERA portal search form via dropdown
        select, submits, and parses the HTML response. Also extracts session cookie
        for downstream detail scout (T-1063).

        Only attempted if market_name is in RERA_USE_PLAYWRIGHT_MARKETS settings.
        Returns ([], []) on any failure — caller falls through to hardcoded seed.
        """
        if market_name not in RERA_USE_PLAYWRIGHT_MARKETS:
            logger.debug(f"[RERA][Playwright] {market_name} not in Playwright markets — skipping")
            return [], []

        loc = RERA_PLAYWRIGHT_LOCALITY_VALUES.get(market_name)
        if not loc:
            logger.debug(f"[RERA][Playwright] No locality values for {market_name}")
            return [], []

        district_val, subdistrict_val = loc
        logger.info(f"[RERA][Playwright] Launching browser for {market_name} ({district_val}/{subdistrict_val})")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("[RERA][Playwright] playwright not installed — skipping fallback")
            return [], []

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
        except ImportError:
            PlaywrightTimeout = Exception

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
                )
                ctx = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="en-IN",
                )
                page = ctx.new_page()
                page.set_default_timeout(_PW_NAVIGATE_TIMEOUT)

                # Step 1: Navigate to the search form to establish session
                try:
                    page.goto(f"{self.BASE_URL}/viewAllProjects", wait_until="domcontentloaded", timeout=_PW_NAVIGATE_TIMEOUT)
                except PlaywrightTimeout:
                    logger.warning(f"[RERA][Playwright] {market_name}: navigation timed out")
                    browser.close()
                    return [], []
                page.wait_for_timeout(_PW_FORM_FILL_DELAY)

                # Step 2: Fill district dropdown by label
                district_selector = "select[name='district']"
                try:
                    page.select_option(district_selector, district_val)
                except PlaywrightTimeout:
                    logger.warning(f"[RERA][Playwright] {market_name}: district dropdown '{district_val}' not found")
                    browser.close()
                    return [], []
                page.wait_for_timeout(_PW_FORM_FILL_DELAY)

                # Step 3: Fill subdistrict dropdown
                subdistrict_selector = "select[name='subdistrict']"
                page.select_option(subdistrict_selector, subdistrict_val)
                page.wait_for_timeout(_PW_DROPDOWN_DELAY)

                # Step 4: Also set taluk if the field exists
                try:
                    taluk_selector = "select[name='taluk']"
                    page.select_option(taluk_selector, subdistrict_val)
                except Exception:
                    pass  # taluk might auto-populate or be absent

                # Step 5: Click Search button
                try:
                    page.click("input[type='submit'], button[type='submit'], input[name='btn1']")
                    page.wait_for_load_state("networkidle", timeout=_PW_NAVIGATE_TIMEOUT)
                except PlaywrightTimeout:
                    logger.warning(f"[RERA][Playwright] {market_name}: search submission timed out")
                    browser.close()
                    return [], []
                page.wait_for_timeout(_PW_RESULTS_DELAY)

                # Step 6: Parse the results HTML
                html = page.content()

                # Step 7: Extract cookies from browser context for T-1063
                pw_raw_cookies = ctx.cookies()
                browser.close()

                projects = self._parse_html_table(html, market_name)
                if not projects:
                    logger.warning(f"[RERA][Playwright] 0 projects parsed for {market_name}")
                    return [], []

                # Mark projects with playwright path metadata
                for p in projects:
                    p["data_source"] = "rera_karnataka_live"
                    p["scraped_at"] = datetime.now().isoformat()
                    p["extraction_path"] = "playwright_fallback"

                # T-1063: Convert Playwright cookies to requests-compatible format
                pw_cookies_req = []
                session_cookie_value = ""
                for c in pw_raw_cookies:
                    pw_cookies_req.append(_FakeCookie(
                        name=c.get("name", ""),
                        value=c.get("value", ""),
                        domain=c.get("domain", ".karnataka.gov.in"),
                        path=c.get("path", "/"),
                    ))
                    if c.get("name", "").lower() in ("session", "jsessionid", "iplanetdirectorypro"):
                        session_cookie_value = c.get("value", "")

                # T-1063: Save session cookie to separate checkpoint for detail scout
                if session_cookie_value:
                    try:
                        cp = Checkpointer()
                        cp.save(market_name, "rera_session", {"session_cookie": session_cookie_value})
                    except Exception as exc:
                        logger.debug(f"[RERA][Playwright] Session checkpoint save failed (non-fatal): {exc}")

                return projects, pw_cookies_req

        except Exception as exc:
            logger.warning(f"[RERA][Playwright] Browser automation failed for {market_name}: {exc}")
            return [], []


def scrape_market_standalone(market_name: str = "Yelahanka"):
    scraper = RERAKarnatakaScraper()
    projects, _cookies = scraper.scrape_market(market_name)

    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "outputs",
        market_name.lower(),
    )
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = os.path.join(output_dir, f"rera_projects_{timestamp}.json")
    scraper.save_to_json(projects, output_path)

    print(f"\n{'=' * 55}")
    print(f"RERA SCRAPE — {market_name.upper()}")
    print(f"{'=' * 55}")
    print(f"Projects found : {len(projects)}")
    live = [p for p in projects if p.get("data_source") == "rera_karnataka_live"]
    print(f"Live data      : {len(live)}  (fallback: {len(projects) - len(live)})")
    print(f"Output         : {output_path}")
    if projects:
        print("\nSample (first 5):")
        for p in projects[:5]:
            print(
                f"  {p.get('rera_number', 'N/A')[:40]:<42} | {p.get('project_name', '')[:30]:<32} | {p.get('developer_name', '')[:25]}"
            )
    return projects


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RERA Karnataka Scraper")
    parser.add_argument(
        "--market",
        default="Yelahanka",
        choices=["Yelahanka", "Devanahalli", "Hebbal"],
        help="Micro-market to scrape",
    )
    args = parser.parse_args()
    logger.add("logs/rera_scraper.log", rotation="10 MB")
    scrape_market_standalone(args.market)
