---
title: Kaveri Portal 6-Tier Fallback Chain
date: 2026-06-02
category: docs/solutions/integration-issues/
module: scrapers/kaveri_karnataka.py
problem_type: integration_issue
component: tooling
severity: high
symptoms:
  - kaveri.karnataka.gov.in returns 403 or TLS handshake failure for standard requests
  - Playwright times out after 30s during peak portal load
  - kaveri2 mirror returns empty response body on ~40% of attempts
  - IGR GV API returns empty JSON array even when data exists in the portal UI
  - Scraper silently falls through to hardcoded 2024-25 government estimates
root_cause: config_error
resolution_type: code_fix
tags:
  - kaveri
  - karnataka-portal
  - tls-fingerprint
  - scrapling
  - fallback-chain
  - guidance-values
related_components:
  - background_job
---

# Kaveri Portal 6-Tier Fallback Chain

## Problem

`kaveri.karnataka.gov.in` consistently rejects standard Python `requests` connections
via JA3 TLS fingerprint detection. No single scraping method achieves sufficient
reliability to serve as sole data source for guidance values (circle rates) in
North Bengaluru micro-markets.

## Symptoms

- `requests.get("https://kaveri.karnataka.gov.in/GVSearch")` returns HTTP 403 or
  `SSLError` (TLS handshake failure) on ~100% of attempts
- Playwright timeout (`>30s`) during business hours when portal is under load
- `kaveri2.karnataka.gov.in` mirror returns empty response body ~40% of the time
- `kaveri.karnataka.gov.in/api/gv/search` returns `[]` even when guidance values
  exist in the portal UI
- Scraper falls through to hardcoded 2024-25 government estimates (₹2,800–₹6,500
  PSF for Yelahanka) without logging which tier failed

## What Didn't Work

- **Standard `requests` GET/POST:** Blocked at TLS layer by JA3 fingerprint detection.
  The portal identifies non-browser client hellos and returns 403 before serving content.
- **Playwright as sole method:** Timeout failure rate too high. Portal's DataTables AJAX
  call takes 25–35s, exceeding the 30s Playwright timeout during peak hours.
- **kaveri2 mirror as sole method:** Undocumented mirror, no SLA, ~40% empty response
  rate. Will go offline without notice.
- **IGR GV API as sole method:** Endpoint returns `[]` for valid district/taluk queries
  with no consistent pattern. Behavior undocumented and appears to vary by load.

## Solution

Six-tier ordered fallback chain in `scrapers/kaveri_karnataka.py`, with every tier
logging its source label so operators always know which tier succeeded:

```python
def scrape_guidance_values(self, market_name: str) -> list[dict]:
    # Tier 1: Scrapling TLS spoof (~70% success rate)
    records = self._scrape_gv_with_scrapling(taluk, meta)
    if records:
        logger.info(f"[KaveriScraper][Scrapling TLS][{market_name}] {len(records)} records")
        return records  # source: "scrapling_tls"

    # Tier 2: kaveri2.karnataka.gov.in mirror (requests POST)
    records = self._scrape_gv_from_mirror(taluk, meta)
    if records:
        return records  # source: "mirror"

    # Tier 3: IGR GV API (kaveri.karnataka.gov.in/api/gv/search)
    records = self._scrape_gv_from_igr_api(taluk, meta)
    if records:
        return records  # source: "igr_api"

    # Tier 4: Playwright AJAX intercept (legacy)
    records = self._scrape_gv_with_playwright(taluk, meta)
    if records:
        return records  # source: "kaveri_portal" (Playwright)

    # Tier 5: Direct POST (legacy)
    records = self._scrape_gv_via_post(taluk, meta)
    if records:
        return records  # source: "kaveri_portal" (POST)

    # Tier 6: Hardcoded fallback — ALWAYS logs at WARNING, never silent
    logger.warning(
        f"[KaveriScraper] All GV sources failed for {market_name} — using fallback data"
    )
    return self._fallback_guidance_values(market_name)  # source: "fallback_sample"
```

**Scrapling TLS spoof (Tier 1):**

```python
from scrapling.fetchers import Fetcher  # guarded by _SCRAPLING_OK flag

def _scrape_gv_with_scrapling(self, taluk: str, meta: dict) -> list[dict]:
    if not _SCRAPLING_OK:
        logger.debug("[KaveriScraper][Scrapling] Not available — skipping")
        return []
    page = Fetcher.get(GV_SEARCH_URL, stealthy_headers=True, follow_redirects=True)
    html = getattr(page, "html", None) or str(page)
    if len(html) > 1000:
        records = self._parse_gv_html(html, meta)
        for r in records:
            r["source"] = "scrapling_tls"
        return records
    return []
```

**Never-silent fallback (Tier 6):** Always `logger.warning` before returning hardcoded
data. This is enforced so downstream consumers and operators can distinguish live Kaveri
data from 2024-25 government estimates.

**Avoid mutating the global fallback dict** — `_fallback_guidance_values` works on a
copy, not the module-level `_FALLBACK_GV` dict (session history fix: in-place
`setdefault` was corrupting test isolation between runs):

```python
def _fallback_guidance_values(self, market_name: str) -> list[dict]:
    records = [dict(r) for r in _FALLBACK_GV.get(market_name, [])]  # copy, not mutate
    for r in records:
        r.setdefault("source", "fallback_sample")
    return records
```

## Why This Works

Scrapling's `stealthy_headers=True` randomizes the JA3 TLS fingerprint on each request,
mimicking a real browser's TLS client hello. The portal's bot detection relies on
fingerprint constancy — standard `requests` always presents the same JA3 hash, which is
trivial to block. Scrapling achieves ~70% success where standard requests achieves 0%.

The remaining 30% Scrapling failures are caught by Tiers 2–5 in descending order of
reliability. Tier 6 (hardcoded) is a permanent safety net that guarantees the pipeline
never returns an empty list for Yelahanka, Devanahalli, or Hebbal guidance values.

## Prevention

- **Source-label every record at the collection point** (not downstream). Each tier
  sets a `source` key before returning. Downstream DB queries can then filter out
  `fallback_sample` data for PSF calculations that require live guidance values.
- **Test tier availability** before deploying Kaveri scraper changes:
  `python scrapers/kaveri_karnataka.py --market Yelahanka` — check the log for which
  tier succeeded.
- **When adding a new government portal scraper:** Assume JA3 blocking is present.
  Start with Scrapling as Tier 1, not as a fallback of last resort.
- **Keep `_SCRAPLING_OK` import guard** — Scrapling is an optional dependency. Never
  hard-import it at module level. The guard ensures the scraper degrades gracefully to
  Tier 2+ on environments where Scrapling isn't installed.
- **Never copy the global fallback dict in-place.** Use `[dict(r) for r in ...]` to
  avoid cross-test state contamination.

## Related Issues

- CLAUDE.md `## Current State — Open Issues`: "Kaveri GV Portal Unreachable" —
  historical open issue this chain resolves.
- `kilo_output/audits/kaveri_silent_fails.md` — pre-T-483 audit (2026-05-17) that
  documented the original 2–3 tier chain. Superseded by this doc.
- [[igr-transaction-ingestion-fallback-chain]] — same portal, registration data path
- T-483 — task that implemented Tiers 1–3 (Scrapling + mirror + IGR API)
