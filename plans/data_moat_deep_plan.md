# RE_OS — Data Moat Deep Plan
## Bhoomi Land Records + Infrastructure Pipeline Intelligence
**Part of:** Bloomberg RE Terminal Master Plan
**Owner:** Jinu Joshi / LLS

---

> This is the part no competitor can copy fast. Raw scraped data is table stakes. Structured, cross-linked, spatially-indexed land intelligence with infrastructure alpha — that is the moat. Bloomberg's moat is 40 years of tick data. RE_OS's moat is the structured intersection of land title, infrastructure timeline, and regulatory zoning — for every parcel in Bengaluru, then India.

---

## Section 1 — Bhoomi Land Records Intelligence

### What Bhoomi Is

Bhoomi is Karnataka's land records digitization system. It covers:
- **RTC (Record of Rights, Tenancy and Crops)** — who owns what land, what type, what cultivation
- **Mutation register** — ownership transfer history
- **EC (Encumbrance Certificate)** — mortgages, charges, legal disputes on a survey number
- **Pahani** — village-level crop and land use records

Portal: `https://bhoomi.karnataka.gov.in`

For real estate, Bhoomi answers:
1. Who owns this parcel right now?
2. Is it agricultural (needs NA conversion) or already non-agricultural?
3. Is there a bank mortgage / legal charge on it?
4. Who owned it before? (title chain — critical for clean title)
5. What is the survey number / phodi (sub-division) status?

**This is what a developer's legal team spends weeks doing manually. RE_OS does it in minutes.**

---

### Bhoomi Data Architecture

#### New Schema Tables

```sql
-- ============================================================
-- LAND PARCELS
-- Core entity — one row per survey number sub-division
-- ============================================================
CREATE TABLE land_parcels (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    district VARCHAR(100) NOT NULL,
    taluk VARCHAR(100) NOT NULL,
    hobli VARCHAR(100),
    village VARCHAR(100) NOT NULL,
    survey_number VARCHAR(50) NOT NULL,
    sub_division VARCHAR(20),                    -- phodi number
    full_survey_ref VARCHAR(200),               -- district/taluk/village/survey

    -- Classification
    land_type VARCHAR(50),                       -- Dry, Wet, Garden, Inam, Govt
    land_use VARCHAR(50),                        -- Agricultural, Non-Agricultural, Mixed
    na_conversion_status VARCHAR(50),            -- Converted, Not Converted, Applied, Rejected
    na_conversion_date DATE,
    na_conversion_order VARCHAR(200),            -- GO/order number

    -- Area
    total_area_acres DECIMAL(10,4),
    total_area_sqm DECIMAL(12,2)
        GENERATED ALWAYS AS (total_area_acres * 4046.86) STORED,

    -- Owner (current from RTC)
    owner_name VARCHAR(300),
    owner_type VARCHAR(50),                      -- Individual, Company, Trust, Govt
    khata_number VARCHAR(100),
    owner_caste_category VARCHAR(20),           -- for SC/ST land restrictions

    -- Encumbrances
    has_encumbrance BOOLEAN DEFAULT FALSE,
    encumbrance_type VARCHAR(100),               -- Mortgage, Attachment, Court Order
    encumbrance_detail TEXT,

    -- Title chain flags
    title_chain_clear BOOLEAN,                  -- computed after mutation analysis
    last_mutation_date DATE,
    mutation_count INTEGER DEFAULT 0,

    -- Spatial
    geom GEOMETRY(POLYGON, 4326),               -- parcel boundary (from BDA GIS if available)
    centroid GEOMETRY(POINT, 4326),

    -- Cross-references
    micro_market_id UUID REFERENCES micro_markets(id),
    adjacent_rera_project_id UUID REFERENCES rera_projects(id),

    -- Status
    acquisition_interest VARCHAR(20),           -- Watch, Target, Acquired, Rejected
    acquisition_notes TEXT,

    -- Metadata
    bhoomi_rtc_url TEXT,
    last_scraped_at TIMESTAMP,
    raw_rtc_data JSONB,
    raw_ec_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(district, taluk, village, survey_number, sub_division)
);

-- ============================================================
-- MUTATION REGISTER
-- Ownership transfer history per parcel
-- ============================================================
CREATE TABLE land_mutations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    land_parcel_id UUID REFERENCES land_parcels(id) ON DELETE CASCADE,
    mutation_number VARCHAR(100),
    mutation_date DATE,
    from_owner VARCHAR(300),
    to_owner VARCHAR(300),
    transfer_type VARCHAR(50),                  -- Sale, Gift, Inheritance, Court Decree
    transaction_amount DECIMAL(15,2),           -- if sale
    reason_code VARCHAR(50),
    order_date DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- ENCUMBRANCE CERTIFICATES
-- Per-parcel EC pulls — mortgages, attachments
-- ============================================================
CREATE TABLE land_encumbrances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    land_parcel_id UUID REFERENCES land_parcels(id) ON DELETE CASCADE,
    document_number VARCHAR(200),
    document_type VARCHAR(100),                 -- Sale Deed, Mortgage Deed, Release Deed
    execution_date DATE,
    party_one VARCHAR(300),                     -- seller / mortgagor
    party_two VARCHAR(300),                     -- buyer / mortgagee (bank)
    consideration_amount DECIMAL(15,2),
    sro_name VARCHAR(200),                      -- Sub-Registrar Office
    is_active BOOLEAN DEFAULT TRUE,             -- mortgage discharged or not
    raw_ec_data JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

### Bhoomi Scraper Strategy

**File:** `scrapers/bhoomi_karnataka.py`

#### Portal Structure
```
https://bhoomi.karnataka.gov.in
  /bhoomi/Pahani.do          → RTC (Record of Rights) search by district/taluk/village/survey
  /bhoomi/MRquery.do         → Mutation register query
  /bhoomi/ecquery.do         → Encumbrance Certificate search
```

All three use form-based POST with session cookies. Classic government portal — no JS rendering needed, but requires session maintenance.

#### Scraping Strategy

```python
class BhoomiScraper:
    """
    Three scrapers in one:
    1. scrape_rtc(district, taluk, village, survey_number)
       → Returns owner, land type, area, NA status
    2. scrape_mutations(district, taluk, village, survey_number)
       → Returns ownership history (last 10 mutations)
    3. scrape_ec(district, taluk, village, survey_number, years_back=13)
       → Returns encumbrance records (13yr EC = standard legal search period)

    Primary:  requests + BeautifulSoup (no JS needed — plain form POST)
    Fallback: Playwright if session handling fails
    Rate:     Max 1 req/3sec — government portal, be respectful
    """
```

#### Input Generation Strategy

**Problem:** Bhoomi requires exact district/taluk/village/survey combos. Can't scrape all of Karnataka.

**Solution — Target-driven scraping:**
1. Pull survey numbers from Kaveri registration records (we already have `survey_number` in `kaveri_registrations` table)
2. Pull survey numbers from RERA project disclosures (RERA requires land survey details in project registration)
3. Manual seeding: LLS acquisition targets (Jinu inputs survey numbers directly)
4. Spatial query: for any polygon drawn on map, find all survey numbers that intersect (using BDA village map GIS layer)

**Priority queue logic:**
```
Tier 1: Parcels adjacent to active RERA projects (high development pressure)
Tier 2: Parcels where Kaveri registrations happened in last 6 months
Tier 3: Parcels within 500m of planned metro stations
Tier 4: Any parcel manually flagged by LLS team
```

---

### What This Produces (The Intelligence)

| Signal | How Derived | Business Value |
|--------|-------------|----------------|
| **Clean title score** | Zero EC charges + single owner + <3 mutations in 10yr | Pre-qualification before site visit |
| **Distressed parcel flag** | Court attachment EC + stalled mutation | Negotiation opportunity |
| **Agricultural holdout** | Large ag parcel, no NA, surrounded by NA | Identifies aggregation targets |
| **Developer accumulation** | Same company/director appears in mutations across adjacent surveys | Spot competitors assembling land before announcement |
| **SC/ST land flag** | Karnataka law prohibits sale of SC/ST lands to non-SC/ST without DC permission | Legal risk warning |
| **Title chain depth** | Mutation count + transfer type history | Clean = quick deal, messy = slow + risk |

---

### Bhoomi Integration with Terminal

**Screen: Land Acquisition Intelligence**

```
┌─────────────────────────────────────────────────────────────┐
│ LAND INTEL — Yelahanka Corridor          [Draw AOI] [Filter]│
├──────────────────────────────────────────────────────────────┤
│ Survey Map (PostGIS render)                                  │
│ ████ NA Converted  ░░░░ Agricultural  ▓▓▓▓ Govt/Reserved    │
│                                                             │
│ 📍 Sy.No 45/2, Yelahanka Hobli      [DETAILS →]            │
│    Owner: Ramesh K (Individual)  Area: 2.3ac               │
│    NA Status: ✅ Converted (2019)  Encumbrance: ❌ None     │
│    Title Score: ████████░░ 85/100  Mutations: 2 (clean)    │
│    Last Kaveri reg: ₹4,800/sqft (Mar 2025)                  │
│                                                             │
│ ⚠️  Sy.No 67, Bagalur Village      [DETAILS →]             │
│    Owner: [Company XYZ Pvt Ltd]  Area: 5.1ac               │
│    NA Status: ❌ Agricultural     Encumbrance: ⚠️ Mortgage  │
│    Title Score: ████░░░░░░ 40/100  Mutations: 7             │
└──────────────────────────────────────────────────────────────┘
```

---

## Section 2 — Infrastructure Pipeline Intelligence

### Why This Is Alpha

Infrastructure = the single biggest driver of RE appreciation in India. Bengaluru metro Phase 2 stations that were announced in 2016 and completed by 2022 saw 40-80% price appreciation in adjacent corridors. **The terminal must know what's coming before the market prices it in.**

Sources:
- BMRCL (Bengaluru Metro Rail Corporation) — Metro line plans, station lists, timelines
- NHAI (National Highways Authority) — NH expansion projects, ring roads
- BWSSB (water/sewer) — pipeline extension maps (water availability = developability signal)
- BDA (Bengaluru Development Authority) — CDP 2031 land use map, ring roads, new layouts
- KIADB (industrial areas) — industrial zone designations (affects residential zoning around them)
- BBMP (roads, flyovers, underpasses)
- Railways — South Western Railway suburban rail (STRR project)

---

### Infrastructure Schema

```sql
-- ============================================================
-- INFRASTRUCTURE PROJECTS
-- Any public infrastructure that affects RE values
-- ============================================================
CREATE TABLE infrastructure_projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_name VARCHAR(300) NOT NULL,
    project_type VARCHAR(50) NOT NULL,          -- Metro, Highway, Ring Road, Suburban Rail,
                                                --  Flyover, Water Pipeline, Industrial Zone
    authority VARCHAR(100) NOT NULL,            -- BMRCL, NHAI, BDA, BBMP, BWSSB, KIADB

    -- Status
    status VARCHAR(50) NOT NULL,                -- Announced, DPR Approved, Tendered,
                                                --  Under Construction, Commissioned, Cancelled
    announcement_date DATE,
    dpr_approval_date DATE,
    tender_date DATE,
    construction_start_date DATE,
    expected_completion_date DATE,
    actual_completion_date DATE,

    -- Geometry
    alignment GEOMETRY(LINESTRING, 4326),       -- for roads, metro lines, pipelines
    influence_zone GEOMETRY(POLYGON, 4326),     -- 500m buffer auto-computed
    geom GEOMETRY(GEOMETRY, 4326),              -- generic fallback

    -- Financial
    project_cost_crore DECIMAL(15,2),
    funding_source VARCHAR(200),                -- Central govt, State, PPP, JICA loan

    -- Impact scoring
    re_impact_radius_m INTEGER DEFAULT 500,    -- how far RE prices affected
    re_price_impact_pct DECIMAL(5,2),          -- estimated % uplift on completion
    impact_confidence VARCHAR(20),             -- High/Medium/Low (based on historical comps)

    -- Sources
    source_url TEXT,
    source_document TEXT,
    last_updated TIMESTAMP DEFAULT NOW(),
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- METRO STATIONS
-- Individual stations (child of infrastructure_projects)
-- ============================================================
CREATE TABLE metro_stations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    infra_project_id UUID REFERENCES infrastructure_projects(id),
    station_name VARCHAR(200) NOT NULL,
    line_name VARCHAR(100),                     -- Purple Line, Green Line, Yellow Line etc
    station_type VARCHAR(50),                   -- Elevated, Underground, At-grade, Interchange
    sequence_number INTEGER,

    -- Status
    status VARCHAR(50),                         -- Operational, Under Construction, Planned
    expected_opening DATE,
    actual_opening DATE,

    -- Location
    geom GEOMETRY(POINT, 4326),

    -- Influence zones (pre-computed for fast spatial query)
    zone_500m GEOMETRY(POLYGON, 4326),
    zone_1km GEOMETRY(POLYGON, 4326),
    zone_2km GEOMETRY(POLYGON, 4326),

    -- RE impact tracking
    pre_announcement_avg_psf DECIMAL(10,2),    -- PSF at time of announcement
    current_avg_psf DECIMAL(10,2),             -- latest PSF in 500m zone
    appreciation_pct DECIMAL(5,2)
        GENERATED ALWAYS AS (
            CASE WHEN pre_announcement_avg_psf > 0
                 THEN ROUND(((current_avg_psf - pre_announcement_avg_psf)
                              / pre_announcement_avg_psf) * 100, 2)
                 ELSE NULL END
        ) STORED,

    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(infra_project_id, station_name)
);

-- ============================================================
-- INFRA × MICRO MARKET PROXIMITY
-- Pre-computed: which markets are within N km of which projects
-- ============================================================
CREATE TABLE infra_market_proximity (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    infra_project_id UUID REFERENCES infrastructure_projects(id),
    metro_station_id UUID REFERENCES metro_stations(id),
    micro_market_id UUID REFERENCES micro_markets(id),
    land_parcel_id UUID REFERENCES land_parcels(id),
    rera_project_id UUID REFERENCES rera_projects(id),

    distance_m DECIMAL(10,2),
    proximity_category VARCHAR(20),             -- Walking (0-500m), Near (500m-1km), Adjacent (1-2km)
    computed_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- CDP ZONING
-- BDA Master Plan 2031 land use zones
-- ============================================================
CREATE TABLE cdp_zones (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plan_name VARCHAR(100) DEFAULT 'CDP 2031',
    zone_code VARCHAR(20),                      -- R1, R2, C1, MU-1, GB, Agr, etc.
    zone_description VARCHAR(200),
    geom GEOMETRY(MULTIPOLYGON, 4326),

    -- Development parameters (from BDA DC Rules 2015)
    far_9m_road DECIMAL(4,2),
    far_12m_road DECIMAL(4,2),
    far_18m_road DECIMAL(4,2),
    far_24m_road DECIMAL(4,2),
    far_30m_road DECIMAL(4,2),
    ground_coverage_pct DECIMAL(5,2),
    min_plot_area_sqm DECIMAL(10,2),
    max_height_m DECIMAL(6,2),
    uses_permitted TEXT[],                      -- array of permitted uses
    uses_prohibited TEXT[],

    created_at TIMESTAMP DEFAULT NOW()
);
```

---

### Infrastructure Data Sources (Bengaluru)

#### BMRCL — Metro

| Phase | Lines | Status | Stations |
|-------|-------|--------|----------|
| Phase 1 | Purple (E-W) + Green (N-S) | Operational | 42 stations |
| Phase 2 | Yellow (RV Road-Bommasandra) + Pink (Kalena Agrahara-Nagawara) | Partial ops | 38 stations |
| Phase 2A | Silver (Central Silk Board-KR Puram via Sarjapur) | UC | 22 stations |
| Phase 2B | Gold (KR Puram-Kempegowda via Hebbal) | UC | 19 stations — **KEY for North BLR** |
| Phase 3 | JP Nagar-Kempegowda Airport (elevated) | DPR stage | ~35 stations — **MASSIVE for Yelahanka/Devanahalli** |

**Phase 3 airport line is the single biggest RE catalyst in North Bengaluru.** Current data: DPR submitted 2023, Cabinet approval pending. Any station list update = immediate RE price signal.

Scraping:
- `https://english.bmrc.co.in` — press releases, project updates
- PDF parsing: DPR documents, alignment maps
- News aggregator: track BMRCL keyword in Times of India, Deccan Herald

#### NHAI — Highways

Key North BLR projects:
- NH-44 widening (Bengaluru-Hyderabad) — affects Yelahanka, Devanahalli directly
- STRR (Satellite Town Ring Road) — 74km ring connecting all radial NHs outside BBMP
- Peripheral Ring Road (PRR) — BDA project, partial completion
- NH-648 Bengaluru-Hassan — affects Tumkur Road corridor

Source: `https://nhaipirdonline.com` + `https://nhai.gov.in`

#### KIADB / ITIR

- Devanahalli Business Park (DBP) — IT/ITES SEZ, 900 acres
- Aerospace Park — near KIA
- Industrial area designations affect surrounding residential RE (workforce housing demand)

Source: `https://kiadb.in` — zone notification PDFs

#### BWSSB — Water Pipeline

Less visible but critical: developers can't build where there's no water. BWSSB pipeline extension = developability signal 12-18 months before construction starts.

Source: BWSSB annual reports, RTI data, local news.

---

### Infrastructure Scraper Strategy

**File:** `scrapers/infra_pipeline.py`

```python
class InfraScraper:
    """
    Scrapes and structures infrastructure project data.

    Sources:
    1. BMRCL press releases (requests + BeautifulSoup)
    2. NHAI project tracker (Playwright — JS-rendered project list)
    3. BDA announcements (requests + PDF parser)
    4. News aggregator (NewsAPI / Google News RSS for infrastructure keywords)
    5. PDF parser for DPR documents (pdfplumber + LLM extraction)

    LLM role here: Extract structured data from PDF documents and news text.
    This is legitimate LLM use — unstructured → structured, not hallucination risk.
    """

    def scrape_bmrcl_updates(self) -> list[dict]:
        """Scrape BMRCL press releases for project status updates."""

    def scrape_nhai_projects(self, district="Bengaluru Urban") -> list[dict]:
        """Pull active NHAI projects in target district."""

    def parse_infra_pdf(self, pdf_path: str, project_type: str) -> dict:
        """Use LLM (Gemini 2.5 Flash - long context) to extract structured
        data from DPR/alignment PDFs. Returns stations list, timeline, cost."""

    def geocode_stations(self, station_list: list[str]) -> list[dict]:
        """Geocode station names to lat/lon using Google Maps / Nominatim."""

    def compute_influence_zones(self, station_geom) -> dict:
        """PostGIS ST_Buffer at 500m, 1km, 2km. Pre-compute for fast queries."""
```

**Key insight:** Infrastructure PDFs are the best source but are unstructured. Use Gemini 2.5 Flash (1M token context, free tier) to parse alignment maps and extract station lists from DPR PDFs. This is where long-context LLM earns its place.

---

### Infrastructure Intelligence — What the Terminal Shows

#### Screen: Infrastructure Alpha Map

```
┌─────────────────────────────────────────────────────────────────┐
│ INFRASTRUCTURE PIPELINE — North Bengaluru Corridor              │
│ [Show: Metro] [Show: Highways] [Show: Water] [Timeline: 2yr]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│    KEMPEGOWDA AIRPORT ●────────────────── Phase 3 Metro         │
│                       ║  (DPR submitted)   ~2028 est.          │
│    Devanahalli ●──────╫──── STRR ────────── NH-44               │
│                       ║                                         │
│    Yelahanka New Town ●    Phase 2B UC ──── 2025 est.          │
│                       ║                                         │
│    Hebbal ●───────────╫──── Phase 2B operational               │
│                       ║                                         │
│    Outer Ring Road ●──╝                                         │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│ IMPACT OVERLAY — Properties within 1km of planned stations      │
│                                                                 │
│ RERA Projects in Phase 3 Metro influence zone: 12              │
│   Avg PSF pre-announcement: ₹4,200  Current: ₹5,800 (+38%)    │
│   Projects NOT yet priced in: Brigade X, Sobha Y (+3 more)    │
│                                                                 │
│ Land parcels in Phase 3 zone: 847 survey numbers              │
│   NA Converted + Clean Title + <500m: 23 parcels              │
│   → These are the acquisition targets                          │
└─────────────────────────────────────────────────────────────────┘
```

#### The Core Intelligence Loop

```
Infrastructure announced
    → Geocode alignment + stations
    → Spatial query: which RERA projects + land parcels fall in 500m/1km/2km
    → Cross with Kaveri: current registered PSF in those zones
    → Cross with pre-announcement PSF (from project_snapshots)
    → Compute appreciation already priced in vs historical comp markets
    → Flag parcels not yet repriced = acquisition targets
    → Alert: "Phase 3 Metro — 23 clean-title parcels in 500m zone not yet repriced"
```

---

### Cross-Signal Intelligence Matrix

The terminal's real power is where signals intersect. No single source is alpha — the intersection is:

| Signal A | Signal B | Signal C | Intelligence Output |
|----------|----------|----------|---------------------|
| Parcel: Clean title, NA converted, 2ac | Metro: planned station 400m away | Kaveri: PSF ₹3,200 (below market) | **TOP ACQUISITION TARGET** |
| RERA project: 90% absorbed, possession due | Kaveri: registration spike +40% | Developer grade: A | **Price momentum — market moving** |
| Parcel: Agricultural, large (>5ac) | Adjacent: 3 NA-converted parcels | Mutations: same company buying | **Competitor assembling land — track** |
| RERA project: delayed 8 months | Developer: NCLT case filed | Absorption: 45% (stalled) | **Distressed — negotiation opportunity** |
| CDP zone change: Agr → MU | KIADB: industrial zone adjacent | Water: BWSSB pipeline planned | **Pre-development signal — acquire before market** |

---

### Data Refresh Cadence

| Source | Refresh | Trigger |
|--------|---------|---------|
| Bhoomi RTC | Monthly (or on-demand per parcel) | LLS acquisition interest flagged |
| Bhoomi EC | On-demand (before any acquisition) | Never auto — too expensive |
| BMRCL press releases | Daily | News scraper cron |
| NHAI project tracker | Weekly | Scheduler |
| CDP zoning | Annual + on notification | BDA GO alert |
| Infra PDFs | On-demand (when new DPR announced) | Manual trigger + LLM parse |
| RERA projects | Daily (existing pipeline) | Current scheduler |
| Kaveri GV | Monthly | Current scheduler |
| Kaveri registrations | Daily | Current scheduler |

---

### Implementation Sequence

#### Sprint 1 — Metro Layer (Highest Value, Fastest Build)
1. Manual seed: BMRCL Phase 2B + Phase 3 station list (23 stations) into `metro_stations` — plain SQL, no scraper needed yet
2. Geocode stations (Google Maps API or Nominatim, free)
3. PostGIS `ST_Buffer` to create 500m/1km/2km influence zones
4. Spatial join: `rera_projects` + `land_parcels` within metro zones
5. Terminal screen: show which projects are metro-adjacent, compute PSF uplift

**Output after Sprint 1:** "Brigade Orchards is 800m from planned Yelahanka Phase 3 station. PSF there is ₹5,800 vs ₹4,200 pre-announcement — 38% already priced. Sobha Dream Gardens is 600m from same station but PSF is ₹4,400 — only 5% above pre-announcement. Underpriced."

#### Sprint 2 — Bhoomi Basic (RTC Pull)
1. Build `scrapers/bhoomi_karnataka.py` — RTC + mutation scraper
2. Seed with survey numbers from Kaveri registration records (already in DB)
3. Score clean title: zero encumbrance + <4 mutations + NA converted = score 80+
4. Terminal: Land Acquisition Intelligence screen (map view + parcel list)

#### Sprint 3 — CDP Zoning Layer
1. BDA CDP 2031 shapefile (publicly available — request from BDA or download from BBMP GIS portal)
2. Load into PostGIS as `cdp_zones`
3. Spatial join: show zone code + FAR parameters for any parcel or project

#### Sprint 4 — Infrastructure Scraper Automation
1. BMRCL news scraper (daily, feeds `infrastructure_projects` updates)
2. NHAI project tracker (weekly)
3. LLM PDF parser for DPR documents (Gemini 2.5 Flash on trigger)

---

### File Structure for New Scrapers

```
scrapers/
  ├── rera_karnataka.py       ✅ existing
  ├── kaveri_karnataka.py     ✅ existing
  ├── listings_scraper.py     🔄 stub → next
  ├── bhoomi_karnataka.py     ❌ new — RTC + EC + mutations
  ├── infra_pipeline.py       ❌ new — BMRCL + NHAI + BDA
  └── cdp_zones.py            ❌ new — BDA shapefile loader

utils/
  ├── db_organizer.py         ✅ existing
  ├── infra_organizer.py      ❌ new — upserts for infra + parcel tables
  ├── geocoder.py             ❌ new — Nominatim/Google Maps wrapper
  └── spatial_analyzer.py     ❌ new — ST_Buffer, ST_Within, influence zone compute

agents/
  ├── analyst_agent.py        ✅ existing → add spatial queries
  ├── land_agent.py           ❌ new — Bhoomi queries, title scoring, acquisition signals
  └── infra_agent.py          ❌ new — infrastructure cross-reference, PSF uplift compute
```

---

## Summary — Data Moat Build Order

```
Priority 1: Metro station layer (manual seed → spatial join → terminal screen)
Priority 2: Bhoomi RTC scraper (title score → acquisition targeting)
Priority 3: CDP zoning layer (FAR / zone → development feasibility)
Priority 4: Infrastructure scraper automation (BMRCL daily, NHAI weekly)
Priority 5: Bhoomi EC on-demand (legal due diligence trigger)
Priority 6: Developer financial intelligence (MCA + NCLT)
```

**The moat metric:** When a land broker calls LLS with a 3-acre site in Yelahanka, RE_OS should return in 30 seconds: title score, encumbrance status, NA conversion, nearest metro station distance, CDP zone + FAR, Kaveri PSF trend, comparable RERA projects nearby, and a buy/pass recommendation. That response currently takes a lawyer 3 days and a market analyst 2 hours.

---

*Plan authored: 2026-05-13*
*Companion to: plans/bloomberg_re_terminal_plan.md*
