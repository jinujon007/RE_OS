# Data Lineage — PSF, MoS, and Conflict Detection

## PSF Data Flow — Unified (Migration 0023)

```
  ┌──────────────────────────┐     ┌─────────────────────────┐     ┌──────────────────┐
  │ kaveri_registrations     │     │ guidance_values         │     │ listings         │
  │ (actual sale deeds)      │     │ (govt circle rates)     │     │ (portal_scraped  │
  │ transaction_amount /     │     │ guidance_value_psf      │     │  / seed_         │
  │  area_sqft = trans PSF   │     │                         │     │  estimated)      │
  └───────────┬──────────────┘     └───────────┬─────────────┘     └────────┬─────────┘
              │                               │                            │
              ▼                               ▼                            ▼
      Tier 1: ≥5 rows                  Tier 2: ≥3 rows               Tier 3: ≥5 live rows
      median(trans_psf)                median(gv_psf)                AVG(price_psf) excl seed
              │                               │                            │
              └───────────┬───────────────────┘────────────────────────────┘
                          │                        Tier 4: AVG(price_psf) all rows (≥1)
                          ▼
              ┌──────────────────────────────────────────────────────┐
              │           v_market_brief (migration 0023)            │
              │                                                      │
              │  psf_source_tier  │  psf_source_label                │
              │  ────────────────┼────────────────────────────────   │
              │  1               │  kaveri_registration              │
              │  2               │  guidance_value                   │
              │  3               │  live_listing                     │
              │  4               │  seed_listing                     │
              │                                                      │
              │  avg_listing_psf = COALESCE(tier1, tier2, tier3,     │
              │                     tier4) across 4-tier cascade     │
              └──────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌─────────────────────────────────────────┐
              │ FinancialIntel._load_igr_data()          │
              │ (separate 3-tier cascade for IRR):      │
              │   1. live_igr (igr_transactions, ≥5)    │
              │   2. guidance_value (gv, ≥3)            │
              │   3. listing_only (sell_psf)             │
              │ psf_source_quality field                │
              └─────────────────────────────────────────┘
                          │
                          ▼
              ┌─────────────────────────────────────────┐
              │ Board Room  │  Deal Memo  │  Investor   │
              │ cites       │  cites      │  Brief      │
              │ psf_source  │  psf_source │  cites      │
              │ tier+label  │  tier+label │  source     │
              └─────────────────────────────────────────┘
```

### PSF Tier Selection Rules (v_market_brief)

| Tier | Source Table | Min Rows | Statistic | Label |
|------|-------------|----------|-----------|-------|
| 1    | kaveri_registrations | ≥5 | PERCENTILE_CONT(0.5) transaction PSF | kaveri_registration |
| 2    | guidance_values (data_source IN igr_gazette,portal_scraped) | ≥3 | PERCENTILE_CONT(0.5) guidance_value_psf | guidance_value |
| 3    | listings (data_source != seed_estimated) | ≥5 | AVG(price_psf) | live_listing |
| 4    | listings (all, including seed) | ≥1 | AVG(price_psf) | seed_listing |

The cascade uses SQL `COALESCE`: the first tier meeting its minimum row count wins.
This ensures v_market_brief.avg_listing_psf always agrees with FinancialIntel's
_igr_source_for hierarchy (best available data wins).

## MoS Data Flow

```
  kaveri_registrations                  rera_projects
        │                                    │
        │  COUNT / 12                        │  absorption_pct
        │  (per micro_market)                │  total_units
        ▼                                    ▼
  ┌────────────┐                    ┌────────────────┐
  │ kaveri_    │                    │ rera absorption │
  │ stats      │                    │ fallback        │
  └──────┬─────┘                    └────────┬───────┘
         │                                   │
         ▼                                   ▼
  ┌──────────────────────────────────────────────┐
  │            v_market_brief (view)             │
  │                                              │
  │  Tier 1: kaveri_registrations ≥12 → raw MoS │
  │  Tier 2: kaveri_registrations <12, >0 → cap │
  │  Tier 3: no kaveri → absorption fallback    │
  │                                              │
  │  Output: months_of_supply (LEAST(raw, 120)) │
  │        mos_unrestricted (before cap)        │
  │        mos_quality (source label)            │
  └──────────────────────────────────────────────┘
```

## Conflict Detection Data Flow

```
  agent_memories
        │
        │  SELECT pairs with same LEFT(fact, 50)
        │  and numeric gap > 20%
        ▼
  detect_conflicts(market)
        │
        ├── write conflict row (fact_type='conflict')
        ├── Discord #alerts (if configured)
        └── GET /api/memory/explorer?fact_type=conflict

  Key dependency: seed data must have identical
  first-50 characters for LEFT-join matching.
```

## Seed Data Lifecycle

```
  database/seed_listings.py
        │
        ├── INSERT INTO listings (source='seed_estimated')
        ├── SAVEPOINT isolation per row
        ├── --seed CLI arg for deterministic output
        └── DataQualityMonitor.check_seed_staleness()
              │
              ├── Live scrape ≥10 → flag "remove_seed"
              └── Seed age >7d → flag "re_scrape_needed"
```

## Freshness Monitoring

```
  ingest_log (per-plugin scrape records)
        │
        ├── utils/data_freshness.get_source_status()
        │     └── GET /api/data/freshness (cached 60s)
        │
        ├── utils/data_quality.DataQualityMonitor
        │     ├── freshness_score()
        │     ├── stale_flag()
        │     ├── check_psf_divergence()
        │     ├── check_seed_staleness()
        │     └── config/slos.all_slo_status()
        │
        └── GET /api/health
              ├── .data_quality.freshness
              ├── .data_quality.slo_pass/fail
              └── .data_quality.seed_stale_warnings
```
