---
title: IGR Transaction Ingestion Fallback Chain
date: 2026-06-02
category: docs/solutions/architecture-patterns/
module: scrapers/igr_karnataka.py
problem_type: architecture_pattern
component: tooling
severity: high
applies_when:
  - Scraping a Karnataka government portal that requires form-fill and AJAX intercept
  - The portal has CSRF token requirements and is JS-rendered
  - Multiple scout instances will run in parallel threads
  - SHA-256 dedup is needed to prevent double-ingestion across re-runs
tags:
  - igr
  - scraper
  - fallback-chain
  - dedup
  - rate-limiter
  - karnataka-portal
  - playwright
related_components:
  - service_object
  - background_job
---

# IGR Transaction Ingestion Fallback Chain

## Context

The Karnataka Inspector General of Registration portal
(`kaveri.karnataka.gov.in/registration/search`) is JS-rendered with CSRF token
requirements, making it hostile to standard HTTP clients. Sprint 39 introduced
`scrapers/igr_karnataka.py` to ingest registered sale deed transactions that feed
`GDVEstimator._query_igr_median_psf()` and the `v_market_brief` months_of_supply
calculation. The scraper needed to handle three failure modes: portal unavailable,
Playwright timeout, and POST rejection — while still guaranteeing at least 5 records
for the GDV median floor (`MIN_IGR_RECORDS = 5`).

Two bugs were caught in post-implementation audit (session history): `hashlib` was
imported inside the per-record hot-path via `__import__("hashlib")` instead of at
module level, and SHA-256 dedup IDs were truncated to 16 hex characters (collision
risk). Both were fixed before GATE-25.

## Guidance

Use a three-tier fallback chain: Playwright AJAX intercept → POST with 2-retry
backoff → hardcoded fallback. Tag every record with its source at the collection
point, not downstream. Use a per-instance rate limiter, never a module-global one.

```python
# scrapers/igr_karnataka.py
class IGRTransactionScout:
    def run(self, market: str = "Yelahanka", days_back: int = 30) -> list[dict]:
        # Tier 1: Playwright — no retry (expensive browser launch)
        records = self._scrape_via_playwright(meta, from_str, to_str)
        if records:
            for r in records:
                r["source"] = "portal_playwright"
            return records

        # Tier 2: Direct POST — 2 retries with 6s backoff
        for attempt in range(2):
            records = self._scrape_via_post(meta, from_str, to_str)
            if records:
                for r in records:
                    r["source"] = "portal_post"
                return records
            if attempt == 0:
                time.sleep(MIN_REQUEST_INTERVAL_S * 2)  # 6s before retry

        # Tier 3: Hardcoded fallback — guarantees >=5 records for GATE-25
        fb = _fallback_transactions(market)
        for r in fb:
            r["source"] = "fallback"
        logger.warning(f"[IGRScout] Portal unreachable — using {market} fallback data")
        return fb
```

**CSRF token:** Include `__RequestVerificationToken` as an empty string — the portal
rejects requests where the key is absent, even when the value is empty:

```python
payload = {
    "district": meta["district"],
    "taluk": meta["taluk"],
    "fromDate": from_str,
    "toDate": to_str,
    "__RequestVerificationToken": "",  # key required even when empty
}
```

**Per-instance rate limiter** prevents cross-market timer interference when scouts
run in parallel threads. Module-global state is a concurrency bug when ThreadPoolExecutor
spawns multiple instances:

```python
class RateLimiter:
    def __init__(self, interval_s: float = 3.0):
        self._interval = interval_s
        self._last_ts = 0.0
        self._lock = threading.Lock()  # per-instance, not module-level

    def wait(self) -> None:
        with self._lock:
            elapsed = time.time() - self._last_ts
            if elapsed < self._interval:
                time.sleep(self._interval - elapsed)
            self._last_ts = time.time()
```

**SHA-256 dedup** — use 32 hex characters, keyed on `survey_no:registration_date`.
16-character truncation was a prior bug (session history); 32 chars reduces collision
probability to negligible while keeping ID fits within standard VARCHAR(32):

```python
dedup_key = f"{survey_no}:{reg_date}"
dedup_id = hashlib.sha256(dedup_key.encode()).hexdigest()[:32]

conn.execute(text("""
    INSERT INTO igr_transactions (id, market, survey_no, ...)
    VALUES (:id, :market, :survey_no, ...)
    ON CONFLICT DO NOTHING
"""), {"id": dedup_id, ...})
```

## Why This Matters

IGR transaction PSF is the closest proxy to actual buyer-paid price in a Bengaluru
micro-market. Listing PSF (from 99acres/MagicBricks) runs 15–25% above transaction
reality. For a 2-acre site at ₹120 Cr land cost, a 15% PSF overestimate translates
to ~₹18 Cr GDV error — enough to flip a 22% IRR to 19%, changing the go/no-go
decision. Without a reliable IGR ingestor, GDVEstimator falls back to listing PSF
permanently.

The per-instance rate limiter matters because `ThreadPoolExecutor` used in the
parallel market fan-out creates multiple `IGRTransactionScout` instances
simultaneously. A module-global `_last_request_time` causes false sleeps in all
instances whenever any one instance makes a request, serializing what should be
independent parallel scouts.

## When to Apply

Apply this pattern for any new Karnataka government portal scraper with these
characteristics:
- JS-rendered with DataTables AJAX response
- CSRF token requirement (include key even if value is empty)
- Parallel invocation across markets

The **30-day default window** is the safe upper bound for the IGR portal — it times
out silently beyond ~90 days. Use `days_back=90` only when bootstrapping historical
baseline data for a new market. Do not use `days_back=365` for routine runs.

**Revisit `MIN_IGR_RECORDS = 5`** in `utils/irr_model.py` if Devanahalli residential
ingestion remains thin — fewer than 5 registrations per 90-day window is plausible
for low-volume sub-markets. Consider reducing to 3 or extending to 180 days for those
specific markets.

## Examples

**Before — module-global rate limiter (concurrency bug):**
```python
# BAD: module level — shared across all scout instances
_last_request_time = 0.0

def _throttle():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < 3.0:
        time.sleep(3.0 - elapsed)
    _last_request_time = time.time()
```

**After — per-instance lock:**
```python
# GOOD: instance level — each market scout has its own timer
class IGRTransactionScout:
    def __init__(self):
        self.rate_limiter = RateLimiter(interval_s=3.0)
```

**Source label reference for downstream queries:**

| `source` value | Meaning |
|---|---|
| `portal_playwright` | Live data via Playwright AJAX intercept |
| `portal_post` | Live data via direct POST |
| `fallback` | Hardcoded realistic records (GATE-25 safety net) |

Filter fallback records out of PSF calculations:
```sql
SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY transaction_psf)
FROM igr_transactions
WHERE market ILIKE '%Yelahanka%'
  AND source != 'fallback'   -- exclude synthetic baseline data
  AND registration_date >= NOW() - INTERVAL '90 days'
```

## Related

- [[gdv-estimator-igr-integration]] — consumes IGR transaction data for GDV PSF
- [[kaveri-portal-6-tier-fallback-chain]] — parallel portal scraping pattern
- `utils/irr_model.py` — `GDVEstimator._query_igr_median_psf()` (primary consumer)
- `database/schema.sql` — `igr_transactions` table (Alembic migration 0013)
