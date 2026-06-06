# Data Lineage — PSF, MoS, and Conflict Detection

## PSF Data Flow

```
Portal (99acres/magicbricks)              IGR Portal (govt)              Kaveri Gazette
        │                                      │                             │
        ▼                                      ▼                             ▼
  portal_scout.py                         igr_karnataka.py             kaveri_gazette_parser.py
        │                                      │                             │
        │  + locality filter                  │  + 90-day window            │  + SRO code mapping
        │  (config/locality_aliases.py)        │                             │
        ▼                                      ▼                             ▼
  ┌──────────────┐                    ┌────────────────┐            ┌──────────────────┐
  │ listings     │                    │ igr_transactions│            │ guidance_values   │
  │ (portal_     │                    │ (live_igr /     │            │ (guidance_value / │
  │  scraped /   │                    │  fallback_igr)  │            │  portal_scraped)  │
  │  seed_       │                    └────────────────┘            └──────────────────┘
  │  estimated)  │                           │                             │
  └──────┬───────┘                           ▼                             │
         │                           ┌────────────────┐                    │
         │                           │ FinancialIntel  │◄───────────────────┘
         │                           │ _load_igr_data()│
         │                           │                 │
         │                           │ Tier selection: │
         │                           │ 1. live_igr     │
         │                           │    (≥5 igr_     │
         │                           │     trans.)     │
         │                           │ 2. guidance_    │
         │                           │    value         │
         │                           │    (≥3 GV rec.) │
         │                           │ 3. listing_only  │
         ▼                           └────────┬────────┘
  ┌──────────────┐                            │
  │ v_market_    │                            │
  │ brief        │                            │  psf_source_quality
  │              │                            │
  │ avg_listing_ │◄─── listings.price_psf     │
  │ psf (Tier 1) │    (no fallback chain)     │
  └──────────────┘                            ▼
                                       ┌──────────────────┐
                                       │ Board Room       │
                                       │ Deal Memo        │
                                       │ Investor Brief   │
                                       └──────────────────┘
                                       
Legend:
  Solid line = live data path
  Dashed = fallback
  ⚠ = GAP: v_market_brief and FinancialIntel diverge
```

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
