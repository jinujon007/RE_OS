---
title: GDVEstimator IGR Integration Pattern
date: 2026-06-02
category: docs/solutions/design-patterns/
module: utils/irr_model.py
problem_type: design_pattern
component: service_object
severity: high
applies_when:
  - Estimating market PSF for GDV calculations using live transaction data
  - The data source may have insufficient records for statistical reliability
  - The caller needs to know which data source was used for audit transparency
  - PSF values from external sources may contain data errors requiring sanity bounds
tags:
  - gdv
  - igr
  - psf
  - irr-model
  - caching
  - source-tracking
  - median
  - fallback
related_components:
  - database
  - background_job
---

# GDVEstimator IGR Integration Pattern

## Context

`GDVEstimator` in `utils/irr_model.py` previously used listing PSF from portal scouts
(99acres, MagicBricks) as the GDV sell-price input. Listing PSF reflects asking prices
and runs 15–25% above actual registered transaction prices. Sprint 39 (T-477) wired
IGR transaction data from the `igr_transactions` table into `GDVEstimator` as the
primary PSF source, retaining listing PSF as a caller-provided fallback.

The design decision to use IGR over listing PSF was confirmed in the Sprint 39 planning
session: "IGR records reflect actual sale deed prices; listing PSF is an ask price"
(session history). The 15% gap matters because at ₹120 Cr land cost, a 15% PSF
overestimate translates to ~₹18 Cr GDV error — enough to flip a 22% IRR to 19%.

## Guidance

Use `PERCENTILE_CONT(0.5)` (median, not average) over a 90-day window with a 5-record
minimum floor. Return a source label for every outcome so callers and audit logs have
full transparency on which PSF was used.

```python
# utils/irr_model.py
class GDVEstimator:
    MIN_IGR_RECORDS = 5           # floor for statistical reliability
    _CACHE_TTL_S = 900            # 15-min TTL for positive results
    _NODATA_CACHE_TTL_S = 300     # 5-min TTL for negative results (re-check sooner)
    _PSF_MIN_SANITY = 500         # ₹500/sqft floor — below = data error
    _PSF_MAX_SANITY = 50000       # ₹50,000/sqft ceiling

    def _query_igr_median_psf(self, market: str) -> tuple[float | None, int, str]:
        row = conn.execute(text("""
            SELECT
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY transaction_psf) AS median_psf,
                COUNT(*) AS record_count
            FROM igr_transactions
            WHERE market ILIKE :market
              AND registration_date >= NOW() - INTERVAL '90 days'
              AND transaction_psf IS NOT NULL
              AND transaction_psf > 0
        """), {"market": f"%{market}%"}).fetchone()

        if row and row[1] >= self.MIN_IGR_RECORDS:
            validated = self._validate_psf(float(row[0]))
            if validated is not None:
                return (validated, int(row[1]), "igr_portal")
            else:
                return (None, int(row[1]), "sanity_rejected")
        elif row:
            return (None, int(row[1]), "insufficient_records")
        else:
            return (None, 0, "no_data")
```

**The `0.0` return design** — when IGR data is insufficient, `estimate()` returns
`psf=0.0`. The caller provides the listing PSF override:

```python
def estimate(self, sellable_area_sqft: float, market: str = "") -> GDVResult:
    igr_psf, igr_count, igr_source = self._query_igr_median_psf(market_safe)
    if igr_psf is not None and igr_count >= self.MIN_IGR_RECORDS:
        psf = igr_psf
    # else psf=0.0 — FeasibilityAnalystTool provides listing PSF as override
    ...
    return GDVResult(sell_psf=psf, igr_source=igr_source, igr_record_count=igr_count, ...)
```

This keeps `GDVEstimator` testable without DB mocking — tests inject any PSF without
needing live `igr_transactions` data.

**Dual TTL cache** — shorter TTL for negative results so the system re-checks after
the next IGR scrape run:

```python
# Positive result (valid PSF found): cache 15 minutes
self._cache[market] = (psf, count, "igr_portal", now + self._CACHE_TTL_S)

# Negative result (no data, insufficient, sanity rejected): cache 5 minutes
self._cache[market] = (None, count, source, now + self._NODATA_CACHE_TTL_S)
```

**Audit trail** via `log_igr_lookup()` — non-fatal write to `agent_runs`:

```python
log_igr_lookup(market="Yelahanka", source="igr_portal", record_count=12, psf=6450.0)
# Writes: INSERT INTO agent_runs (agent_name, task_type, micro_market, status, metadata)
# Non-fatal: caller proceeds regardless of write failure
```

## Why This Matters

Median over average provides outlier resistance — a single ₹8,000 PSF commercial
re-registration does not corrupt a residential GDV estimate built on 12+ records.

The 5-record floor ensures the median has statistical meaning. With < 5 records, a
single outlier can shift the "median" by 20–30%, making the estimate worse than
listing PSF. Below the floor, listing PSF (ask price) is more reliable than a thin
IGR median.

The 90-day window captures current market conditions without including stale
transactions from prior interest rate cycles. Kaveri data spans years; the 90-day
filter ensures the PSF reflects what buyers are paying today.

The source label cascade enables BD decisions to be audit-ready:
- Board Room Finance Head can cite `"igr_portal (12 records, 90-day median ₹6,450 PSF)"` 
  vs `"listing_psf (fallback — only 3 IGR records)"` 
- The distinction matters for investor due diligence

## When to Apply

Apply this pattern for any financial metric that aggregates rupee-denominated values
from external sources:

1. **Median over average** for price/PSF metrics where outlier transactions exist
2. **Minimum record count floor** before trusting the aggregate (recalibrate floor
   per metric — 5 for PSF, potentially lower for plot registrations)
3. **Sanity bounds** on all currency values (reject < ₹500/sqft, > ₹50,000/sqft)
4. **Dual TTL** — positive results cache longer; negative results cache shorter
   (re-check after next scrape run)
5. **Return 0.0 on insufficient data** so the caller owns the fallback decision

**Recalibrate `MIN_IGR_RECORDS = 5`** for low-volume markets. Devanahalli residential
may have < 5 IGR transactions in any 90-day window — consider reducing to 3 or extending
to 180 days for those specific markets before deploying to production.

## Examples

**Source label cascade — full reference:**

| Return tuple | Condition | Caller action |
|---|---|---|
| `(psf_value, n≥5, "igr_portal")` | Valid median from live IGR data | Use as primary GDV PSF |
| `(None, n<5, "insufficient_records")` | IGR data exists but thin | Fall back to listing PSF |
| `(None, 0, "no_data")` | Zero IGR records in 90-day window | Fall back to listing PSF |
| `(None, n, "sanity_rejected")` | PSF outside ₹500–₹50,000 | Fall back to listing PSF, log warning |
| `(None, 0, "table_unavailable")` | DB error or missing table | Fall back to listing PSF, log error |

**Test pattern — no DB required:**
```python
def test_gdv_estimate_insufficient_igr(monkeypatch):
    monkeypatch.setattr(
        GDVEstimator, "_query_igr_median_psf",
        lambda self, m: (None, 3, "insufficient_records")
    )
    est = GDVEstimator()
    result = est.estimate(sellable_area_sqft=50000, market="Yelahanka")
    assert result.sell_psf == 0.0            # caller must provide listing PSF override
    assert result.igr_source == "insufficient_records"
    assert result.igr_record_count == 3
```

**Market name normalization** — always `.strip().title()` before ILIKE query to
handle inconsistent casing from pitch text (e.g. "YELAHANKA" → "Yelahanka"):
```python
@staticmethod
def _normalize_market(market: str) -> str:
    return market.strip().title()[:100] if market else ""
```

## Related

- [[igr-transaction-ingestion-fallback-chain]] — feeds `igr_transactions` table
- [[months-of-supply-cte-pattern]] — parallel use of Kaveri/IGR data in SQL
- `utils/feasibility.py` — `FeasibilityAnalystTool` is the primary caller; provides
  listing PSF override when `igr_source` indicates insufficient data
- `database/schema.sql` — `igr_transactions` table (Alembic migration 0013)
- `database/schema.sql` — `agent_runs` table (IGR lookup audit trail)
- T-563–T-566 (PENDING) — future GDV inputs (debt service, CP brokerage, construction
  escalation) should follow the same source-label + fallback pattern
