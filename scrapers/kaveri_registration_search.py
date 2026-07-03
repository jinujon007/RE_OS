"""
RE_OS — Kaveri Registration Search
────────────────────────────────────
Scrapes Kaveri portal for recently registered deeds in a given village.

Usage:
    from scrapers.kaveri_registration_search import KaveriRegistrationSearch
    searcher = KaveriRegistrationSearch()
    results = searcher.scan_village("Doddajala", "Bangalore North", days_back=1)
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger
import requests

__all__ = ["KaveriRegistrationSearch"]

KAVERI_SEARCH_URL = "https://kaveri.karnataka.gov.in/registration/search"

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]
_UA_POOL_SIZE = len(_USER_AGENTS)
_UA_COUNTER = 0


class KaveriRegistrationSearch:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._last_request_at: float = 0.0

    def _next_user_agent(self) -> str:
        global _UA_COUNTER
        ua = _USER_AGENTS[_UA_COUNTER % _UA_POOL_SIZE]
        _UA_COUNTER += 1
        return ua

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_at
        if elapsed < 2.0:
            time.sleep(2.0 - elapsed)

    def scan_village(
        self,
        village: str,
        taluk: str | None = None,
        days_back: int = 1,
    ) -> list[dict[str, Any]]:
        self._rate_limit()
        start_date = date.today() - timedelta(days=days_back)
        end_date = date.today()

        headers = {
            "User-Agent": self._next_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://kaveri.karnataka.gov.in",
            "Referer": "https://kaveri.karnataka.gov.in/registration/search",
        }

        form_data: dict[str, str] = {
            "village": village,
            "fromDate": start_date.strftime("%d/%m/%Y"),
            "toDate": end_date.strftime("%d/%m/%Y"),
        }
        if taluk:
            form_data["taluk"] = taluk

        try:
            resp = self._session.post(
                KAVERI_SEARCH_URL,
                data=form_data,
                headers=headers,
                timeout=30,
            )
            self._last_request_at = time.time()
            resp.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 405:
                # Verified 2026-07-03: kaveri.karnataka.gov.in is an Angular SPA
                # (Kaveri 2.0) — /registration/search serves the app shell and
                # rejects form POSTs with 405. This scraper cannot return data
                # until the real JWT-authenticated API endpoint is integrated.
                logger.error(
                    "[KaveriRegistrationSearch] Kaveri 2.0 rejects form POST (405) "
                    "for {} — portal is SPA+JWT; scraper non-functional until real "
                    "API integration (see TASK_QUEUE).",
                    village,
                )
            else:
                logger.warning("[KaveriRegistrationSearch] HTTP error for {}: {}", village, exc)
            return []

        return self._parse_result_page(resp.text, village)

    def _parse_result_page(self, html: str, village: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return []

        rows = table.find_all("tr")
        if len(rows) < 2:
            return []

        results: list[dict[str, Any]] = []
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 6:
                continue
            try:
                doc_no = cells[0].get_text(strip=True)
                reg_date_str = cells[1].get_text(strip=True)
                seller = cells[2].get_text(strip=True)
                buyer = cells[3].get_text(strip=True)
                doc_type = cells[4].get_text(strip=True) if len(cells) > 4 else ""
                property_desc = cells[5].get_text(strip=True) if len(cells) > 5 else ""
                estimated_value = cells[6].get_text(strip=True) if len(cells) > 6 else ""
            except (IndexError, AttributeError):
                continue

            reg_date = None
            try:
                from datetime import datetime
                reg_date = datetime.strptime(reg_date_str, "%d/%m/%Y").date().isoformat()
            except (ValueError, TypeError):
                reg_date = reg_date_str

            survey_no = ""
            property_area = ""
            if property_desc:
                parts = property_desc.split(",")
                for part in parts:
                    p = part.strip()
                    if p and not survey_no and any(c.isdigit() for c in p):
                        survey_no = p
                    if "sq" in p.lower() or "acres" in p.lower() or "acr" in p.lower():
                        property_area = p
                if not survey_no and parts:
                    survey_no = parts[0].strip()

            results.append({
                "doc_no": doc_no,
                "reg_date": reg_date,
                "seller": seller[:500] if seller else "",
                "buyer": buyer[:500] if buyer else "",
                "survey_no": survey_no[:200] if survey_no else "",
                "property_area": property_area[:200] if property_area else "",
                "estimated_value": estimated_value[:200] if estimated_value else "",
                "village": village,
                "doc_type": doc_type,
            })

        return results
