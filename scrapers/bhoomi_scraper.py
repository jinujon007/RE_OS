"""Karnataka Bhoomi RTC Integration (Sprint 56 — Land Intelligence)

Fetches RTC (Record of Rights, Tenancy and Crops) data from the Karnataka
Bhoomi portal (landrecords.karnataka.gov.in) via HTTP POST.

Portal strategy:
  - Endpoint: https://landrecords.karnataka.gov.in/rtcReportData
  - Method: HTTP POST with form params: district_id, taluk_id, survey_no
  - Response: JSON with owner_name, land_nature, khata_no, area_guntas, encumbrances
  - On portal unreachable: returns {"bhoomi_status": "unavailable"} — never crashes
  - Retry: 2 retries with 3s backoff for transient failures

Usage:
  python scrapers/bhoomi_scraper.py --survey 45/2 --market Devanahalli
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from loguru import logger

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_BHOOMI_URL = "https://landrecords.karnataka.gov.in/rtcReportData"
_TIMEOUT = 15
_MAX_RETRIES = 2
_RETRY_DELAY_S = 3
_SURVEY_NO_RE = re.compile(r"^[\d]+/[a-zA-Z0-9]+$")

_MARKET_DIST_TALUK = {
    "Yelahanka": {"district_id": 1, "taluk_id": 5},
    "Devanahalli": {"district_id": 1, "taluk_id": 6},
    "Hebbal": {"district_id": 1, "taluk_id": 5},
}


def _lookup_district_taluk(market: str) -> dict:
    s = market.strip().lower()
    for k, v in _MARKET_DIST_TALUK.items():
        if k.lower() == s:
            return v
    logger.warning("[BhoomiScraper] Unknown market '{}' — using default district/taluk", market)
    return {"district_id": 1, "taluk_id": 5}


def _do_request(params: dict) -> str:
    """Single HTTP POST attempt. Returns raw response text or raises."""
    data = urllib.parse.urlencode(params).encode("ascii")
    req = urllib.request.Request(
        _BHOOMI_URL,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/plain, */*",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch(survey_no: str, market: str | None = None) -> dict:
    """Fetch RTC data from Karnataka Bhoomi portal.

    Args:
        survey_no: Survey number (e.g. '45/2', '101/1A').
                   Must match pattern: digits/digits-or-letters.
        market: Market name for district/taluk lookup. Optional.

    Returns:
        Dict with land record fields, or {"bhoomi_status": "unavailable"}
        on portal failure.

    Raises:
        ValueError: If survey_no format is invalid.
    """
    sn = survey_no.strip()
    if not _SURVEY_NO_RE.match(sn):
        logger.warning("[BhoomiScraper] Invalid survey_no format: '{}'", sn)
        return {"bhoomi_status": "unavailable", "error": f"invalid survey_no format: {sn}"}
    dt = _lookup_district_taluk(market) if market else {"district_id": 1, "taluk_id": 5}
    params = {
        "district_id": str(dt["district_id"]),
        "taluk_id": str(dt["taluk_id"]),
        "survey_no": sn,
    }
    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            raw = _do_request(params)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                logger.warning("[BhoomiScraper] Rate limited (429) — returning unavailable")
                return {"bhoomi_status": "unavailable", "error": "rate_limited"}
            last_error = exc
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_S * (attempt + 1))
            continue
        except Exception as exc:
            last_error = exc
            logger.warning("[BhoomiScraper] Attempt {}/{} failed: {}", attempt + 1, _MAX_RETRIES + 1, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_S * (attempt + 1))
            continue
        break
    else:
        logger.warning("[BhoomiScraper] Portal unreachable after {} attempts: {}", _MAX_RETRIES + 1, last_error)
        return {"bhoomi_status": "unavailable"}

    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("[BhoomiScraper] Non-JSON response: {}", raw[:200])
        return {"bhoomi_status": "unavailable"}

    if isinstance(body, dict) and body.get("error"):
        logger.warning("[BhoomiScraper] Portal error: {}", body.get("error"))
        return {"bhoomi_status": "unavailable"}

    if isinstance(body, dict) and body.get("status") == "404":
        return {"bhoomi_status": "unavailable"}

    return _parse_response(body, survey_no, market)


def _parse_response(body: dict | list, survey_no: str, market: str | None) -> dict:
    """Parse Bhoomi portal JSON response into standardised dict."""
    record = body if isinstance(body, dict) else {"raw": str(body)[:500]}

    land_nature = (record.get("land_nature") or "").strip().lower()
    if land_nature not in ("agricultural", "converted", "revenue", "notional", "unknown"):
        land_nature = "unknown"

    encumbrances = record.get("encumbrances")
    if isinstance(encumbrances, str):
        try:
            encumbrances = json.loads(encumbrances)
        except (json.JSONDecodeError, ValueError):
            encumbrances = [encumbrances]
    if not isinstance(encumbrances, list):
        encumbrances = [] if encumbrances is None else [str(encumbrances)]

    return {
        "survey_no": survey_no,
        "market": market or "",
        "owner_name": (record.get("owner_name") or record.get("owner", "")).strip(),
        "land_nature": land_nature,
        "khata_no": (record.get("khata_no") or record.get("khata", "")).strip(),
        "area_guntas": _parse_guntas(record.get("area_guntas") or record.get("area", 0)),
        "encumbrances": encumbrances,
        "bhoomi_status": "live",
        "bhoomi_fetched_at": None,
    }


def _parse_guntas(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Karnataka Bhoomi RTC Fetcher")
    parser.add_argument("--survey", default="45/2", help="Survey number")
    parser.add_argument("--market", default="Devanahalli", help="Market name")
    args = parser.parse_args()
    result = fetch(args.survey, args.market)
    print(json.dumps(result, indent=2, default=str))
