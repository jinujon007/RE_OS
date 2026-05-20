"""
RE_OS — RERA Karnataka Scraper
────────────────────────────────
Pulls all registered projects from RERA Karnataka portal.
URL: https://rera.karnataka.gov.in

Strategy (as of 2026-05-14 live inspection):
  Portal form: POST /projectViewDetails with district + subdistrict (taluk)
  Response: full HTML page, all rows rendered server-side (no JS required)
  Parse: BeautifulSoup table extraction — no Playwright needed for listing

Market → district/taluk mapping confirmed via live portal:
  Yelahanka  → district="Bengaluru Urban",  subdistrict="Yelahanka"     (165 projects)
  Hebbal     → district="Bengaluru Urban",  subdistrict="Bengaluru North" (734 projects)
  Devanahalli→ district="Bengaluru  Rural", subdistrict="Devanahalli"   (317 projects)

Note: listing page has project name, developer, RERA no, status, type, dates.
      Unit counts and PSF require individual project detail pages (future phase).

Run standalone: python scrapers/rera_karnataka.py --market Yelahanka
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import argparse
from datetime import datetime
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import MARKET_RERA_CONFIG


class RERAKarnatakaScraper:
    """
    Scrapes RERA Karnataka project listing via direct HTTP POST.
    No Playwright or JS rendering required — portal returns server-side HTML.
    """

    BASE_URL = "https://rera.karnataka.gov.in"
    SEARCH_URL = f"{BASE_URL}/projectViewDetails"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": "https://rera.karnataka.gov.in/viewAllProjects",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def scrape_market(self, market_name: str) -> list[dict]:
        """
        Main entry point. Returns list of normalized project dicts for the market.
        Falls back to hardcoded sample data if portal unreachable.
        """
        logger.info(f"Starting RERA scrape for: {market_name}")

        config = MARKET_RERA_CONFIG.get(market_name)
        if not config:
            logger.warning(f"  No RERA config for '{market_name}' — using fallback")
            return self._fallback_rera_data(market_name)

        projects = self._post_search(
            config["district"], config["subdistrict"], market_name
        )

        if not projects:
            logger.warning("  Portal returned 0 results — using fallback sample data")
            return self._fallback_rera_data(market_name)

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
        return unique

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
        payload = {
            "project": "",
            "firm": "",
            "appNo": "",
            "regNo": "",
            "district": district,
            "subdistrict": subdistrict,
            "btn1": "Search",
        }

        try:
            resp = self.session.post(self.SEARCH_URL, data=payload, timeout=60)
            resp.raise_for_status()

            size_mb = len(resp.content) / 1024 / 1024
            logger.info(
                f"  [POST] {district}/{subdistrict} → {resp.status_code}, {size_mb:.1f} MB"
            )

            return self._parse_html_table(resp.text, market_name)

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
                "source": "rera_karnataka_live",
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
            "source": "fallback_sample",
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

    def save_to_json(self, projects: list, output_path: str):
        with open(output_path, "w") as f:
            json.dump(projects, f, indent=2, default=str)
        logger.info(f"Saved {len(projects)} projects to {output_path}")


def scrape_market_standalone(market_name: str = "Yelahanka"):
    scraper = RERAKarnatakaScraper()
    projects = scraper.scrape_market(market_name)

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
    live = [p for p in projects if p.get("source") == "rera_karnataka_live"]
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
