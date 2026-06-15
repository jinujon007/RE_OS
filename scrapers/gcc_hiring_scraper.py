"""
RE_OS — GCC Hiring Snapshot Scraper (GATE-94, T-1152)

Weekly snapshot of open job postings per tracked GCC employer at North Bengaluru
office locations. Uses Naukri public search to retrieve posting counts.

Two modes:
  --mode live    : Fetch from Naukri public search (may be blocked)
  --mode inbox   : Parse manually saved search result files in data/gcc_hiring/inbox/

Fallback: if live fetch fails, returns empty list (no crash).
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from loguru import logger

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

# TRACKED_EMPLOYERS lives in config/settings.py to avoid DRY violation.
# This scraper accepts an employers argument — the plugin passes settings value.
# This file's __main__ block uses settings when run standalone.

_RETRY_MAX = 2
_RETRY_BACKOFF = 3.0  # seconds


def _naukri_search_url(company: str) -> str:
    """Build a Naukri search URL for company-specific job count."""
    slug = company.lower().replace(" ", "-")
    return f"https://www.naukri.com/{slug}-jobs-in-bangalore"


def _extract_job_count_from_html(html: str) -> int | None:
    """Extract total job count from Naukri search results page."""
    patterns = [
        r"(\d[\d,]*)\s*jobs\s*found",
        r"Showing\s+\d+\s*-\s*\d+\s*of\s+(\d[\d,]*)",
        r"totalJobs\s*:\s*(\d+)",
        r'"totalCount"\s*:\s*(\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except (ValueError, IndexError):
                pass
    return None


def _fetch_posting_count(
    employer: str,
    hub: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch job posting count for one employer via Naukri public search.

    Retries on transient failures (5xx, connection errors) with exponential backoff.
    Returns dict with employer, hub, posting_count (0 on failure),
    and source metadata.
    """
    close_client = False
    if client is None:
        if not HAS_HTTPX:
            return {
                "employer": employer,
                "hub": hub,
                "posting_count": 0,
                "source": "naukri_search",
                "error": "httpx not installed",
            }
        client = httpx.Client(timeout=15.0, follow_redirects=True)
        close_client = True

    url = _naukri_search_url(employer)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }

    last_error = ""
    for attempt in range(_RETRY_MAX + 1):
        try:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                count = _extract_job_count_from_html(resp.text)
                if count is not None:
                    if close_client:
                        client.close()
                    return {
                        "employer": employer,
                        "hub": hub,
                        "posting_count": count,
                        "source": "naukri_search",
                    }
                last_error = "count not found in HTML"
            else:
                last_error = f"HTTP {resp.status_code}"
                if resp.status_code < 500:
                    break

            if attempt < _RETRY_MAX:
                wait = _RETRY_BACKOFF * (2**attempt)
                logger.info(
                    "[GccHiringScraper] retry {} for {} in {:.0f}s (last: {})",
                    attempt + 1,
                    employer,
                    wait,
                    last_error,
                )
                time.sleep(wait)

        except Exception as exc:
            last_error = str(exc)
            if attempt < _RETRY_MAX:
                time.sleep(_RETRY_BACKOFF * (2**attempt))

    if close_client:
        client.close()
    return {
        "employer": employer,
        "hub": hub,
        "posting_count": 0,
        "source": "naukri_search",
        "error": last_error,
    }


def run_snapshot(
    employers: list[dict[str, str]] | None = None,
    mode: str = "live",
) -> list[dict[str, Any]]:
    """Run a full snapshot across all tracked employers.

    Args:
        employers: List of dicts with 'employer' and 'hub' keys.
                   Defaults to importing from config.settings.GCC_TRACKED_EMPLOYERS.
        mode: 'live' for Naukri fetch, 'inbox' for manual data.

    Returns:
        List of result dicts, each with employer, hub, posting_count, source.
    """
    if employers is None:
        from config.settings import GCC_TRACKED_EMPLOYERS as _EMPLOYERS

        targets = _EMPLOYERS
    else:
        targets = employers
    results: list[dict[str, Any]] = []

    if mode == "inbox":
        return _parse_inbox_files()

    if not HAS_HTTPX:
        logger.warning(
            "[GccHiringScraper] httpx not available — returning empty snapshot"
        )
        for t in targets:
            results.append(
                {
                    "employer": t["employer"],
                    "hub": t["hub"],
                    "posting_count": 0,
                    "source": "naukri_search",
                    "error": "httpx not installed",
                }
            )
        return results

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for t in targets:
            result = _fetch_posting_count(t["employer"], t["hub"], client)
            results.append(result)

    ok = sum(1 for r in results if r.get("posting_count", 0) > 0)
    failed = sum(1 for r in results if r.get("error"))
    logger.info(
        "[GccHiringScraper] snapshot: {} employers, {} OK, {} failed",
        len(results),
        ok,
        failed,
    )
    return results


def _parse_inbox_files() -> list[dict[str, Any]]:
    """Parse manually saved Naukri search result files from data/gcc_hiring/inbox/.

    Expected format: JSON files with list of {employer, hub, posting_count}.
    """
    results: list[dict[str, Any]] = []
    inbox_dir = "data/gcc_hiring/inbox"
    if not os.path.isdir(inbox_dir):
        logger.info("[GccHiringScraper] inbox dir not found: {}", inbox_dir)
        return results

    for fname in sorted(os.listdir(inbox_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(inbox_dir, fname)
        try:
            with open(fpath) as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    item.setdefault("source", "inbox")
                    results.append(item)
            else:
                results.append(
                    {
                        "employer": str(data.get("employer", "unknown")),
                        "hub": str(data.get("hub", "unknown")),
                        "posting_count": int(data.get("posting_count", 0)),
                        "source": "inbox",
                    }
                )
        except Exception as exc:
            logger.warning(
                "[GccHiringScraper] inbox parse failed for {}: {}", fname, exc
            )

    return results


if __name__ == "__main__":
    import sys
    from config.settings import GCC_TRACKED_EMPLOYERS

    mode = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--mode" else "live"
    results = run_snapshot(employers=GCC_TRACKED_EMPLOYERS, mode=mode)
    print(json.dumps(results, indent=2, default=str))
    ok = sum(1 for r in results if r.get("posting_count", 0) > 0)
    failed = sum(1 for r in results if r.get("error"))
    print(
        f"\n{len(results)} employers: {ok} OK, {failed} failed, {sum(r.get('posting_count', 0) for r in results)} total postings"
    )
