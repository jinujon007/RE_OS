# RE_OS → Bloomberg Terminal for Indian Real Estate
## Master Architecture Plan
**Owner:** Jinu Joshi / Land & Life Space (LLS)
**Phase 1 City:** Bengaluru (North Corridor — Yelahanka, Devanahalli, Hebbal)
**Vision:** Market-leader real estate intelligence terminal for India

---

## Vision Statement

Bloomberg Terminal gives financial markets participants an unfair information advantage. RE_OS does the same for Indian real estate — structured data, live signals, AI synthesis, and actionable intelligence — before any competitor has it.

**Target users (near-term):** LLS internal — acquisition, pricing, project positioning decisions.
**Target users (medium-term):** Builders, brokers, PE funds, HNI investors in Bengaluru.
**Target users (long-term):** All of India — city by city, corridor by corridor.

---

## Current State (as of 2026-05-13)

| Component | Status |
|-----------|--------|
| 5-agent CrewAI pipeline | ✅ Running |
| PostgreSQL + PostGIS schema | ✅ 10 tables, seeded |
| RERA Karnataka scraper (Playwright) | ✅ Code done, container rebuild pending |
| Kaveri GV + registrations scraper | ✅ Code done, fallback data active |
| Listings scraper (99acres/MB) | 🔄 Stub, needs real selectors |
| LLM routing (Cerebras + Groq + Gemini) | ✅ 3-tier, fallback chain |
| Intelligence reports (CEO brief) | ✅ Generating (fallback data) |
| Terminal UI / Dashboard | ❌ Not started |
| API layer | ❌ Not started |
| Alerts / notifications | ❌ Not started |
| Multi-city support | ❌ Not started |

**DB state:** 9 rows rera_projects, 5 linked to Yelahanka. Kaveri fallback data active.

---

## Architecture — The Full Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                    RE_OS BLOOMBERG TERMINAL                      │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  TERMINAL UI  │  │  ALERT ENGINE │  │    PUBLIC API        │  │
│  │  (FastAPI +   │  │  (price move  │  │  (REST + WebSocket)  │  │
│  │   React/HTMX) │  │   launches    │  │  future: SaaS tier)  │  │
│  └──────┬───────┘  │   reg spikes) │  └──────────────────────┘  │
│         │          └──────┬────────┘                            │
│         └────────────────▼─────────────────────────────────────┐│
│                    INTELLIGENCE LAYER                           ││
│  ┌─────────────────────────────────────────────────────────┐   ││
│  │  CEO Agent (Groq 70B / Gemini 2.5 Flash)                │   ││
│  │  Analyst Agent (Cerebras / Groq Scout 128k)             │   ││
│  │  Market Signals Engine (Python — no LLM)                │   ││
│  └─────────────────────────────────────────────────────────┘   ││
│                    DATA LAYER                                   ││
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐  ││
│  │  RERA    │ │  Kaveri  │ │ Listings │ │ Infrastructure   │  ││
│  │Karnataka │ │  Portal  │ │ Scrapers │ │ Pipeline scraper │  ││
│  │Playwright│ │Playwright│ │99a/MB/NB │ │ (BMRCL/NHAI/BDA) │  ││
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘  ││
│                    STORAGE LAYER                                ││
│  ┌────────────────────┐  ┌──────────┐  ┌────────────────────┐  ││
│  │ PostgreSQL+PostGIS │  │  Redis   │  │  TimescaleDB ext   │  ││
│  │ (primary store)    │  │ (cache   │  │  (time series for  │  ││
│  │                    │  │  alerts) │  │   price tracking)  │  ││
│  └────────────────────┘  └──────────┘  └────────────────────┘  ││
└─────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 1 — Bengaluru: Harden & Activate (Now → Stable)

### 1A. Fix Existing Backlog (P0 — do first)

| Task | File | What |
|------|------|------|
| Fix `_upsert_project` ON CONFLICT | `utils/db_organizer.py` | Include `micro_market_id` + `developer_id` in UPDATE SET — fixes 3 orphaned rows |
| Delete empty artifact row | SQL | `DELETE FROM rera_projects WHERE project_name = ''` |
| Rebuild agents container | Docker | Activates Playwright for RERA + Kaveri |
| Add Cerebras + Gemini keys | `.env` | Activates fast LLM tier |

### 1B. Live Data Pipeline

**RERA Scraper** — `scrapers/rera_karnataka.py`
- Playwright interception confirmed working in code
- After rebuild: validate `[Playwright] Intercepted N rows` in logs
- Target: 50+ live Yelahanka projects (RERA has ~200+ registered in North BLR corridor)

**Kaveri Scraper** — `scrapers/kaveri_karnataka.py`
- Calibrate actual form field names (requires manual portal inspection session)
- Portal likely has CAPTCHA — plan: session cookie injection + rotating UA
- Fallback data sufficient for MVP; live data = P1 upgrade

**Listings Scraper** — `scrapers/listings_scraper.py`
- Currently stub. Priority sources:
  1. 99acres (highest inventory, structured URLs)
  2. MagicBricks (RERA number cross-reference field)
  3. NoBroker (owner listings — different supply signal)
- Strategy: Playwright headless + response interception (same pattern as RERA)
- Data value: asking price vs RERA price vs Kaveri registered price = 3-way spread

### 1C. Schema Fixes

| Fix | File | Why |
|-----|------|-----|
| `delay_months` generated column uses integer division | `database/schema.sql` | `(date - date) / 30` returns integer in PG — loses precision. Fix: `EXTRACT(EPOCH FROM ...)` |
| Add `TimescaleDB` hypertable for `project_snapshots` | `database/schema.sql` | Time-series queries 100x faster for price tracking |
| Add `price_history` JSONB to `rera_projects` | `database/schema.sql` | Store per-run price snapshots without separate table scans |

### 1D. Intelligence Upgrade — Analyst Agent

Current analyst produces: inventory stats, pricing, developer breakdown, Kaveri gap.

Add these signals:

| Signal | How | Bloomberg Equivalent |
|--------|-----|---------------------|
| **Absorption velocity** | Units sold per month (snapshot delta / days) | Sales volume |
| **Price momentum** | PSF change MoM, QoQ from snapshots | Price return |
| **Developer delivery score** | delay_months avg per developer, on-time % | Credit rating |
| **Supply pipeline pressure** | Total unsold units / monthly absorption = months of inventory | Inventory-to-sales ratio |
| **Guidance value gap trend** | GV gap % change YoY — signals land cost pressure | Spread |
| **Launch vs registration lag** | Days between RERA registration date and first listing | Time-to-market |

### 1E. CEO Agent — Report Upgrade

Current: paragraph brief.

Upgrade to structured report with these sections:
1. **Market Scorecard** — RAG status (Red/Amber/Green) per market
2. **Top 5 Buy Signals** — projects with high absorption, strong developer, reasonable PSF
3. **Top 3 Risk Flags** — delayed projects, slow absorption, overpriced vs Kaveri GV
4. **Competitive Landscape** — Tier 1 vs Tier 2 developer activity
5. **Land Acquisition Intelligence** — where registrations happening, at what PSF vs GV
6. **Recommended Action** — 3 bullets for LLS decision-makers

---

## Phase 2 — Terminal UI (The Bloomberg Layer)

This is what transforms RE_OS from a backend intelligence engine into a terminal product.

### 2A. Backend API — FastAPI

File: `api/main.py`

```
Endpoints:
GET  /markets                     → list all markets + status
GET  /markets/{slug}/summary      → full intelligence summary
GET  /markets/{slug}/projects     → paginated project list + filters
GET  /markets/{slug}/trends       → price + absorption time series
GET  /projects/{rera_number}      → single project deep dive
GET  /developers/{id}             → developer scorecard
GET  /alerts                      → active alert feed
POST /run/{market}                → trigger manual pipeline run
WS   /live                        → WebSocket for real-time alert push
```

### 2B. Terminal Dashboard — Options

Two implementation paths:

**Option A — HTMX + TailwindCSS (faster to build, server-rendered)**
- Pros: No JS build chain, works inside existing Docker stack, fast to iterate
- Cons: Less interactive, no real-time charts without JS
- Stack: `FastAPI` + `Jinja2` + `HTMX` + `Recharts` via CDN

**Option B — React Frontend (terminal-grade UX)**
- Pros: Real Bloomberg-feel, WebSocket live updates, complex data grids
- Cons: Separate build process, more complexity
- Stack: `Vite` + `React` + `TanStack Table` + `Recharts` + `shadcn/ui`

**Recommendation: Start with Option A for MVP, migrate to B when SaaS-ready.**

### 2C. Terminal Screens

```
Screen 1 — MARKET OVERVIEW (landing)
┌─────────────────────────────────────────────────────┐
│ RE_OS INTELLIGENCE TERMINAL  |  Bengaluru  |  Live  │
├──────────────┬──────────────┬──────────────────────┤
│ YELAHANKA    │ DEVANAHALLI  │ HEBBAL               │
│ ████░░░░ 65% │ ████░░ 58%   │ ██████░ 72%          │
│ Absorption   │ Absorption   │ Absorption           │
│ ₹6,800 avg   │ ₹5,200 avg   │ ₹9,500 avg           │
│ 5 projects   │ 3 projects   │ 4 projects           │
│ 🟢 STRONG    │ 🟡 MODERATE  │ 🔴 TIGHT             │
└──────────────┴──────────────┴──────────────────────┘

Screen 2 — MARKET DEEP DIVE (per market)
- Project table: sortable by absorption, PSF, possession date, developer grade
- Price chart: PSF trend over time (TimescaleDB time series)
- Developer heatmap: who's active, who's delivering
- Kaveri overlay: actual vs asking PSF spread

Screen 3 — PROJECT DETAIL (per project)
- RERA card: number, status, possession date, delay
- Unit mix breakdown (BHK composition)
- Pricing band chart
- Comparable projects in same micro-market
- Kaveri registrations linked to this project

Screen 4 — ALERTS FEED
- New project registered in RERA
- Price move > 5% on any active project
- Registration spike (Kaveri velocity up > 20% MoM)
- Developer delay flag (possession slipped)

Screen 5 — LAND ACQUISITION INTELLIGENCE
- Kaveri registration heatmap (where transactions happening)
- GV gap by village (where buying below market)
- Infrastructure proximity overlay (BMRCL stations, STRR, NHAI)
```

### 2D. Alert Engine — `alerts/engine.py`

Triggers (check on every pipeline run + daily):
- New RERA project registered in target market → Slack/email/WhatsApp
- Project absorption crosses threshold (60%, 80%, 90%)
- PSF move > 5% in any project
- Kaveri registration count spike (> 2 SD from 6-month mean)
- Developer missed possession date

Delivery:
- Phase 1: Log to DB + show in terminal UI
- Phase 2: Slack webhook (5 min to add)
- Phase 3: WhatsApp Business API (LLS client notifications)

---

## Phase 3 — Data Moat (What Makes This Unbeatable)

These data sources create a moat competitors can't replicate without years of work:

### 3A. Infrastructure Pipeline Intelligence

Source: BMRCL, NHAI, BDA, BBMP public documents + news scraper

Data:
- Metro station locations + planned stations (Phase 2, Phase 3)
- STRR (Suburban Rail) corridors
- NHAI NH expansion projects
- BDA CDP 2031 zoning map (raster → vector conversion)

Value: Know 2 years before market which corridors will appreciate. This is alpha.

Schema: `infrastructure_pipeline` table already exists in schema.

### 3B. Land Parcel Intelligence

Source: Bhoomi portal (Karnataka land records)

Data:
- Survey number → owner → conversion status (agricultural → non-agricultural)
- Khata records — title chain
- EC (Encumbrance Certificate) pulls — check for mortgages

Value: LLS can identify clean-title parcels before brokers know they're available.

### 3C. Regulatory Intelligence

Source: BBMP/BDA CDP documents, ODP notifications, GOs

Data:
- FAR rules by road width (already in schema)
- Zoning changes (residential → mixed use)
- TDR (Transfer of Development Rights) zones
- Affordable housing mandates per zone

Value: Know FSI/FAR before acquiring land — drives project concept before layout.

### 3D. Rental Market Layer

Source: NoBroker, MagicBricks Rent, Housing.com

Data:
- Rental yield by micro-market + BHK type
- Rental PSF trend
- Rental vacancy rate (listings age → days on market)

Value: Rental yield = demand signal + investor return benchmark.

### 3E. Developer Financial Intelligence

Source: MCA (Ministry of Corporate Affairs), NCLT filings, news

Data:
- Developer CIN → annual filings → revenue, debt, PAT
- NCLT cases (stressed developers — distressed asset opportunity)
- Director network map (related entities, cross-holdings)

---

## Phase 4 — India Expansion Strategy

City prioritization framework:

| Priority | City | Why |
|----------|------|-----|
| P0 | Bengaluru (North) | Current. Phase 1. |
| P1 | Bengaluru (East + South) | Same RERA, same Kaveri. Schema reuse 100%. |
| P2 | Hyderabad | RERA Telangana (similar portal). 2nd largest tech RE market. |
| P3 | Pune | RERA Maharashtra (different portal structure). IT corridor demand. |
| P4 | Chennai | TNRERA. Stable market. Different buyer profile. |
| P5 | NCR (Delhi/Gurugram/Noida) | UP RERA + Haryana RERA. Largest market. Most complex. |
| P6 | Mumbai | MahaRERA. Premium segment. |

Expansion architecture:
- Each city = new `city_config.py` with portal URLs, market slugs, Kaveri/SRO equivalent
- Schema is city-agnostic (uses `city` column in `micro_markets`)
- Scrapers parameterized by city config
- Same CrewAI pipeline, different market slugs

---

## Phase 5 — Monetization (When Ready)

| Tier | Target | Pricing | Features |
|------|--------|---------|----------|
| Internal | LLS only | Free | Full terminal, all data |
| Builder Pro | Bengaluru builders | ₹25k-50k/month | Market reports, project comps, land acquisition signals |
| Broker Elite | Top brokers | ₹10k-15k/month | Inventory alerts, absorption data, project rankings |
| Investor | HNIs, PE funds | ₹75k+/month | Developer financials, distressed assets, pipeline alpha |
| API | PropTech startups | Usage-based | Raw data API |

---

## Immediate Execution Roadmap (Next 30 Days)

### Week 1 — Harden Bengaluru Core
```
Day 1-2: Fix DB bugs + rebuild container + add API keys
Day 3-4: Validate live RERA data (50+ projects)
Day 5-7: Calibrate Kaveri scraper selectors + validate live GV data
```

### Week 2 — Listings + Intelligence Upgrade
```
Day 8-10: Build 99acres listings scraper (Playwright)
Day 11-12: Add 6 analyst signals (velocity, momentum, delivery score)
Day 13-14: Upgrade CEO report to structured 6-section brief
```

### Week 3 — Terminal UI MVP
```
Day 15-17: FastAPI backend + 5 endpoints
Day 18-20: HTMX dashboard — Market Overview + Deep Dive screens
Day 21: Alert engine (DB + log)
```

### Week 4 — Devanahalli + Hebbal + Polish
```
Day 22-24: Activate Devanahalli + Hebbal markets (data seeding)
Day 25-26: Infrastructure pipeline scraper (BMRCL station data)
Day 27-28: Slack alert webhook
Day 29-30: Internal demo. Collect feedback. Prioritize Phase 2.
```

---

## Key Architectural Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| LLM for scraping | No | Playwright interception is deterministic. LLM = hallucination risk on raw data |
| LLM for analysis | Yes | Pattern recognition on messy structured data = LLM strength |
| LLM for DB writes | No | Pure Python organizer. No hallucination on writes |
| Time series | TimescaleDB extension | Native PostgreSQL, zero migration. 100x faster than row scanning |
| Frontend MVP | HTMX | Ship fast. Bloomberg terminal feel with server-side tables |
| Frontend v2 | React | When SaaS-ready. Real-time WebSocket charts |
| Alert delivery | Slack first | Fastest to implement. WhatsApp next for LLS clients |
| Multi-city | Config-driven | One codebase, N cities. No forks |

---

## Success Metrics (Bloomberg Benchmark)

| Metric | Target | Bloomberg Equivalent |
|--------|--------|---------------------|
| Data freshness | < 24hr lag on RERA + Kaveri | Real-time tick data |
| Market coverage | 100% of active RERA projects in target markets | Full market depth |
| Signals accuracy | PSF within 5% of actual Kaveri registered price | Mark-to-market pricing |
| Report generation | < 3 min for full market brief | Terminal query speed |
| Uptime | 99%+ (Docker restart policies) | Terminal availability |
| Alert latency | < 1 hour from RERA registration to alert | News flash |

---

*Plan authored: 2026-05-13*
*Status: Awaiting user approval before implementation*
