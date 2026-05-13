# RE_OS — Developer Intelligence Module
## A-Grade Developer Tracking: Launches, Sales Inventory, Price Hikes
**Part of:** Bloomberg RE Terminal Master Plan
**Owner:** Jinu Joshi / LLS

---

> Bloomberg tracks every listed company — earnings, price moves, analyst ratings, insider trades. RE_OS tracks every Grade-A developer the same way. When Sobha launches a new phase, Brigade raises prices, or Prestige's absorption stalls — LLS knows first, before the broker calls.

---

## The Intelligence Goal

A real estate agent worth their salt knows:
1. **Who just launched** — new project, new phase, pre-launch
2. **How fast it's selling** — absorption velocity, not marketing claims
3. **When prices moved** — price hike date, quantum, per-micro-market
4. **Which developer is stressed** — slow sales, delayed possession, fund crunch
5. **What's coming** — land acquired, approvals filed, soft launch signals

RE_OS makes all of this systematic, automated, and queryable. This is what transforms an agent from reactive (client asks, agent scrambles) to proactive (agent calls client before client knows).

---

## Grade-A Developer Universe — Bengaluru (Seed List)

Priority tracking list for Phase 1:

| Developer | Grade | Known North BLR Projects | Why Track |
|-----------|-------|--------------------------|-----------|
| Brigade Group | A+ | Brigade Orchards (Devanahalli), Brigade Cornerstone Utopia | Largest land bank North BLR |
| Sobha Ltd | A+ | Sobha Dream Gardens (Yelahanka), Sobha City | Listed co — MCA + BSE data available |
| Prestige Group | A+ | Prestige Lakeside Habitat, Prestige Smart City | Most launches/year in BLR |
| Puravankara | A+ | Purva Atmosphere (Hebbal) | Mid-premium segment leader |
| Godrej Properties | A+ | Godrej Splendour | National brand, aggressive BLR push |
| Mana Projects | A | Mana Dale (Yelahanka) | North BLR specialist |
| Shriram Properties | A | Shriram Suhaana (Yelahanka) | Listed, active North BLR |
| Total Environment | A | Multiple villas projects | Premium segment |
| Century Real Estate | A | Multiple plotted dev. | Large land bank |
| Nitesh Estates | B+ | Premium segment | Niche, premium |
| Ozone Group | B+ | Ozone Urbana (Devanahalli) | Airport corridor specialist |

**Expansion:** Add any developer with >3 active RERA registrations in target markets.

---

## Data Sources Per Developer

### Source 1 — RERA Karnataka (Primary, Automated)
Already in pipeline. Extract per-developer:
- All registered projects (linked via `developer_id` in `rera_projects`)
- Per-project: units launched, units sold, unsold inventory, PSF range
- Timeline: launch date, possession date, delay status
- QTR updates: snapshot deltas = actual sales velocity

### Source 2 — Stock Exchange Filings (Listed Developers)
Listed Bengaluru developers: Sobha Ltd (NSE: SOBHA), Prestige Estates (NSE: PRESTIGE), Puravankara (NSE: PURVA), Shriram Properties (NSE: SHRIRAMPPS), Godrej Properties (NSE: GODREJPROP), Brigade Enterprises (NSE: BRIGADE)

Data available from BSE/NSE:
- Quarterly results — revenue from operations (housing segment)
- Project-wise sales data (disclosed in investor presentations)
- New launches — investor updates, press releases
- Pre-sales bookings (most listed devs disclose quarterly pre-sales in INR cr)
- Net debt (stress indicator)
- Collections (cash flow health)

Source URLs:
- `https://www.bseindia.com/corporates/ann.html` — NSE/BSE announcements
- `https://www.nseindia.com/companies-listing/corporate-filings-announcements` — NSE filings
- Company IR pages (e.g., `https://www.sobha.com/investors/`)

**This is massive alpha:** Sobha's quarterly investor deck discloses which projects sold how many units. Market doesn't systematically extract this per-project per-market. RE_OS does.

### Source 3 — MCA (Ministry of Corporate Affairs)
For unlisted developers (Mana, Total Environment, Ozone, Century etc.):
- Annual financial statements
- Director network — identify related entities, subsidiary land-holding SPVs
- Paid-up capital changes (rights issue = fund crunch signal)
- Charge creation/satisfaction = bank loans on land

Source: `https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html`

### Source 4 — News Aggregator
Real-time signals that RERA + MCA lag by months:
- New launch announcements (developer press releases, ET Realty, BW Businessworld RE)
- Price hike news ("Brigade raises Orchards prices by 8%")
- Land acquisition news ("Prestige buys 50 acres in Devanahalli")
- Litigation news (NCLT, NCDRC consumer complaints)
- Partnership / JV announcements

Source: NewsAPI / Google News RSS filtered by developer name + RE keywords

### Source 5 — Listing Portals (Cross-Reference)
99acres / MagicBricks developer pages:
- New project listings = launch signal (listed before RERA in some cases)
- Price updates on existing listings = price hike signal
- "Sold Out" tags on units = absorption signal
- Response time metrics (developer responsiveness = sales confidence indicator)

### Source 6 — Developer Websites (Direct)
Playwright scraper on developer project pages:
- Price list PDFs (Brigade, Sobha publish detailed price lists)
- Inventory status pages (some show "X units remaining")
- New project teasers / pre-registration pages

---

## Developer Intelligence Schema

```sql
-- ============================================================
-- DEVELOPER PROFILES (upgrade existing developers table)
-- ============================================================
-- Add to existing developers table:
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    nse_symbol VARCHAR(20),                     -- SOBHA, BRIGADE, PRESTIGE etc
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    bse_code VARCHAR(10),
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    is_listed BOOLEAN DEFAULT FALSE,
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    cin VARCHAR(21),                            -- MCA Corporate Identification Number
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    website VARCHAR(200),
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    bengaluru_market_share_pct DECIMAL(5,2),   -- computed: their units / total market units
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    active_projects_count INTEGER DEFAULT 0,
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    total_active_unsold INTEGER DEFAULT 0,
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    overall_delivery_score DECIMAL(5,2),       -- 0-100, based on delay history
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    financial_stress_flag BOOLEAN DEFAULT FALSE,
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    last_launch_date DATE,
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    last_price_hike_date DATE,
ALTER TABLE developers ADD COLUMN IF NOT EXISTS
    last_price_hike_pct DECIMAL(5,2);

-- ============================================================
-- DEVELOPER QUARTERLY PERFORMANCE
-- Structured from investor presentations + RERA snapshots
-- ============================================================
CREATE TABLE developer_quarterly_stats (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    developer_id UUID REFERENCES developers(id),
    period_year INTEGER NOT NULL,
    period_quarter INTEGER NOT NULL,           -- 1,2,3,4

    -- Sales performance (from RERA snapshot deltas)
    units_sold_this_qtr INTEGER,
    value_sold_crore DECIMAL(12,2),            -- if disclosed (listed cos)
    pre_sales_crore DECIMAL(12,2),             -- bookings (listed cos disclose)
    collections_crore DECIMAL(12,2),

    -- Launches
    projects_launched INTEGER,
    units_launched INTEGER,
    area_launched_sqft DECIMAL(15,2),

    -- Inventory
    total_unsold_units INTEGER,
    months_of_inventory DECIMAL(5,1),          -- unsold / monthly sales rate

    -- Financials (from annual report / quarterly results — listed only)
    revenue_crore DECIMAL(12,2),
    ebitda_crore DECIMAL(12,2),
    pat_crore DECIMAL(12,2),
    net_debt_crore DECIMAL(12,2),
    debt_to_equity DECIMAL(5,2),

    -- Source
    source VARCHAR(50),                        -- RERA_COMPUTED, BSE_FILING, INVESTOR_DECK
    filing_date DATE,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(developer_id, period_year, period_quarter)
);

-- ============================================================
-- DEVELOPER LAUNCHES
-- Every new project or new phase launch
-- ============================================================
CREATE TABLE developer_launches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    developer_id UUID REFERENCES developers(id),
    rera_project_id UUID REFERENCES rera_projects(id),
    micro_market_id UUID REFERENCES micro_markets(id),

    launch_type VARCHAR(30),                   -- New Project, New Phase, Pre-Launch, Soft Launch
    launch_date DATE,
    announcement_date DATE,                    -- when public announcement made
    project_name VARCHAR(300),

    -- Launch parameters
    units_launched INTEGER,
    launch_price_min_psf DECIMAL(10,2),
    launch_price_max_psf DECIMAL(10,2),
    total_launch_value_crore DECIMAL(12,2),

    -- Market context at launch
    market_avg_psf_at_launch DECIMAL(10,2),   -- what market was trading at
    premium_to_market_pct DECIMAL(5,2)
        GENERATED ALWAYS AS (
            CASE WHEN market_avg_psf_at_launch > 0
                 THEN ROUND(((launch_price_min_psf - market_avg_psf_at_launch)
                              / market_avg_psf_at_launch) * 100, 2)
                 ELSE NULL END
        ) STORED,

    -- Source
    source VARCHAR(100),
    source_url TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- PRICE HISTORY
-- Every price move per project, per developer
-- ============================================================
CREATE TABLE project_price_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rera_project_id UUID REFERENCES rera_projects(id),
    developer_id UUID REFERENCES developers(id),
    micro_market_id UUID REFERENCES micro_markets(id),

    effective_date DATE NOT NULL,
    price_psf_min DECIMAL(10,2),
    price_psf_max DECIMAL(10,2),
    price_psf_avg DECIMAL(10,2),

    -- Change from previous record
    prev_price_psf_avg DECIMAL(10,2),
    change_pct DECIMAL(5,2)
        GENERATED ALWAYS AS (
            CASE WHEN prev_price_psf_avg > 0
                 THEN ROUND(((price_psf_avg - prev_price_psf_avg)
                              / prev_price_psf_avg) * 100, 2)
                 ELSE NULL END
        ) STORED,
    change_direction VARCHAR(10),              -- UP, DOWN, FLAT

    -- Context
    reason VARCHAR(200),                       -- New phase, QtrRevision, MarketHike
    source VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- DEVELOPER NEWS & EVENTS
-- Structured news feed per developer
-- ============================================================
CREATE TABLE developer_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    developer_id UUID REFERENCES developers(id),
    rera_project_id UUID REFERENCES rera_projects(id),

    event_date DATE NOT NULL,
    event_type VARCHAR(50) NOT NULL,           -- Launch, PriceHike, LandAcquisition,
                                               -- Delay, Legal, Partnership, Completion,
                                               -- InvestorUpdate, Award
    headline VARCHAR(500),
    summary TEXT,
    sentiment VARCHAR(10),                     -- Positive, Negative, Neutral
    impact_score INTEGER,                      -- 1-10, LLM-assessed
    source VARCHAR(200),
    source_url TEXT,
    raw_content TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Developer Intelligence Engine — Agents & Tools

### Upgrade: `agents/analyst_agent.py` → Add `DeveloperScorecardTool`

```python
class DeveloperScorecardTool(BaseTool):
    """
    Full developer intelligence scorecard.
    Input: developer name or RERA promoter ID
    Output:
      - Active project count + total unsold inventory
      - Absorption velocity (units/month, last 90 days)
      - Price momentum (avg PSF change last 3 qtrs)
      - Delivery score (% projects on-time)
      - Financial stress flag (net debt / pre-sales ratio if listed)
      - Recent events (last 5 news events)
      - Market share in target micro-markets
      - Competitive positioning vs peer developers
    """
```

### New: `agents/developer_agent.py`

```python
"""
Developer Intelligence Agent
Tracks A-grade developer moves across all data sources.
Separate from Analyst (which is market-focused) — this is company-focused.
LLM: Groq Scout 128k (needs long context for investor deck parsing)
"""

class DeveloperNewsScraperTool(BaseTool):
    """Scrapes developer news from ET Realty, BW Businessworld RE, developer IR pages."""

class BSEFilingScraperTool(BaseTool):
    """Pulls quarterly results + investor presentations from BSE/NSE for listed developers."""

class InvestorDeckParserTool(BaseTool):
    """LLM extracts structured sales data from PDF investor presentations."""

class PriceListScraperTool(BaseTool):
    """Playwright scrapes developer website price list PDFs + 99acres project pages."""
```

---

## Developer Scorecard — Terminal Screen

```
┌─────────────────────────────────────────────────────────────────────┐
│ DEVELOPER INTELLIGENCE              [SOBHA LTD]  [▼ Compare]       │
├──────────────┬──────────────┬───────────────────────────────────────┤
│ SCORECARD    │ MARKET SHARE │ RECENT EVENTS                        │
│              │              │                                       │
│ Grade: A+    │ Yelahanka:   │ 🟢 12 May — New Phase launch          │
│ Projects: 4  │ ████░░ 34%   │    Sobha Dream Gardens Phase 3       │
│ Active units │              │    1,200 units @ ₹7,800/sqft          │
│ 2,840 unsold │ Devanahalli: │                                       │
│              │ ██░░░░ 18%   │ 🟡 08 May — Price revision           │
│ VELOCITY     │              │    +6% hike across all phases         │
│ 82 units/mo  │ Hebbal:      │    Effective 10 May 2026              │
│ ▲ +12% QoQ   │ █████░ 41%   │                                       │
│              │              │ 🔴 02 Apr — Possession delay          │
│ DELIVERY     │ BENGALURU    │    Dream Acres Phase 1: +4 months     │
│ ████████░░   │ TOTAL:       │                                       │
│ 84/100       │ ███░░░ 22%   │ 🟢 28 Mar — Q4 FY26 Results          │
│              │              │    Pre-sales: ₹1,840cr (+18% YoY)    │
│ PRICE TREND  │              │    Net debt: ₹2,100cr (D/E: 0.6)     │
│ ₹7,200 avg   │              │                                       │
│ ▲ +8.2% YoY  │              │ 🟢 15 Mar — Land acquisition          │
│              │              │    12ac Devanahalli @ ₹4cr/ac         │
└──────────────┴──────────────┴───────────────────────────────────────┘

PROJECTS ACTIVE
┌──────────────────────┬────────┬──────────┬────────┬────────┬────────┐
│ Project              │ Market │ Units    │ Sold % │ PSF    │ Status │
├──────────────────────┼────────┼──────────┼────────┼────────┼────────┤
│ Sobha Dream Gardens  │ Yelah. │ 2,400    │ 68% ▲  │ ₹7,800 │ UC     │
│ Sobha City Ph2       │ Hebbal │   800    │ 91% ▲  │ ₹9,200 │ UC     │
│ Sobha Silicon Oasis  │ Sarj.  │ 1,200    │ 45% ▼  │ ₹6,400 │ New   │
│ Sobha Dream Acres    │ Yelah. │   640    │ 99% ✓  │ ₹6,800 │ Comp. │
└──────────────────────┴────────┴──────────┴────────┴────────┴────────┘

PRICE HISTORY — Sobha Dream Gardens
₹8,000 ┤                                              ●
₹7,500 ┤                            ●────────────────
₹7,000 ┤                  ●─────────
₹6,500 ┤        ●─────────
₹6,000 ┤●───────
       └──────────────────────────────────────────────
        Jan25   Apr25   Jul25   Oct25   Jan26   May26
```

---

## Developer Comparison Screen

```
┌─────────────────────────────────────────────────────────────────────┐
│ COMPETITOR MATRIX — Yelahanka Corridor                              │
├──────────────────┬───────┬────────┬──────────┬────────┬────────────┤
│ Developer        │ Grade │ Unsold │ Velocity │ Avg PSF│ Delivery   │
├──────────────────┼───────┼────────┼──────────┼────────┼────────────┤
│ Sobha            │  A+   │  780   │  82/mo ▲ │ ₹7,800 │ ████████ 84│
│ Brigade          │  A+   │ 1,240  │  95/mo ▲ │ ₹7,200 │ ████████ 88│
│ Shriram          │   A   │  420   │  38/mo ▼ │ ₹5,800 │ ██████░░ 68│
│ Mana             │   A   │  310   │  42/mo ─ │ ₹6,200 │ ███████░ 74│
│ Ozone            │  B+   │  890   │  28/mo ▼ │ ₹4,800 │ █████░░░ 55│
└──────────────────┴───────┴────────┴──────────┴────────┴────────────┘
  ▲ accelerating  ─ stable  ▼ slowing

INSIGHT (CEO Agent): Brigade has highest velocity at 95 units/mo but also
highest unsold inventory (1,240). At current pace: 13 months of supply.
Sobha is tighter — 780 unsold / 82 units/mo = 9.5 months. Sobha more
likely to announce price hike in next 60 days. Brigade likely to hold
price to clear inventory. Shriram slowdown (-18% QoQ velocity) — watch
for price correction or incentive scheme.
```

---

## Alert Types — Developer Intel

| Trigger | Alert | Priority |
|---------|-------|----------|
| New RERA registration by A-grade developer in target market | "Brigade just registered new project in Yelahanka — 800 units" | P0 |
| Price hike detected (PSF up >4% vs last snapshot) | "Sobha Dream Gardens: PSF up 6% from ₹7,350 to ₹7,800 (effective 10-May)" | P0 |
| Absorption velocity crosses 80% sold | "Brigade Orchards: 80% absorbed — Phase close-out in ~3 months" | P1 |
| Velocity drops >20% QoQ | "Ozone Urbana: velocity down 28% — watch for price correction" | P1 |
| Developer land acquisition news | "Prestige acquires 50ac Devanahalli — new project likely Q3 2027" | P1 |
| Possession delay flagged | "Shriram Suhaana Phase 2: possession slipped from Dec 2025 to Apr 2026" | P1 |
| Listed developer quarterly results | "Sobha Q4 FY26: pre-sales ₹1,840cr (+18% YoY). Debt: ₹2,100cr" | P2 |
| NCLT / consumer forum case filed | "Ozone Group: NCDRC case filed — 45 complainants, Urbana Phase 1" | P0 |

---

## Agent Intelligence — What RE Agent Gets

When a client asks: *"Should I buy in Sobha Dream Gardens or Brigade Orchards?"*

RE_OS returns in <30 seconds:

```
COMPARISON: Sobha Dream Gardens vs Brigade Orchards (Yelahanka)

SOBHA DREAM GARDENS
  Price: ₹7,800/sqft (up 6% last hike, May 10)
  Absorption: 68% sold, 82 units/month
  Inventory left: 780 units → 9.5 months supply
  Delivery: On track (possession Dec 2026, 0 months delay)
  Developer: A+ grade, delivery score 84/100
  Kaveri gap: Market trades at ₹7,100 registered vs ₹7,800 asking = +10%
  Verdict: STRONG — tight inventory, on-time delivery, price appreciation likely

BRIGADE ORCHARDS
  Price: ₹7,200/sqft (stable last 2 quarters)
  Absorption: 52% sold, 95 units/month (fastest in market)
  Inventory left: 1,240 units → 13 months supply
  Delivery: On track (possession Mar 2027)
  Developer: A+ grade, delivery score 88/100
  Kaveri gap: Market at ₹6,900 registered vs ₹7,200 asking = +4.3%
  Verdict: GOOD — highest velocity but more supply overhang. Price hold likely.

RECOMMENDATION:
  End-user (own use): Sobha — tighter community, better delivery track
  Investor (appreciation): Sobha — price hike more likely in 60 days
  Investor (rental yield): Brigade — higher unit count = rental market liquidity
```

That's not analysis a broker can give in 30 seconds. That's what Bloomberg gives a bond trader.

---

## Implementation Sequence

### Sprint 1 — Schema + Seed Data
1. Add new columns to `developers` table (ALTER statements above)
2. Create `developer_quarterly_stats`, `developer_launches`, `project_price_history`, `developer_events` tables
3. Manually seed: 10 Grade-A developers with grade, NSE symbol, CIN, website
4. Backfill: compute `developer_quarterly_stats` Q1 FY26 from existing RERA snapshot data

### Sprint 2 — Price History Automation
1. Modify `utils/db_organizer.py`: on every RERA upsert, if PSF changed → write `project_price_history` record
2. Compute `change_pct` vs previous record
3. If `change_pct > 4%` → fire alert event

### Sprint 3 — News Scraper
1. `scrapers/developer_news.py` — NewsAPI + Google News RSS per developer name
2. LLM (Cerebras fast) — classify event_type, sentiment, impact_score from headline
3. Upsert `developer_events`

### Sprint 4 — BSE/MCA Scraper (Listed Devs)
1. BSE announcements scraper — investor presentations, quarterly results PDFs
2. LLM (Gemini 2.5 Flash — long context) — extract pre-sales, launches, debt from PDF
3. Upsert `developer_quarterly_stats`

### Sprint 5 — Developer Agent + Terminal Screen
1. `agents/developer_agent.py` — runs after Analyst, before CEO
2. CEO prompt context: include developer scorecard summary
3. Terminal: Developer Scorecard screen + Competitor Matrix screen

---

## Files to Create/Modify

```
NEW:
  scrapers/developer_news.py        — NewsAPI + Google News per developer
  scrapers/bse_filings.py           — BSE/NSE quarterly results scraper
  agents/developer_agent.py         — Developer intelligence crew agent

MODIFY:
  database/schema.sql               — New tables + ALTER statements
  utils/db_organizer.py             — Price history write on every RERA upsert
  agents/analyst_agent.py           — Add DeveloperScorecardTool
  crews/market_intel_crew.py        — Add developer_agent to crew pipeline
  config/settings.py                — Add DEVELOPER_GRADE_A_LIST config
```

---

## The Agent's Daily Intelligence Brief (What RE_OS Delivers Every Morning)

```
RE_OS MORNING BRIEF — 13 May 2026, 07:00 IST

MARKET PULSE — North Bengaluru
  Yelahanka: 🟢 STRONG  | Avg PSF ₹6,800 | Absorption 65% | 5 active projects
  Devanahalli: 🟡 MODERATE | Avg PSF ₹5,200 | Absorption 58% | 3 projects
  Hebbal: 🔴 TIGHT SUPPLY | Avg PSF ₹9,500 | Absorption 72% | 4 projects

DEVELOPER MOVES (last 24hr)
  🔴 ALERT: Sobha raised Dream Gardens prices +6% effective today
  🟢 INFO: Brigade registered new project — "Brigade Horizon" Devanahalli, 1,200 units
  🟡 WATCH: Shriram Suhaana velocity down 3rd consecutive month (-18% QoQ)

LAND SIGNALS
  📍 Kaveri: 3 registrations in Kogilu Village at ₹4,800/sqft (above GV ₹3,800 — +26%)
  📍 Bhoomi: New NA conversion order for Sy.No 45/2 Yelahanka (2.3ac, clean title)

INFRA UPDATE
  🚇 BMRCL Phase 3: Cabinet discussion scheduled — watch for alignment confirmation
  🛣️ STRR: Devanahalli segment piling work started (source: Twitter/local news)

TOP ACTION FOR LLS TODAY
  1. Sobha price hike signals tight inventory → check if Dream Gardens comparable
     land still available at pre-hike land cost
  2. Brigade Horizon launch → 1,200 units Devanahalli = supply increase, may
     pressure Ozone Urbana pricing
  3. Kogilu registration spike → investigate who is buying (developer accumulation?)
```

---

*Plan authored: 2026-05-13*
*Companion to: plans/bloomberg_re_terminal_plan.md + plans/data_moat_deep_plan.md*
