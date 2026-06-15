"""
RE_OS — DC Conversion Application Tracker (GATE-94, T-1153)

Tracks land-use conversion (DC) application status from Bhoomi/landrecords
portal. DC conversion is the process of changing agricultural land to
residential/commercial use — a key leading indicator for pre-RERA supply.

Two modes:
  --mode live    : Scrape Bhoomi portal for DC application status (reuses
                   BhoomiScraper session pattern)
  --mode inbox   : Parse manually saved files from data/dc_conversions/inbox/

Records are matched to parcels via survey_no → parcel linker.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
from datetime import datetime
from typing import Any

from loguru import logger

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

_RETRY_MAX = 2
_RETRY_BACKOFF = 3.0

# ── Market village mapping for DC conversion monitoring ─────────────────────
# Only these villages trigger Discord alerts on conversion.
# Cross-reference: Kaveri jurisdiction data lives in data/kaveri_jurisdiction/.
# These lists should be kept in sync with re_os_market_kaveri_map.json for
# survey-level parcel linking.
MARKET_VILLAGES: dict[str, list[str]] = {
    "Yelahanka": [
        "Venkatala",
        "Yelahanka",
        "Atturu",
        "Kodigehalli",
        "Singanayakanahalli",
        "Anjanapura",
    ],
    "Devanahalli": [
        "Devanahalli",
        "Sulibele",
        "Bettahalasuru",
        "Hunasamaranahalli",
        "Vishwanathapura",
        "Nandagudi",
    ],
    "Hebbal": [
        "Byatarayanapura",
        "Jakkur",
        "Nagawara",
        "Thanisandra",
        "HBR Layout",
        "Kogilu",
    ],
}

# Bhoomi portal DC conversion endpoint
_BHOOMI_DC_URL = "https://landrecords.karnataka.gov.in/dcConversionStatus"
_COVERED_MARKETS = {"yelahanka", "devanahalli", "hebbal"}


def _parse_dc_html(html: str) -> list[dict[str, Any]]:
    """Parse DC conversion table rows from Bhoomi portal HTML response.

    Expected columns: app_no, village, survey_no, extent, from_use, to_use,
    applicant, status, date.
    """
    records: list[dict[str, Any]] = []
    rows = re.findall(r"<tr[^>]*>.*?</tr>", html, re.DOTALL)
    start_idx = 0
    if rows and re.search(r"<th[^>]*>", rows[0], re.IGNORECASE):
        start_idx = 1
    for row_html in rows[start_idx:]:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.DOTALL)
        if len(cells) >= 6:
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            rec = {
                "application_no": clean[0] if len(clean) > 0 else "",
                "village": clean[1] if len(clean) > 1 else "",
                "survey_no": clean[2] if len(clean) > 2 else "",
                "extent_acres": _parse_extent(clean[3]) if len(clean) > 3 else None,
                "from_use": clean[4] if len(clean) > 4 else "",
                "to_use": clean[5] if len(clean) > 5 else "",
                "applicant_name": clean[6] if len(clean) > 6 else "",
                "status": clean[7] if len(clean) > 7 else "unknown",
                "application_date": _parse_date(clean[8]) if len(clean) > 8 else None,
            }
            if rec["application_no"]:
                records.append(rec)
    return records


def _parse_extent(val: str) -> float | None:
    try:
        return float(val.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _parse_date(val: str) -> str | None:
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(val.strip(), fmt).date().isoformat()
        except (ValueError, AttributeError):
            continue
    return val.strip() if val.strip() else None


def _fetch_dc_applications(
    village: str,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch DC conversion applications for a specific village from Bhoomi portal.

    Retries on transient failures (5xx, connection errors) with exponential backoff.
    """
    close_client = False
    if client is None:
        if not HAS_HTTPX:
            return []
        client = httpx.Client(timeout=15.0, follow_redirects=True)
        close_client = True

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"village": village, "action": "search"}
    last_error = ""

    for attempt in range(_RETRY_MAX + 1):
        try:
            resp = client.post(_BHOOMI_DC_URL, headers=headers, data=data)
            if resp.status_code == 200:
                parsed = _parse_dc_html(resp.text)
                if close_client:
                    client.close()
                return parsed
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code < 500:
                break
        except Exception as exc:
            last_error = str(exc)

        if attempt < _RETRY_MAX:
            wait = _RETRY_BACKOFF * (2**attempt)
            logger.info(
                "[DCScraper] retry {} for village {} in {:.0f}s (last: {})",
                attempt + 1,
                village,
                wait,
                last_error,
            )
            time.sleep(wait)

    if close_client:
        client.close()
        logger.info(
            "[DCScraper] fetch failed for village {} after {} retries: {}",
            village,
            _RETRY_MAX,
            last_error,
        )
    return []


def run_scan(
    villages: list[str] | None = None,
    mode: str = "live",
) -> list[dict[str, Any]]:
    """Scan DC conversion applications across specified villages.

    Args:
        villages: List of village names to scan. Defaults to all MARKET_VILLAGES.
        mode: 'live' for Bhoomi portal, 'inbox' for manual data.

    Returns:
        List of DC conversion record dicts.
    """
    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()

    if mode == "inbox":
        return _parse_inbox_files()

    if not HAS_HTTPX:
        logger.warning("[DCScraper] httpx not available — returning empty")
        return []

    targets = villages or list(set(v for vs in MARKET_VILLAGES.values() for v in vs))

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for village in targets:
            records = _fetch_dc_applications(village, client)
            for rec in records:
                app_no = rec.get("application_no", "")
                if app_no and app_no not in seen:
                    seen.add(app_no)
                    all_records.append(rec)

    logger.info(
        "[DCScraper] scan complete: {} villages, {} records",
        len(targets),
        len(all_records),
    )
    return all_records


def _parse_inbox_files() -> list[dict[str, Any]]:
    """Parse manually saved DC conversion files from data/dc_conversions/inbox/.

    Supports CSV and JSON formats.
    """
    results: list[dict[str, Any]] = []
    inbox_dir = "data/dc_conversions/inbox"
    if not os.path.isdir(inbox_dir):
        logger.info("[DCScraper] inbox dir not found: {}", inbox_dir)
        return results

    for fname in sorted(os.listdir(inbox_dir)):
        fpath = os.path.join(inbox_dir, fname)
        try:
            if fname.endswith(".json"):
                with open(fpath) as f:
                    data = json.load(f)
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            elif fname.endswith(".csv"):
                with open(fpath, newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        results.append(row)
        except Exception as exc:
            logger.warning("[DCScraper] inbox parse failed for {}: {}", fname, exc)

    return results


def market_for_village(village: str) -> str | None:
    """Return the RE_OS market name for a village, or None if not covered."""
    v_lower = village.lower().strip()
    for market, villages in MARKET_VILLAGES.items():
        if any(v_lower == v.lower() for v in villages):
            return market
    return None


if __name__ == "__main__":
    import sys

    mode = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--mode" else "live"
    results = run_scan(mode=mode)
    print(json.dumps(results, indent=2, default=str))
    print(f"\nTotal: {len(results)} DC conversion records")
