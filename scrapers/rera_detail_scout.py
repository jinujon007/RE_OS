"""
RE_OS — RERA Detail Scout
──────────────────────────
Goes deeper than the RERA listing page. Takes project detail URLs captured
by rera_karnataka.py and extracts full project intelligence:
  • Unit mix (2BHK count, 3BHK count, etc.)
  • Project cost and funding details
  • Site area, FSI, wing/block breakdown
  • Promoter address, license numbers
  • Completion stage timeline
  • Plan approval numbers (BDA/BBMP)

The listing scraper gets you the roster. This scout gets you the file.

Model: Groq Scout 17b — handles semi-structured government page layouts
       with multi-section tables better than pure extraction models.

Dedup: A RERA number is the gold-standard canonical ID. If we've already
       deep-dived a project this run, skip it.

Run standalone:
  python scrapers/rera_detail_scout.py --market Yelahanka
  python scrapers/rera_detail_scout.py --rera PRM/KA/RERA/1251/446/PR/180601/001792
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
    CEREBRAS_API_KEY,
    CEREBRAS_BASE_URL,
    CEREBRAS_MODEL,
    GROQ_API_KEY,
    GROQ_CEO_MODEL,
    GEMINI_API_KEY,
    GEMINI_CEO_MODEL,
)
from config.checkpointer import Checkpointer
from scrapers.scout_memory import ScoutMemory


RERA_BASE = "https://rera.karnataka.gov.in"
RERA_DETAIL_URL = f"{RERA_BASE}/viewPromoterProjectDetails"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://rera.karnataka.gov.in/viewAllProjects",
}

DETAIL_EXTRACTION_PROMPT = """\
Extract real estate project details from this RERA Karnataka detail page text.
Return ONLY a JSON object with these exact keys (use null if not found):
  total_units          (integer)
  unit_mix             (object: {"2BHK": int, "3BHK": int, "4BHK": int, "Villa": int, ...})
  site_area_sqft       (number)
  site_area_acres      (number)
  project_cost_crore   (number: total project cost in crores)
  fsi_utilized         (number)
  total_wings          (integer)
  bda_approval_no      (string)
  bbmp_approval_no     (string)
  plan_approval_date   (string: YYYY-MM-DD)
  possession_date      (string: YYYY-MM-DD)
  project_address      (string: full address)
  promoter_address     (string)
  completion_pct       (number: 0-100)
  no_of_floors         (integer)
  amenities            (array of strings: top 10)

Return ONLY the JSON object, no commentary, no markdown fences.

RERA PAGE TEXT:
"""


# ── AI extraction (Groq Scout 17b — better at multi-table gov pages) ──────────


def _ai_extract_detail(text: str) -> dict:
    truncated = text[:4000]
    prompt = DETAIL_EXTRACTION_PROMPT + truncated

    raw = ""
    try:
        import litellm

        if GROQ_API_KEY:
            resp = litellm.completion(
                model=f"groq/{GROQ_CEO_MODEL}",
                api_key=GROQ_API_KEY,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.0,
            )
            raw = resp.choices[0].message.content.strip()
        elif CEREBRAS_API_KEY:
            resp = litellm.completion(
                model=f"openai/{CEREBRAS_MODEL}",
                api_key=CEREBRAS_API_KEY,
                base_url=CEREBRAS_BASE_URL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.0,
            )
            raw = resp.choices[0].message.content.strip()
        elif GEMINI_API_KEY:
            resp = litellm.completion(
                model=GEMINI_CEO_MODEL,
                api_key=GEMINI_API_KEY,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.0,
            )
            raw = resp.choices[0].message.content.strip()
        else:
            return {}
    except Exception as exc:
        logger.warning(f"[RERADetailScout] AI extraction error: {exc}")
        return {}

    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`")
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logger.debug(f"[RERADetailScout] JSON parse failed: {raw[:100]}")
    return {}


# ── Page fetching ─────────────────────────────────────────────────────────────


def _fetch_detail_page_requests(detail_url: str, session: requests.Session) -> str:
    try:
        if "/projectDetails?action=" in detail_url:
            action = detail_url.split("action=", 1)[-1].strip()
            resp = session.post(
                f"{RERA_BASE}/projectDetails", data={"action": action}, timeout=30
            )
        else:
            resp = session.get(detail_url, timeout=30)
        time.sleep(1)
        if resp.status_code == 200:
            return _clean_html(resp.text)
        logger.debug(f"[RERADetailScout] HTTP {resp.status_code} for {detail_url}")
    except requests.exceptions.RequestException as exc:
        logger.debug(f"[RERADetailScout] Request error: {exc}")
    return ""


def _fetch_with_fallbacks(
    url_candidates: list[str], session: requests.Session
) -> tuple[str, str]:
    """Try multiple candidate URLs; return first page with meaningful content."""
    best_text = ""
    best_url = ""
    for url in url_candidates:
        if not url:
            continue
        text = _fetch_detail_page_requests(url, session)
        if len(text) > len(best_text):
            best_text = text
            best_url = url
        if len(text) >= 1000:
            return text, url
    return best_text, best_url


def _fetch_detail_page_playwright(detail_url: str) -> str:
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
            ctx = browser.new_context(user_agent=HEADERS["User-Agent"], locale="en-IN")
            page = ctx.new_page()
            page.set_default_timeout(30_000)
            page.goto(detail_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
            return _clean_html(html)
    except Exception as exc:
        logger.debug(f"[RERADetailScout][Playwright] Failed for {detail_url}: {exc}")
        return ""


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s{3,}", "\n", text)


# ── RERA Detail Scout ─────────────────────────────────────────────────────────


class RERADetailScout:
    """
    Deep-dives into RERA Karnataka project detail pages.
    Enriches RERA listing data with unit mix, costs, approvals, amenities.

    Input: list of RERA projects from checkpoint (must have 'rera_number' + 'detail_url')
    Output: list of enriched project dicts with is_new flag from ScoutMemory
    """

    def __init__(self, market: str, memory: ScoutMemory | None = None):
        self.market = market
        self.memory = memory or ScoutMemory(market)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def scout(
        self, projects: list[dict] | None = None, max_projects: int = 30
    ) -> list[dict]:
        """
        Deep-dive RERA detail pages.
        projects: pre-loaded list from RERA listing scraper; if None, loads from checkpoint.
        max_projects: cap per run to stay within Groq TPM budget.
        """
        if projects is None:
            cp = Checkpointer()
            projects = cp.load(self.market, "rera_scraped") or []

        if not projects:
            logger.warning(
                f"[RERADetailScout] No RERA projects to enrich for {self.market}"
            )
            return []

        # Prioritise projects we haven't detail-scouted yet
        unseen = [
            p
            for p in projects
            if not self.memory.is_known(ScoutMemory.cid_rera(p.get("rera_number", "")))
        ]
        to_scout = unseen[:max_projects]
        logger.info(
            f"[RERADetailScout] {self.market}: "
            f"{len(projects)} projects | {len(unseen)} un-enriched | "
            f"diving into {len(to_scout)}"
        )

        enriched: list[dict] = []
        for project in to_scout:
            result = self._enrich_project(project)
            if result:
                enriched.append(result)
            time.sleep(1.5)

        new, known = self.memory.mark_all(enriched, source="rera_detail")
        logger.info(
            f"[RERADetailScout] {self.market}: "
            f"{len(enriched)} enriched | {len(new)} new detail dives"
        )
        return new + known

    def _enrich_project(self, project: dict) -> dict | None:
        rera_number = project.get("rera_number", "")
        project_name = project.get("project_name", "")
        detail_url = project.get("detail_url", "")

        if not rera_number:
            return None

        candidate_urls = self._build_detail_urls(rera_number, detail_url)
        detail_url = candidate_urls[0]

        logger.info(f"[RERADetailScout] Diving: {project_name} ({rera_number})")

        text, used_url = _fetch_with_fallbacks(candidate_urls, self.session)
        if used_url:
            detail_url = used_url
        if len(text) < 200:
            for url in candidate_urls:
                ptext = _fetch_detail_page_playwright(url)
                if len(ptext) > len(text):
                    text = ptext
                    detail_url = url
                if len(text) >= 1000:
                    break
        nav_only = False
        if len(text) < 1000:
            nav_only = True
            logger.warning(
                f"[RERADetailScout] detail page returned nav-only content for {rera_number}"
            )

        if len(text) < 100:
            logger.debug(f"[RERADetailScout] Insufficient content for {rera_number}")
            return None

        details = _ai_extract_detail(text)
        if nav_only:
            details = {
                "total_units": None,
                "unit_mix": None,
                "site_area_sqft": None,
                "site_area_acres": None,
                "project_cost_crore": None,
                "fsi_utilized": None,
                "total_wings": None,
                "bda_approval_no": None,
                "bbmp_approval_no": None,
                "plan_approval_date": None,
                "possession_date": None,
                "project_address": None,
                "promoter_address": None,
                "completion_pct": None,
                "no_of_floors": None,
                "amenities": None,
            }

        enriched = {
            "cid": ScoutMemory.cid_rera(rera_number),
            "source": "rera_detail",
            "market": self.market,
            "rera_number": rera_number,
            "project_name": project_name,
            "developer": project.get("developer_name", ""),
            "locality": project.get("locality", self.market),
            "project_status": project.get("project_status", ""),
            "detail_url": detail_url,
            "scraped_at": datetime.now().isoformat(),
            # Enriched fields from detail page
            "total_units": details.get("total_units") or project.get("total_units", 0),
            "unit_mix": details.get("unit_mix") or {},
            "site_area_sqft": details.get("site_area_sqft"),
            "site_area_acres": details.get("site_area_acres"),
            "project_cost_crore": details.get("project_cost_crore"),
            "fsi_utilized": details.get("fsi_utilized"),
            "total_wings": details.get("total_wings"),
            "bda_approval_no": details.get("bda_approval_no"),
            "bbmp_approval_no": details.get("bbmp_approval_no"),
            "plan_approval_date": details.get("plan_approval_date"),
            "possession_date": details.get("possession_date")
            or project.get("possession_date"),
            "project_address": details.get("project_address")
            or project.get("locality"),
            "promoter_address": details.get("promoter_address"),
            "completion_pct": details.get("completion_pct"),
            "no_of_floors": details.get("no_of_floors"),
            "amenities": details.get("amenities") or [],
        }
        return enriched

    def _build_detail_urls(self, rera_number: str, detail_url: str = "") -> list[str]:
        """Build ordered candidate detail URLs for resilient fallback."""
        urls: list[str] = []
        if detail_url:
            urls.append(detail_url)

        encoded = rera_number.replace("/", "%2F")
        # Legacy/search endpoints observed in portal flows.
        urls.extend(
            [
                f"{RERA_BASE}/viewPromoterProjectDetails?regNo={encoded}",
                f"{RERA_BASE}/viewProjectDetails?regNo={encoded}",
                f"{RERA_BASE}/viewAllProjectDetails?regNo={encoded}",
                f"{RERA_BASE}/projectViewDetails?regNo={encoded}",
            ]
        )

        # De-dupe preserving order.
        seen = set()
        ordered = []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                ordered.append(u)
        return ordered


# ── Standalone runner ─────────────────────────────────────────────────────────


def scout_market_rera_details(market: str) -> list[dict]:
    memory = ScoutMemory(market)
    scout = RERADetailScout(market, memory)
    results = scout.scout()

    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "outputs",
        market.lower().replace(" ", "_"),
    )
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = os.path.join(output_dir, f"rera_detail_scout_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    new_total = sum(1 for r in results if r.get("is_new"))
    print(f"\n{'=' * 55}")
    print(f"RERA DETAIL SCOUT — {market.upper()}")
    print(f"{'=' * 55}")
    print(f"Enriched projects : {len(results)}")
    print(f"New detail dives  : {new_total}")
    print(f"Output            : {out_path}")
    if results:
        for r in results[:3]:
            mix = r.get("unit_mix") or {}
            print(
                f"  {r.get('rera_number', '?')[:40]:<42} | "
                f"Units: {r.get('total_units', '?')} | "
                f"Mix: {mix}"
            )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RERA Detail Scout")
    parser.add_argument(
        "--market", default="Yelahanka", choices=["Yelahanka", "Devanahalli", "Hebbal"]
    )
    parser.add_argument("--rera", default="", help="Single RERA number to deep-dive")
    args = parser.parse_args()
    logger.add("logs/rera_detail_scout.log", rotation="10 MB")

    if args.rera:
        scout = RERADetailScout(args.market)
        result = scout._enrich_project({"rera_number": args.rera, "project_name": "?"})
        print(json.dumps(result, indent=2, default=str))
    else:
        scout_market_rera_details(args.market)
