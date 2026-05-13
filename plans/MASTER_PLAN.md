# RE_OS — MASTER PLAN
## Bloomberg Terminal for Indian Real Estate
**Owner:** Jinu Joshi / Land & Life Space (LLS)
**Phase 1 City:** Bengaluru (North Corridor)
**Vision:** Market-leading RE intelligence terminal for India
**Created:** 2026-05-13
**Status:** Living document — update after every planning session

---

## Document Map

| Sub-Plan | File | What |
|----------|------|------|
| Architecture + Phase 1 | `plans/bloomberg_re_terminal_plan.md` | Full stack, Bengaluru hardening, UI, India expansion |
| Data Moat | `plans/data_moat_deep_plan.md` | Bhoomi land records + infrastructure pipeline |
| Developer Intelligence | `plans/developer_intelligence_plan.md` | A-grade developer tracking, launches, price hikes |
| News Intelligence | `plans/news_intelligence_plan.md` | Macro news, policy events, govt reforms |
| **This file** | `plans/MASTER_PLAN.md` | Single source of truth, execution order |

---

## The Vision in One Sentence

> RE_OS gives a real estate professional the same information edge that Bloomberg Terminal gives a bond trader — every project, every developer, every policy move, every land signal, structured and actionable, before anyone else has it.

---

## What We Are Building — Full Module Map

```
RE_OS BLOOMBERG TERMINAL
│
├── DATA LAYER (inputs)
│   ├── Module 1: RERA Karnataka Scraper          [BUILT — activate]
│   ├── Module 2: Kaveri Registrations Scraper    [BUILT — calibrate]
│   ├── Module 3: Listings Scraper (99a/MB/NB)    [STUB — build]
│   ├── Module 4: Bhoomi Land Records Scraper     [PLANNED]
│   ├── Module 5: Infrastructure Pipeline Scraper [PLANNED]
│   ├── Module 6: Developer News Scraper          [PLANNED]
│   ├── Module 7: BSE/MCA Filings Scraper         [PLANNED]
│   └── Module 8: News Aggregator (RSS+API)       [PLANNED]
│
├── INTELLIGENCE LAYER (processing)
│   ├── Agent 1: Scraper Agent                    [BUILT]
│   ├── Agent 2: Analyst Agent                    [BUILT — upgrade]
│   ├── Agent 3: CEO Agent                        [BUILT — upgrade]
│   ├── Agent 4: Developer Agent                  [PLANNED]
│   └── Agent 5: News Agent                       [PLANNED]
│
├── SIGNALS ENGINE (pure Python, no LLM)
│   ├── Absorption velocity (units/month)         [PLANNED]
│   ├── Price momentum (PSF change MoM/QoQ)       [PLANNED]
│   ├── Supply pressure (months of inventory)     [PLANNED]
│   ├── GV gap trend (market vs circle rate)      [PLANNED]
│   ├── Developer delivery score                  [PLANNED]
│   ├── Infrastructure proximity score            [PLANNED]
│   └── Title clean score (Bhoomi)                [PLANNED]
│
├── STORAGE LAYER
│   ├── PostgreSQL + PostGIS                      [BUILT]
│   ├── TimescaleDB extension (price time series) [PLANNED]
│   └── Redis (cache + alert queue)               [BUILT]
│
├── TERMINAL UI LAYER
│   ├── FastAPI backend                           [PLANNED]
│   ├── Screen 1: Market Overview                 [PLANNED]
│   ├── Screen 2: Market Deep Dive                [PLANNED]
│   ├── Screen 3: Project Detail                  [PLANNED]
│   ├── Screen 4: Developer Scorecard             [PLANNED]
│   ├── Screen 5: Developer Competitor Matrix     [PLANNED]
│   ├── Screen 6: Land Acquisition Intel          [PLANNED]
│   ├── Screen 7: Infrastructure Alpha Map        [PLANNED]
│   ├── Screen 8: News Feed                       [PLANNED]
│   ├── Screen 9: Policy Tracker                  [PLANNED]
│   └── Screen 10: Morning Brief / Alerts Feed    [PLANNED]
│
└── ALERT LAYER
    ├── Alert Engine (rule-based triggers)        [PLANNED]
    ├── Delivery: Terminal UI                     [PLANNED]
    ├── Delivery: Slack webhook                   [PLANNED]
    └── Delivery: WhatsApp Business API           [FUTURE]
```

---

## Database — Full Schema Map

### Existing Tables (Built)
| Table | Purpose | Status |
|-------|---------|--------|
| `micro_markets` | Geographic anchor — Yelahanka, Devanahalli, Hebbal etc. | ✅ Seeded |
| `developers` | Developer profiles + grades | ✅ Basic |
| `rera_projects` | RERA-registered projects | ✅ 9 rows, growing |
| `project_snapshots` | Quarterly absorption snapshots | ✅ Schema only |
| `listings` | 99acres/MagicBricks listings | ✅ Schema only |
| `kaveri_registrations` | Actual property transactions | ✅ Fallback data |
| `guidance_values` | Govt circle rates | ✅ Fallback data |
| `regulatory_zones` | FAR/setback rules by zone | ✅ Schema only |
| `overlay_constraints` | Water bodies, reserves, buffers | ✅ Schema only |
| `infrastructure_pipeline` | Infra projects (basic) | ✅ Schema only |

### New Tables to Add
| Table | Purpose | Plan File |
|-------|---------|-----------|
| `land_parcels` | Bhoomi survey records | data_moat_deep_plan.md |
| `land_mutations` | Ownership transfer history | data_moat_deep_plan.md |
| `land_encumbrances` | Mortgages, attachments, orders | data_moat_deep_plan.md |
| `infrastructure_projects` | Full infra project details | data_moat_deep_plan.md |
| `metro_stations` | Individual metro stations + influence zones | data_moat_deep_plan.md |
| `infra_market_proximity` | Pre-computed spatial joins | data_moat_deep_plan.md |
| `cdp_zones` | BDA CDP 2031 zoning layer | data_moat_deep_plan.md |
| `developer_quarterly_stats` | Listed + unlisted dev performance | developer_intelligence_plan.md |
| `developer_launches` | New project/phase launch records | developer_intelligence_plan.md |
| `project_price_history` | Every PSF change per project | developer_intelligence_plan.md |
| `developer_events` | Developer news structured events | developer_intelligence_plan.md |
| `news_articles` | All ingested news articles | news_intelligence_plan.md |
| `policy_events` | Structured govt policy actions | news_intelligence_plan.md |
| `news_themes` | Clustered macro themes | news_intelligence_plan.md |
| `news_theme_articles` | Theme-article junction | news_intelligence_plan.md |

---

## Execution Phases — Master Sequence

### PHASE 0 — Fix & Activate (Current State → Working System)
**Goal:** Stop running on fallback data. Get real live data into DB. Zero blockers.

| Task | File | Priority |
|------|------|----------|
| Fix `_upsert_project` ON CONFLICT — add `micro_market_id` + `developer_id` to UPDATE SET | `utils/db_organizer.py` | P0 |
| Delete empty artifact row from `rera_projects` | SQL | P0 |
| Add `CEREBRAS_API_KEY` + `GEMINI_API_KEY` to `.env` | `.env` | P0 |
| `docker compose build agents` → rebuild with Playwright | Docker | P0 |
| `docker compose up -d` → validate `[Playwright] Intercepted N rows` in logs | Docker | P0 |
| Run pipeline → confirm 50+ live RERA projects in DB | Run | P0 |
| Calibrate Kaveri scraper form field names (manual portal inspection) | `scrapers/kaveri_karnataka.py` | P1 |

**Exit criteria:** Pipeline runs daily, pulls live RERA + Kaveri data, CEO brief shows real numbers.

---

### PHASE 1 — Intelligence Upgrade (Reports Worth Acting On)
**Goal:** Reports that an experienced RE analyst would actually use.

| Task | File | Priority |
|------|------|----------|
| Add 6 analyst signals: velocity, momentum, delivery score, supply pressure, GV gap trend, launch lag | `agents/analyst_agent.py` | P0 |
| Upgrade CEO report to 6-section structured brief | `agents/ceo_agent.py` | P0 |
| Build 99acres listings scraper (Playwright) | `scrapers/listings_scraper.py` | P1 |
| Add MagicBricks listings scraper | `scrapers/listings_scraper.py` | P1 |
| Add `project_price_history` — write on every RERA upsert when PSF changes | `utils/db_organizer.py` | P1 |
| Add TimescaleDB extension to `project_snapshots` | `database/schema.sql` | P2 |
| Activate Devanahalli + Hebbal markets (RERA seeding) | Pipeline run | P2 |

**Exit criteria:** Morning brief is 6 sections, shows absorption velocity + price momentum + developer scorecard + land signals.

---

### PHASE 2 — Developer Intelligence (Know Every Move Before It's Public)
**Goal:** Track Grade-A developers like Bloomberg tracks listed companies.

| Task | File | Priority |
|------|------|----------|
| Add columns to `developers` table (NSE symbol, CIN, delivery score, stress flag) | `database/schema.sql` | P0 |
| Create `developer_quarterly_stats`, `developer_launches`, `project_price_history`, `developer_events` tables | `database/schema.sql` | P0 |
| Manually seed 10 Grade-A developers | SQL / seed script | P0 |
| Build `scrapers/developer_news.py` — NewsAPI + Google News per developer | `scrapers/developer_news.py` | P1 |
| Build `agents/developer_agent.py` — `DeveloperScorecardTool` + `NewsClassifierTool` | `agents/developer_agent.py` | P1 |
| Build `scrapers/bse_filings.py` — BSE/NSE quarterly results PDF parser | `scrapers/bse_filings.py` | P2 |
| Add Developer Scorecard + Competitor Matrix to CEO brief | `agents/ceo_agent.py` | P1 |
| Price hike alert: if PSF change >4% → fire `developer_events` + Slack | `utils/db_organizer.py` | P1 |

**Exit criteria:** Every morning brief includes Developer Moves section. Price hikes detected within 24hr of RERA update.

---

### PHASE 3 — News Intelligence (Policy = Market Mover)
**Goal:** Know about every policy event, govt reform, and macro shift before it prices into the market.

| Task | File | Priority |
|------|------|----------|
| Create `news_articles`, `policy_events`, `news_themes` tables | `database/schema.sql` | P0 |
| Build `scrapers/news_aggregator.py` — RSS + Google News + NewsAPI | `scrapers/news_aggregator.py` | P0 |
| Build `agents/news_agent.py` — classify, score, extract policy events | `agents/news_agent.py` | P1 |
| Build `utils/news_organizer.py` — DB upserts for news tables | `utils/news_organizer.py` | P1 |
| Add 2-hour news scrape job to scheduler | `config/scheduler.py` | P1 |
| Manually seed `policy_events` — current repo rate, stamp duty, GST, RERA status | SQL | P0 |
| Manually seed `policy_calendar` — MPC dates, Budget, RERA board, BDA review | SQL | P0 |
| Inject news summary into CEO morning brief | `agents/ceo_agent.py` | P1 |
| Build `scrapers/govt_portals.py` — RERA Karnataka notifications, BDA, RBI circulars | `scrapers/govt_portals.py` | P2 |

**Exit criteria:** Morning brief has Policy Status + Top News section. RBI rate change detected and impact scored within 2 hours.

---

### PHASE 4 — Data Moat: Infrastructure Alpha (2-Year Price Signal)
**Goal:** Know which corridors will appreciate before the market prices it in.

| Task | File | Priority |
|------|------|----------|
| Create `infrastructure_projects`, `metro_stations`, `infra_market_proximity`, `cdp_zones` tables | `database/schema.sql` | P0 |
| Manually seed BMRCL Phase 2B + Phase 3 stations (23 stations) with lat/lon | SQL / seed script | P0 |
| PostGIS `ST_Buffer` — compute 500m/1km/2km influence zones for each station | `utils/spatial_analyzer.py` | P0 |
| Spatial join: RERA projects + land parcels within metro zones | `utils/spatial_analyzer.py` | P0 |
| Manually seed NHAI North BLR projects (NH-44, STRR, PRR) | SQL | P1 |
| Build `scrapers/infra_pipeline.py` — BMRCL press releases (daily), NHAI tracker (weekly) | `scrapers/infra_pipeline.py` | P1 |
| LLM PDF parser — Gemini 2.5 Flash for DPR documents | `scrapers/infra_pipeline.py` | P2 |
| Load BDA CDP 2031 shapefile into PostGIS `cdp_zones` | `utils/infra_organizer.py` | P1 |
| Add infrastructure proximity to analyst + CEO brief | `agents/analyst_agent.py` | P1 |

**Exit criteria:** Terminal shows which RERA projects are metro-adjacent. CEO brief includes infrastructure alpha section.

---

### PHASE 5 — Data Moat: Land Records (Acquisition Intelligence)
**Goal:** For any parcel, return title score + encumbrance + NA status + comparable PSF in 30 seconds.

| Task | File | Priority |
|------|------|----------|
| Create `land_parcels`, `land_mutations`, `land_encumbrances` tables | `database/schema.sql` | P0 |
| Build `scrapers/bhoomi_karnataka.py` — RTC + mutation scraper | `scrapers/bhoomi_karnataka.py` | P0 |
| Seed initial parcels from Kaveri registration `survey_number` field | `utils/infra_organizer.py` | P1 |
| Compute clean title score per parcel (EC + mutations + NA status) | `utils/spatial_analyzer.py` | P1 |
| Build `agents/land_agent.py` — Bhoomi queries, title scoring, acquisition signals | `agents/land_agent.py` | P1 |
| Bhoomi EC on-demand scraper (trigger per LLS request) | `scrapers/bhoomi_karnataka.py` | P2 |
| Terminal screen: Land Acquisition Intel (parcel map + title score + PSF overlay) | `api/` + frontend | P2 |

**Exit criteria:** LLS team can look up any survey number and get title score + NA status + metro proximity + comparable PSF.

---

### PHASE 6 — Terminal UI (The Product Layer)
**Goal:** Web dashboard that looks and feels like a professional terminal.

| Task | File | Priority |
|------|------|----------|
| Build FastAPI backend — 8 endpoints (markets, projects, developers, alerts, run trigger) | `api/main.py` | P0 |
| Screen 1: Market Overview (RAG status cards per market) | `api/templates/` | P0 |
| Screen 2: Market Deep Dive (project table + price chart + developer heatmap) | `api/templates/` | P0 |
| Screen 3: Project Detail (RERA card + unit mix + comparables) | `api/templates/` | P1 |
| Screen 4: Developer Scorecard | `api/templates/` | P1 |
| Screen 5: Competitor Matrix | `api/templates/` | P1 |
| Screen 6: News Feed + Policy Tracker | `api/templates/` | P1 |
| Screen 7: Infrastructure Alpha Map (PostGIS render) | `api/templates/` | P2 |
| Screen 8: Land Acquisition Intel | `api/templates/` | P2 |
| WebSocket: real-time alert push | `api/ws.py` | P2 |
| Alert Engine: rule-based triggers → DB + Slack | `alerts/engine.py` | P1 |
| Slack webhook integration | `alerts/slack.py` | P1 |

**Exit criteria:** LLS team uses terminal daily instead of WhatsApp groups and broker calls for market intelligence.

---

### PHASE 7 — Expand to All Bengaluru (East + South)
**Goal:** Full city coverage. North BLR is Phase 1. Same RERA + Kaveri. Schema reuse 100%.

| Task | Priority |
|------|----------|
| Add East BLR markets: Whitefield, Sarjapur, Marathahalli, KR Puram | P1 |
| Add South BLR markets: Electronic City, Bannerghatta, Kanakpura Road | P1 |
| Add West BLR markets: Tumkur Road, Peenya, Rajajinagar | P2 |
| Add Central BLR markets: Indiranagar, Koramangala, Jayanagar | P2 |
| Seed all RERA projects for new markets | P1 |
| Add city-wide competitor matrix (all developers, all markets) | P1 |

---

### PHASE 8 — India Expansion (City by City)

| Priority | City | RERA Portal | Kaveri Equivalent | Effort |
|----------|------|-------------|------------------|--------|
| P1 | Hyderabad | RERA Telangana | IGRS Telangana | Medium |
| P2 | Pune | MahaRERA | IGR Maharashtra | Medium |
| P3 | Chennai | TNRERA | Registration Dept TN | Medium |
| P4 | NCR (Gurugram + Noida) | HRERA + UPRERA | Two portals | High |
| P5 | Mumbai | MahaRERA | IGR Maharashtra | High |

**Architecture:** Each city = `city_config.py` with portal URLs, market slugs, SRO equivalent. Same pipeline, same schema, different config.

---

## Data Signals — Complete Reference

### Market-Level Signals
| Signal | Formula | Source Tables |
|--------|---------|---------------|
| Absorption rate | `sold_units / total_units * 100` | `rera_projects` |
| Absorption velocity | `(sold_units_now - sold_units_prev) / days * 30` | `project_snapshots` |
| Months of inventory | `unsold_units / monthly_velocity` | `rera_projects` + `project_snapshots` |
| Price momentum | `(avg_psf_now - avg_psf_3mo_ago) / avg_psf_3mo_ago * 100` | `project_price_history` |
| Kaveri-to-asking spread | `(asking_psf - registered_psf) / registered_psf * 100` | `rera_projects` + `kaveri_registrations` |
| GV gap | `(registered_psf - guidance_value_psf) / guidance_value_psf * 100` | `kaveri_registrations` + `guidance_values` |
| New supply pressure | `units_launched_last_90d` | `developer_launches` |
| Registration velocity | `count(kaveri_registrations) per month per market` | `kaveri_registrations` |

### Developer-Level Signals
| Signal | Formula | Source Tables |
|--------|---------|---------------|
| Market share | `developer_units / market_total_units` | `rera_projects` |
| Developer velocity | `units_sold_last_90d / 90 * 30` | `project_snapshots` |
| Delivery score | `on_time_projects / total_completed * 100` | `rera_projects` |
| Inventory coverage | `total_unsold / monthly_velocity` | `rera_projects` + `project_snapshots` |
| Price positioning | `developer_avg_psf / market_avg_psf` | `rera_projects` |
| Financial stress flag | `net_debt / pre_sales > 2.5 OR NCLT case exists` | `developer_quarterly_stats` + `developer_events` |

### Land-Level Signals
| Signal | Formula | Source Tables |
|--------|---------|---------------|
| Clean title score | `(no EC) * 40 + (NA converted) * 30 + (mutations < 4) * 30` | `land_parcels` + `land_encumbrances` |
| Infrastructure proximity | `min(distance to metro_station, infra_project)` | `infra_market_proximity` |
| Comparable PSF | `avg(kaveri_registrations.psf within 500m, last 180d)` | `kaveri_registrations` |
| GV gap (land) | `(comparable_psf - guidance_value_psf) / guidance_value_psf` | `kaveri_registrations` + `guidance_values` |

---

## Alert Rules — Complete Reference

| # | Trigger | Condition | Priority | Delivery |
|---|---------|-----------|----------|---------|
| 1 | New RERA project registered | Any Grade-A developer in target market | P0 | Slack + Terminal |
| 2 | Price hike detected | PSF change > 4% vs last snapshot | P0 | Slack + Terminal |
| 3 | Absorption crosses 80% | Any active project | P1 | Slack + Terminal |
| 4 | Velocity drop | >20% QoQ decline 2 consecutive quarters | P1 | Terminal |
| 5 | Developer land acquisition news | Any Grade-A developer, target city | P1 | Terminal |
| 6 | Possession delay flagged | `actual_completion > possession_date` | P1 | Slack + Terminal |
| 7 | RBI rate decision | Any MPC outcome | P0 | Slack + Terminal |
| 8 | Stamp duty change | Karnataka or National | P0 | Slack + Terminal |
| 9 | BMRCL news | Phase 3 confirmation / delay | P0 | Slack + Terminal |
| 10 | BDA CDP notification | Zone change in target markets | P0 | Slack + Terminal |
| 11 | NCLT / NCDRC case | Against tracked developer | P0 | Slack + Terminal |
| 12 | Guidance value revision | Karnataka SRD notification | P1 | Slack + Terminal |
| 13 | Kaveri registration spike | >20% MoM increase in any market | P1 | Terminal |
| 14 | Clean title parcel available | Score >80, in metro influence zone, not acquired | P1 | Slack + Terminal |
| 15 | Developer quarterly results | Listed developer BSE filing | P2 | Terminal |

---

## File Structure — Full Target State

```
RE_OS/
│
├── agents/
│   ├── __init__.py
│   ├── scraper_agent.py          ✅ built
│   ├── analyst_agent.py          ✅ built → Phase 1 upgrade
│   ├── ceo_agent.py              ✅ built → Phase 1-3 upgrade
│   ├── developer_agent.py        ❌ Phase 2
│   ├── news_agent.py             ❌ Phase 3
│   └── land_agent.py             ❌ Phase 5
│
├── scrapers/
│   ├── __init__.py
│   ├── rera_karnataka.py         ✅ built (Playwright)
│   ├── kaveri_karnataka.py       ✅ built (Playwright, calibrate)
│   ├── listings_scraper.py       🔄 stub → Phase 1
│   ├── developer_news.py         ❌ Phase 2
│   ├── bse_filings.py            ❌ Phase 2
│   ├── news_aggregator.py        ❌ Phase 3
│   ├── govt_portals.py           ❌ Phase 3
│   ├── infra_pipeline.py         ❌ Phase 4
│   ├── bhoomi_karnataka.py       ❌ Phase 5
│   └── cdp_zones.py              ❌ Phase 4
│
├── utils/
│   ├── __init__.py
│   ├── db_organizer.py           ✅ built → Phase 1-2 upgrade
│   ├── news_organizer.py         ❌ Phase 3
│   ├── infra_organizer.py        ❌ Phase 4
│   ├── spatial_analyzer.py       ❌ Phase 4
│   ├── geocoder.py               ❌ Phase 4
│   ├── status.py                 ✅ built
│   └── validator.py              ✅ built
│
├── agents/
│   └── (as above)
│
├── alerts/
│   ├── engine.py                 ❌ Phase 6
│   └── slack.py                  ❌ Phase 6
│
├── api/
│   ├── main.py                   ❌ Phase 6
│   ├── routes/
│   │   ├── markets.py            ❌ Phase 6
│   │   ├── projects.py           ❌ Phase 6
│   │   ├── developers.py         ❌ Phase 6
│   │   └── alerts.py             ❌ Phase 6
│   ├── templates/
│   │   ├── base.html             ❌ Phase 6
│   │   ├── market_overview.html  ❌ Phase 6
│   │   ├── market_deep_dive.html ❌ Phase 6
│   │   ├── project_detail.html   ❌ Phase 6
│   │   ├── developer.html        ❌ Phase 6
│   │   ├── news_feed.html        ❌ Phase 6
│   │   └── land_intel.html       ❌ Phase 6
│   └── ws.py                     ❌ Phase 6
│
├── config/
│   ├── __init__.py
│   ├── settings.py               ✅ built
│   ├── llm_router.py             ✅ built
│   ├── scheduler.py              ✅ built → Phase 3 upgrade
│   ├── checkpointer.py           ✅ built
│   └── run_logger.py             ✅ built
│
├── crews/
│   ├── __init__.py
│   └── market_intel_crew.py      ✅ built → ongoing upgrades
│
├── database/
│   └── schema.sql                ✅ built → Phase 0-5 additions
│
└── plans/
    ├── MASTER_PLAN.md             ← THIS FILE
    ├── bloomberg_re_terminal_plan.md
    ├── data_moat_deep_plan.md
    ├── developer_intelligence_plan.md
    └── news_intelligence_plan.md
```

---

## LLM Usage Strategy — Where Each Model Goes

| Task | Model | Reason |
|------|-------|--------|
| Structured data extraction (RERA, Kaveri rows) | No LLM — pure Python | Deterministic. No hallucination risk. |
| DB writes | No LLM — pure Python | Same. |
| News classification + sentiment | Cerebras llama3.1-8b | Fast, 8k context enough for headline+summary |
| Analyst signals computation | No LLM — SQL + Python | Numeric. Exact. |
| Analyst brief writing | Groq Scout 128k or Cerebras | Structured text from clean JSON input |
| CEO synthesis + morning brief | Groq meta-llama-4-scout or Gemini 2.5 Flash | Needs reasoning over large context |
| PDF parsing (investor decks, DPRs) | Gemini 2.5 Flash | 1M context window, free 20 req/day |
| Title score reasoning | No LLM — rule-based | Simple formula, no ambiguity |
| Policy impact estimation | Groq Scout 128k | Needs to reason over historical comps library |
| News theme clustering | Cerebras | Fast classification task |

---

## The Morning Brief — What It Looks Like at Full Build

```
╔══════════════════════════════════════════════════════════════════╗
║         RE_OS INTELLIGENCE — MORNING BRIEF                      ║
║         13 May 2026 · 07:00 IST · Bengaluru North Corridor      ║
╚══════════════════════════════════════════════════════════════════╝

MARKET SCORECARD
  Yelahanka    🟢 STRONG    | PSF ₹6,800 | Absorption 65% | 5 projects
  Devanahalli  🟡 MODERATE  | PSF ₹5,200 | Absorption 58% | 3 projects
  Hebbal       🔴 TIGHT     | PSF ₹9,500 | Absorption 72% | 4 projects

TOP BUY SIGNALS
  1. Brigade Orchards (Devanahalli) — 52% absorbed, A+ developer, ₹7,200 psf
     Metro Phase 3: station 600m. Infrastructure not yet priced in (+7% uplift est.)
  2. Sobha Dream Gardens (Yelahanka) — 68% absorbed, price hike likely 60 days
     Tight inventory (9.5mo supply). On-time delivery track. Clean title land.

TOP RISK FLAGS
  1. Ozone Urbana — velocity down 28% QoQ. 28mo inventory. Price correction risk.
  2. Shriram Suhaana Phase 2 — possession slipped Apr 2026 → Sep 2026 (+5mo)
  3. Hebbal: 72% absorbed across 4 projects. New supply needed. Watch for launches.

DEVELOPER MOVES (last 24hr)
  🔴 Sobha: Price hike +6% on Dream Gardens (effective today)
  🟢 Brigade: New RERA registration — "Brigade Horizon" Devanahalli, 1,200 units
  🟡 Shriram: Velocity down 3rd consecutive month (-18% QoQ) — watch

LAND SIGNALS
  📍 Kogilu: 3 Kaveri registrations at ₹4,800/sqft (above GV ₹3,800 = +26% gap)
  📍 Sy.No 45/2 Yelahanka: New NA conversion. Clean title. 2.3ac. In Phase 3 zone.
  ⚠️  Competitor activity: XYZ Pvt Ltd appears in 3 adjacent Bagalur mutations

INFRASTRUCTURE ALPHA
  🚇 Phase 3 Metro: EIA submitted MoEF — clearance est. Q3 2026 (6mo ahead of plan)
     Impact: Land in 1km zone — historical comp: +18% in 12mo post-EIA clearance
  🛣️  STRR Devanahalli segment: piling work started (confirming 2027 completion)

POLICY & NEWS
  RBI: Rate hold at 6.50% — home loan rates stable at 8.75%
  HIGH: Phase 3 EIA is key buy signal. Window closing before market prices in.
  MEDIUM: Karnataka Budget session June — stamp duty revision under discussion
  MEDIUM: Anarock Q1: Bengaluru premium launches +41% YoY — consistent with our data

RECOMMENDED ACTION FOR LLS
  1. Phase 3 EIA confirmation — activate acquisition process for clean-title parcels
     in Yelahanka/Devanahalli 1km zone before full alignment published (Q4 2026)
  2. Sobha price hike = market confidence. Check comparable land cost in same zone.
  3. Brigade Horizon launch — 1,200 units Devanahalli = supply increase. Monitor
     impact on Ozone Urbana and other mid-segment projects.

──────────────────────────────────────────────────────────────────
RE_OS · LLS Business Development · Bengaluru
Next run: 14 May 2026 07:00 IST | Data: RERA + Kaveri + News (as of 06:45 IST)
```

---

## Success Metrics — By Phase

| Phase | Metric | Target |
|-------|--------|--------|
| Phase 0 | Live RERA projects in DB | 50+ Yelahanka |
| Phase 1 | Report sections | 6 structured sections with real numbers |
| Phase 2 | Developer events detected | Price hike within 24hr of RERA update |
| Phase 3 | News coverage | Top 5 RE news daily + policy status current |
| Phase 4 | Metro-adjacent projects | 100% of projects have metro proximity score |
| Phase 5 | Parcel lookup time | <30 seconds title score for any survey number |
| Phase 6 | Terminal usage | LLS team uses daily — replaces broker calls for intel |
| Phase 7 | Bengaluru coverage | All 15+ micro-markets active |
| Phase 8 | City coverage | Hyderabad live within 90 days of Bengaluru Phase 7 |

---

## Brainstorm Parking Lot (Future Advancements)

Ideas captured for future sessions — not in scope yet:

- **AI Property Valuer** — given BHK config, floor, facing, society amenities, location → automated AVM (Automated Valuation Model). Competes with Propstack, NoBroker Goldmine.
- **Broker Performance Index** — track broker activity from listing portals (who lists first, who sells fast, who has developer exclusives)
- **NRI Demand Tracker** — USD/INR rate correlation with Bengaluru premium registrations. NRI demand signal.
- **Rental Yield Calculator** — listing portal rent data → yield per micro-market per BHK type → benchmark for investor return analysis
- **Distressed Asset Screener** — NCLT + NCDRC cases + slow absorption → score distressed projects for acquisition opportunity
- **WhatsApp Alert Bot** — push morning brief and price alerts to LLS team WhatsApp group (WhatsApp Business API)
- **Client-facing Report Generator** — auto-generate PDF market reports for LLS clients (buyer guidance, investment thesis)
- **PropTech API** — expose data as API for PropTech startups, brokers (SaaS revenue)
- **Machine Learning Price Predictor** — train on 3yr PSF + absorption + infra data → 12-month price forecast per market
- **Voice Brief** — text-to-speech morning brief, delivered as WhatsApp audio message at 7am

---

*MASTER PLAN — Last updated: 2026-05-13*
*Update this file after every planning session. Add new modules to brainstorm parking lot.*
*Implementation: switch to Code mode after any approved phase.*
