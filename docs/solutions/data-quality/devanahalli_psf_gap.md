# Devanahalli PSF Gap: ₹10,148 (Listing) vs ₹3,612 (IGR)

**Investigated: 2026-06-05 | Task: T-947 | R2 audit: 2026-06-05**

## Finding

The 2.8× gap is **entirely caused by mis-geocoded listings**. Devanahalli had **0 valid portal listings** in the database. Both entries were from other micro-markets (Electronic City, Kormangala).

## Evidence

### Listings in DB (both were mis-geocoded — now purged)

| Source | PSF | Locality | Project | Verdict |
|--------|-----|----------|---------|---------|
| magicbricks | ₹10,148 | Electronic City, Bangalore | Mahendra Arto Helix | Mis-geocoded — Electronic City is 40km from Devanahalli |
| nobroker | None | Kormangala | Independent house | Mis-geocoded — Kormangala is in South Bangalore |

Both listings returned by portals for "Devanahalli" search URLs, but portals returned out-of-market results.

### IGR Data (ground truth)

| Source | Median PSF | Record Count | Quality |
|--------|------------|-------------|---------|
| `igr_transactions` (90-day window) | ₹3,613 | 12 records | `live_igr` — actual registered sale prices |
| `guidance_values` (kaveri gazette, SRO 118) | ₹1,124 | 395+ records | `guidance_value` — government-set minimum |

**Important:** The ₹1,124 gazette median is significantly lower than the ₹3,613 transaction median. This is normal:
- Gazette guidance values are deliberately conservative (minimum for stamp duty computation)
- Transaction prices reflect market premiums for developed land near the airport
- The 3.2× gap between these two government sources is smaller than the 2.8× listing-vs-transaction gap
- This means FinancialIntel should prefer igr_transactions median when ≥5 records exist, falling back to guidance_values

## Why the Gap is Normal

| Source | Type | Typical vs Market | Direction |
|--------|------|-------------------|-----------|
| Listing PSF | Asking price | Above market | Aspirational, negotiable |
| IGR transaction | Deeded price | Near/at market | Often under-reported for stamp duty |
| IGR guidance value | Government floor | Below market | Conservative minimum |
| Market fallback | v_market_brief avg | Best estimate | From aggregated data |

## Fixes Applied (R1 → R2)

1. **Locality filter** added to `portal_scout.py:_scout_source()` — post-normalization filter discards listings whose `locality` field doesn't match known market aliases. Aliases externalized to `config/locality_aliases.py`.

2. **PSF hierarchy implemented** in `financial_intel.py:_load_igr_data()` — now queries `guidance_values` table when `igr_transactions` has <5 records. `psf_source_quality` set to `"guidance_value"` when ≥3 GV records exist. Full 3-tier fallback: `live_igr` → `guidance_value` → `listing_only`.

3. **Bad data purged** — 2 mis-geocoded Devanahalli listings deleted from DB. `v_market_brief.avg_listing_psf` for Devanahalli now shows `NULL`.

4. **Logging upgraded** — mis-geocoded listing filter logs at `WARNING` level (was `DEBUG`), and increments `scraper_locality_filtered` counter for metrics/monitoring.

## Remaining Risks (R2)

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| New portals or sources bypass the locality filter | Low | Medium | IngestEngine's PortalPlugin always calls portal_scout.PortalScout which includes the filter |
| Locality aliases become stale as city expands | Medium | Low | Aliases in `config/locality_aliases.py` — data change, no code deploy; add periodic review to ops |
| IGR transaction count falls below 5 (seasonal dip) | Medium | Low | Falls through to `guidance_value` tier — still informative but lower confidence |

## Impact on Board Room / Intel Pipeline

- Devanahalli `avg_listing_psf` = `NULL` (no valid listings) — view returns correct signal
- `FinancialIntel` uses IGR transaction median (₹3,613) as psf_source_quality="live_igr"
- Board Room sees accurate Devanahalli economics: lower PSF but also lower land acquisition costs
- `mos_quality` column in v_market_brief tells downstream consumers whether MoS is based on kaveri data or fallback
