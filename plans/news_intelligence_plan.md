# RE_OS — News Intelligence Module
## Macro RE News, Govt Reforms, Policy Impact Tracking
**Part of:** Bloomberg RE Terminal Master Plan
**Owner:** Jinu Joshi / LLS

---

> Bloomberg's "NEWS" key is the most-used key on the terminal. Every bond trader knows: policy moves markets before price moves. For Indian RE, RBI rate decisions, Union Budget sops, RERA amendments, and state government CDP revisions are the macro events that move entire corridors overnight. RE_OS tracks all of it — structured, scored, and cross-referenced to affected micro-markets.

---

## Why News Intelligence Is Non-Negotiable

Indian RE is uniquely policy-driven. Examples of policy events that moved Bengaluru RE prices materially:

| Event | When | Impact |
|-------|------|--------|
| RERA Karnataka enforcement strengthened | 2018 | Killed fly-by-night developers. Grade-A absorption jumped 15% |
| RBI repo rate cut cycle (2019-20) | 2019-20 | Home loan rates fell to 6.5%. Demand surge across all segments |
| COVID stamp duty waiver (Karnataka) | 2021 | Registration volumes up 40% in Q3 2021 |
| RBI rate hike cycle (2022-23) | 2022-23 | EMI up 25%. Demand slowdown, unsold inventory up |
| BMRCL Phase 3 airport line announcement | 2023 | Yelahanka/Devanahalli prices up 10-15% in 3 months |
| Bengaluru BDA revised ODP notification | 2024 | Zone changes unlocked new development corridors |
| Union Budget 2024 — infra allocation | 2024 | Infrastructure stocks + RE in metro corridors rallied |

An agent who knew these events 24 hours before the market priced them in had a massive edge. RE_OS delivers that edge systematically.

---

## News Source Universe

### Tier 1 — Real Estate Specific (Highest Signal)

| Source | Type | What to Extract |
|--------|------|-----------------|
| ET Realty (`realty.economictimes.com`) | News | Developer news, project launches, policy impact |
| BW Businessworld RE (`bwbusinessworld.com/real-estate`) | News | In-depth RE analysis, developer interviews |
| Housing.com News | News | Consumer-facing RE news, NRI sentiment |
| Square Yards Blog | Research | Market reports, quarterly data |
| Anarock Research | Research | Quarterly inventory + launch data (India's best RE data firm) |
| JLL India Research | Research | Commercial RE + residential, city-specific |
| Knight Frank India | Research | Luxury segment + overall market |
| CREDAI Press Releases | Industry body | Developer lobby positions, demand data |
| NAREDCO Updates | Industry body | Policy advocacy, RERA updates |

### Tier 2 — National Business News (Macro Policy)

| Source | Type | What to Track |
|--------|------|---------------|
| Economic Times | News | RBI policy, Union Budget, infrastructure spending |
| Business Standard | News | Policy analysis, sector coverage |
| Mint | News | Data-driven RE coverage |
| Financial Express | News | Banking + RE finance (home loans, NHB) |
| NDTV Profit | News | Markets + policy |
| Moneycontrol | News | Investor sentiment, sector funds |

### Tier 3 — Government Sources (Ground Truth)

| Source | Type | Refresh |
|--------|------|---------|
| RBI Website (`rbi.org.in`) | Monetary policy, circulars | After each MPC meeting (bi-monthly) |
| Union Budget (`indiabudget.gov.in`) | Annual + interim budgets | Annual + as-needed |
| Ministry of Housing (`mohua.gov.in`) | PMAY updates, RERA amendments | Weekly |
| RERA Karnataka (`rera.karnataka.gov.in`) | Notifications, GO amendments | Weekly |
| BDA (`bda.gov.in`) | CDP changes, ODP notifications, layouts | Weekly |
| BBMP (`bbmp.gov.in`) | Bylaw changes, property tax | Monthly |
| Karnataka Govt Portal (`karnataka.gov.in`) | State GOs, stamp duty changes | Weekly |
| KIADB (`kiadb.in`) | Industrial zone notifications | Monthly |

### Tier 4 — Social + Local (Early Signals)

| Source | Type | Signal |
|--------|------|--------|
| Twitter/X — RE journalists | Social | Breaking news before publications |
| LinkedIn — Developer posts | Social | Soft launch signals, hiring (expansion signal) |
| YouTube — Developer events | Video | Launch events, investor days |
| Local Kannada news (Vijaya Karnataka, Prajavani) | Local | Ground-level BBMP/BDA changes, ward-level infra |
| Reddit r/bangalore | Community | Buyer sentiment, broker reputation |

---

## News Intelligence Schema

```sql
-- ============================================================
-- NEWS ARTICLES
-- Every structured news item ingested
-- ============================================================
CREATE TABLE news_articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Content
    headline VARCHAR(500) NOT NULL,
    summary TEXT,                               -- LLM-generated 2-3 sentence summary
    full_text TEXT,                             -- stored if scraping allowed
    source VARCHAR(100) NOT NULL,
    source_url TEXT UNIQUE,
    author VARCHAR(200),
    published_at TIMESTAMP NOT NULL,
    scraped_at TIMESTAMP DEFAULT NOW(),

    -- Classification (LLM-assigned)
    category VARCHAR(50) NOT NULL,             -- Policy, Developer, Market, Infrastructure,
                                               -- Finance, Regulatory, International, Sector
    subcategory VARCHAR(100),                  -- RBI_Rate, BudgetAnnouncement, RERAAmendment,
                                               -- NewLaunch, LandAcquisition, MetroUpdate etc.
    geography_scope VARCHAR(20),               -- National, State, City, Micro-Market
    cities_mentioned TEXT[],                   -- [Bengaluru, Hyderabad, ...]
    markets_mentioned TEXT[],                  -- [Yelahanka, Devanahalli, ...]

    -- Impact assessment (LLM-assigned)
    sentiment VARCHAR(10),                     -- Positive, Negative, Neutral
    sentiment_score DECIMAL(3,2),              -- -1.0 to +1.0
    market_impact VARCHAR(20),                 -- Bullish, Bearish, Neutral
    impact_magnitude VARCHAR(10),              -- High, Medium, Low
    impact_score INTEGER,                      -- 1-10
    impact_timeframe VARCHAR(20),              -- Immediate, ShortTerm (0-6mo),
                                               --  MediumTerm (6-24mo), LongTerm (2yr+)

    -- Cross-references (LLM-extracted)
    developer_ids UUID[],                      -- affected developers
    micro_market_ids UUID[],                   -- affected markets
    infra_project_ids UUID[],                  -- related infra projects
    segment_affected TEXT[],                   -- [Affordable, Mid, Premium, Luxury, Commercial]

    -- Deduplication
    content_hash VARCHAR(64),                  -- SHA256 of headline+published_at
    is_duplicate BOOLEAN DEFAULT FALSE,

    -- Terminal display
    is_featured BOOLEAN DEFAULT FALSE,         -- show in top news strip
    is_alert BOOLEAN DEFAULT FALSE,            -- trigger alert push

    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- POLICY EVENTS
-- Structured extract of government policy actions
-- ============================================================
CREATE TABLE policy_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    news_article_id UUID REFERENCES news_articles(id),

    event_date DATE NOT NULL,
    policy_type VARCHAR(50) NOT NULL,          -- RBI_RateDecision, Budget, RERAAmendment,
                                               -- StampDutyChange, ZoningChange, TaxPolicy,
                                               -- InfraAllocation, PMAY_Update
    authority VARCHAR(100),                    -- RBI, GOI, Govt of Karnataka, BDA, BBMP

    -- The actual policy
    headline VARCHAR(500),
    description TEXT,
    effective_date DATE,
    applicable_geography VARCHAR(100),

    -- Quantified impact (where measurable)
    metric_name VARCHAR(100),                  -- repo_rate_pct, stamp_duty_pct, far_limit etc.
    metric_old_value DECIMAL(10,4),
    metric_new_value DECIMAL(10,4),
    metric_change DECIMAL(10,4)
        GENERATED ALWAYS AS (metric_new_value - metric_old_value) STORED,
    metric_unit VARCHAR(50),                   -- percent, INR_per_sqft, ratio

    -- RE impact estimate
    estimated_demand_impact_pct DECIMAL(5,2), -- LLM estimate: demand change %
    estimated_price_impact_pct DECIMAL(5,2),  -- LLM estimate: price change %
    segments_affected TEXT[],
    markets_affected UUID[],                   -- micro_market_ids

    source_document TEXT,                      -- GO number, Budget speech para, RBI circular
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- NEWS THEMES
-- Cluster articles into macro themes for trend analysis
-- ============================================================
CREATE TABLE news_themes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    theme_name VARCHAR(100) NOT NULL,          -- e.g., "RBI Rate Cycle", "Bengaluru Metro Expansion"
    theme_type VARCHAR(50),                    -- MonetaryPolicy, Infrastructure, Supply, Demand,
                                               --  Regulatory, Developer, Sentiment
    is_active BOOLEAN DEFAULT TRUE,
    article_count INTEGER DEFAULT 0,
    sentiment_trend VARCHAR(10),               -- Improving, Deteriorating, Stable
    last_updated TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE news_theme_articles (
    theme_id UUID REFERENCES news_themes(id),
    article_id UUID REFERENCES news_articles(id),
    relevance_score DECIMAL(3,2),
    PRIMARY KEY (theme_id, article_id)
);
```

---

## The Policy Impact Engine

This is the crown jewel. When a policy event lands, RE_OS automatically:

1. **Identifies the event** — LLM classifies from news text
2. **Quantifies the change** — extracts the actual number (rate, %, amount)
3. **Maps to affected markets** — which micro-markets, which segments
4. **Estimates impact** — using historical comps of similar policy events
5. **Fires alert** — structured impact brief to terminal + Slack

### Policy Impact Library (Historical Comps)

Seed this manually. Used by LLM to estimate future impacts:

```python
POLICY_IMPACT_LIBRARY = {
    "RBI_rate_cut_25bps": {
        "demand_impact_pct": +3.5,      # historical avg demand increase per 25bps cut
        "price_impact_pct": +1.2,       # 6-month lagged price effect
        "timeframe": "0-6 months",
        "segment_sensitivity": {
            "affordable": 5.2,           # most sensitive (EMI-driven buyers)
            "mid": 3.8,
            "premium": 1.5,
            "luxury": 0.8,
        },
        "historical_examples": ["Jun 2019 -25bps: Mumbai affordable +4.1%", "Oct 2019 -25bps: BLR mid +3.2%"]
    },
    "RBI_rate_hike_50bps": {
        "demand_impact_pct": -6.2,
        "price_impact_pct": -1.8,
        "timeframe": "0-9 months",
        "historical_examples": ["Jun 2022 +50bps: BLR registrations -12% next quarter"]
    },
    "stamp_duty_cut_2pct": {
        "demand_impact_pct": +18.0,     # very elastic — direct cost saving
        "price_impact_pct": +2.5,
        "timeframe": "0-3 months",
        "historical_examples": ["Maharashtra Sep 2020: registrations +40%", "Karnataka 2021: registrations +38%"]
    },
    "metro_station_announcement": {
        "price_impact_pct_500m": +12.0,
        "price_impact_pct_1km": +7.0,
        "price_impact_pct_2km": +3.5,
        "timeframe": "0-12 months from announcement",
        "historical_examples": ["BLR Metro Phase 2 Hebbal: PSF +14% in 500m zone post-announcement"]
    },
    # ... add more as history is built
}
```

---

## News Scraper Architecture

**File:** `scrapers/news_aggregator.py`

```python
class NewsAggregator:
    """
    Multi-source news aggregator for Indian RE market intelligence.

    Sources:
      1. RSS feeds (ET Realty, Business Standard, Mint) — no scraping needed
      2. Google News RSS — keyword-based, free
      3. NewsAPI — structured, 100 req/day free tier
      4. Direct scraping — ET Realty, BW Businessworld (Playwright for JS-heavy)
      5. Government portals — RERA Karnataka, BDA, RBI (requests + BeautifulSoup)
      6. Twitter/X API — developer accounts, RE journalists (v2 free tier: 500k reads/month)

    Run: Every 2 hours (news breaks fast)

    LLM role: Article classification + impact scoring (Cerebras fast — 8k context enough)
    """

    KEYWORD_GROUPS = {
        "bengaluru_re": [
            "Bengaluru real estate", "Bangalore property", "Yelahanka", "Devanahalli",
            "Hebbal", "North Bengaluru", "BMRCL", "BDA master plan", "BBMP bylaw"
        ],
        "karnataka_policy": [
            "Karnataka stamp duty", "Karnataka RERA", "Kaveri portal", "BDA notification",
            "KIADB", "Karnataka affordable housing", "Guidance value Karnataka"
        ],
        "india_macro": [
            "RBI repo rate", "Union Budget real estate", "PMAY", "RERA amendment",
            "NHB housing", "home loan rate", "affordable housing scheme",
            "infrastructure investment India", "smart cities mission"
        ],
        "developers": [
            "Sobha", "Brigade", "Prestige Estates", "Puravankara", "Godrej Properties",
            "Shriram Properties", "Mana Projects", "Ozone Group"
        ],
        "sector_trends": [
            "India residential sales", "housing absorption", "new launches India",
            "property price India", "NRI real estate investment", "REITs India",
            "PropTech India", "co-living India", "warehouse India"
        ]
    }

    RSS_FEEDS = [
        "https://realty.economictimes.indiatimes.com/rss/topstories",
        "https://www.business-standard.com/rss/real-estate.rss",
        "https://www.livemint.com/rss/real-estate",
        "https://housing.com/news/feed/",
        "https://rbi.org.in/scripts/RSS.aspx",  # RBI press releases
    ]

    GOOGLE_NEWS_QUERIES = [
        "Bengaluru real estate site:economictimes.com",
        "BMRCL Phase 3 site:deccanherald.com",
        "RBI repo rate real estate",
        "Union Budget housing",
    ]
```

---

## News Intelligence Agent

**New agent:** `agents/news_agent.py`

```python
"""
News Intelligence Agent
Monitors, classifies, and extracts RE intelligence from news.
Runs every 2 hours. Separate from the daily market intel pipeline.

LLM: Cerebras llama3.1-8b (fast, cheap, sufficient for classification)
Heavy analysis: Groq Scout 128k (long articles, policy documents)
"""

class NewsClassifierTool(BaseTool):
    """
    Input: raw article (headline + text)
    Output: category, subcategory, geography, sentiment, impact_score,
            affected_markets, affected_developers, policy_event_flag
    Prompt: structured JSON output enforced
    """

class PolicyImpactTool(BaseTool):
    """
    Input: policy_event record
    Output: estimated demand/price impact using POLICY_IMPACT_LIBRARY
    LLM cross-references historical comps to estimate magnitude
    """

class NewsSummaryTool(BaseTool):
    """
    Input: last 24h high-impact articles (impact_score >= 7)
    Output: morning brief section — top 5 news items with 1-line impact each
    Injected into CEO morning brief
    """
```

---

## Terminal Screens — News

### Screen: News Feed (Bloomberg-style ticker + full feed)

```
┌─────────────────────────────────────────────────────────────────────┐
│ RE_OS NEWS   [All] [Policy] [Developers] [Bengaluru] [National]     │
│━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│
│ 🔴 BREAKING  RBI holds repo at 6.5% — MPC unanimous. Impact: Neutral│
│              Home loan rates stable. Demand unaffected. [READ →]    │
│─────────────────────────────────────────────────────────────────────│
│ 🟢 HIGH      BMRCL confirms Phase 3 alignment — Yelahanka station   │
│              confirmed at Doddaballapur Road junction               │
│              Impact: BULLISH North BLR. PSF uplift est. +8-12%      │
│              Markets affected: Yelahanka ●  Devanahalli ●           │
│              [READ →] [SEE AFFECTED PROJECTS →]                     │
│─────────────────────────────────────────────────────────────────────│
│ 🟡 MEDIUM    Karnataka govt mulls stamp duty revision for first-time │
│              buyers — Budget session starting June 2026             │
│              Impact: BULLISH affordable segment if passed           │
│              [READ →] [TRACK THIS STORY →]                          │
│─────────────────────────────────────────────────────────────────────│
│ 🟡 MEDIUM    Anarock Q1 2026: Bengaluru new launches up 23% YoY     │
│              Affordable segment flat. Premium up 41%.               │
│              [READ →] [COMPARE WITH OUR DATA →]                     │
│─────────────────────────────────────────────────────────────────────│
│ ⚪ LOW       Brigade Group wins IGBC Platinum for Orchards project  │
│              [READ →]                                               │
└─────────────────────────────────────────────────────────────────────┘
```

### Screen: Policy Tracker

```
┌─────────────────────────────────────────────────────────────────────┐
│ POLICY TRACKER — Active Policies Affecting Bengaluru RE             │
├──────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ MONETARY POLICY                                                     │
│ RBI Repo Rate: 6.50% (held — last change: Feb 2025 -25bps)         │
│ Home Loan Rate (avg): 8.75%  SBI: 8.50%  HDFC: 8.75%              │
│ EMI for ₹1cr loan / 20yr: ₹86,800/month                           │
│ Status: STABLE — next MPC: Jun 6-8 2026                            │
│                                                                     │
│ STAMP DUTY (Karnataka)                                              │
│ Properties < ₹35L: 2%  ₹35L-₹45L: 3%  >₹45L: 5% + surcharge      │
│ Proposed revision: Under Budget discussion (June 2026)             │
│ Watch: If affordable reduced to 2%: est. +15% demand surge         │
│                                                                     │
│ RERA KARNATAKA                                                      │
│ Last amendment: Dec 2024 — mandatory Q1 progress reports           │
│ Pending: Carpet area definition clarification (HC petition)        │
│                                                                     │
│ CDP / ZONING                                                        │
│ BDA ODP Revision 2024: North BLR — 4 villages rezoned Agr → R2     │
│ Effective: Jan 2025. Affects: Doddaballapur, Bagalur corridors      │
│                                                                     │
│ GST (Housing)                                                       │
│ Under construction: 5% (no ITC)  Affordable: 1%  Ready to move: Nil│
│ Status: Stable since 2019                                           │
└─────────────────────────────────────────────────────────────────────┘
```

### Screen: Macro Themes Dashboard

```
┌─────────────────────────────────────────────────────────────────────┐
│ MACRO THEMES — India RE                        [30d] [90d] [1yr]   │
├──────────────────────────────────────────────────────────────────────┤
│                                                                     │
│ 🚇 METRO EXPANSION (Bengaluru)                 TREND: ↑ ACCELERATING│
│    43 articles | Sentiment: 🟢 Positive        Impact: BULLISH      │
│    Key events: Phase 3 alignment confirmed, Phase 2B 82% complete  │
│    [DRILL DOWN →]                                                   │
│                                                                     │
│ 🏦 MONETARY POLICY CYCLE                      TREND: → STABLE      │
│    28 articles | Sentiment: 🟡 Neutral         Impact: NEUTRAL      │
│    Rate hold expected through FY27. Rate cut possible Q4 FY27      │
│                                                                     │
│ 🏗️ PREMIUM SEGMENT BOOM                       TREND: ↑ STRONG      │
│    61 articles | Sentiment: 🟢 Positive        Impact: BULLISH      │
│    ₹1cr+ homes: sales up 38% YoY. NRI demand strong post-budget    │
│                                                                     │
│ 🏘️ AFFORDABLE HOUSING STRESS                  TREND: ↓ WEAKENING   │
│    34 articles | Sentiment: 🔴 Negative        Impact: BEARISH      │
│    PMAY delays, cost of construction up 12%, launches falling      │
│                                                                     │
│ 🏭 INDUSTRIAL/WAREHOUSE SURGE                 TREND: ↑ STRONG      │
│    22 articles | Sentiment: 🟢 Positive        Impact: RE adj. ↑    │
│    Devanahalli Aero Park + KIADB = workforce housing demand rising │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Critical Policy Events Calendar (Seed Data)

RE_OS maintains a forward calendar of policy events — market-moving dates known in advance:

| Event | Frequency | Next Date | RE Relevance |
|-------|-----------|-----------|--------------|
| RBI MPC Meeting | Bi-monthly | Jun 6-8, 2026 | Rate decision → home loan rates |
| Union Budget | Annual | Feb 2027 | PMAY allocation, tax sops, stamp duty guidance |
| Karnataka State Budget | Annual | Feb/Mar 2027 | Stamp duty, infra spending, BDA allocation |
| RERA Karnataka Board Meeting | Quarterly | Varies | Rule amendments, enforcement actions |
| BDA CDP Review | Annual | As notified | Zoning changes |
| BMRCL Board Meeting | Quarterly | Varies | Phase 3 updates, station confirmations |
| CREDAI NATCON | Annual | Oct/Nov | Industry positions, demand forecasts |
| JLL Annual Report | Annual | Jan | India market sizing |
| Anarock Quarterly Report | Quarterly | Jan/Apr/Jul/Oct | City-wise sales + supply data |
| Knight Frank Wealth Report | Annual | Mar | Luxury segment |

These go into a `policy_calendar` table — terminal shows upcoming events with estimated market impact.

---

## News Alert Rules

| Trigger | Condition | Alert Priority |
|---------|-----------|----------------|
| RBI rate change | Any rate move | P0 — immediate |
| Stamp duty change | Karnataka or National | P0 — immediate |
| BMRCL Phase 3 news | Any confirmation/delay | P0 — immediate |
| BDA CDP notification | Zone change in target markets | P0 — immediate |
| RERA amendment | Karnataka rule change | P1 — same day |
| Developer IPO/listing | Any Grade-A developer | P1 — same day |
| Budget announcement | RE-relevant allocation | P0 — during Budget speech |
| NCLT/NCDRC order | Against tracked developer | P1 — same day |
| Guidance value revision | Karnataka SRD notification | P1 — same day |
| PM/CM infrastructure speech | Bengaluru infrastructure | P2 — daily digest |
| Anarock/JLL quarterly report | Published | P2 — weekly digest |

---

## Integration with Morning Brief

News intelligence feeds directly into the CEO agent's morning brief:

```
RE_OS MORNING BRIEF — Policy & News Section

POLICY STATUS (as of today)
  RBI Repo: 6.50% (stable) | Home Loan: 8.75% avg
  Stamp Duty Karnataka: 5% (>₹45L) — watch June Budget for revision
  RERA: No new amendments. Last: Dec 2024.

TOP NEWS — Last 24 Hours
  🔴 HIGH: BMRCL Phase 3 EIA submitted to MoEF — clearance expected Q3 2026.
     Implication: Construction start 6-8 months ahead of previous estimate.
     Yelahanka/Devanahalli land values: BUY window closing.

  🟡 MEDIUM: ET Realty — Bengaluru premium launches Q1 2026 up 41% YoY.
     Our data confirms: North BLR absorption 65%+ across Grade-A projects.
     Consistent signal.

  ⚪ LOW: Godrej Properties acquires land in South Bengaluru (Sarjapur).
     Not in target markets. Monitor for Phase 2 expansion.

MACRO THEME WATCH
  Metro Expansion: ACCELERATING. Phase 3 EIA is key milestone.
  Rate Cycle: STABLE. No rate risk near-term.
  Affordable Stress: ONGOING. Not relevant to North BLR premium corridor.

ACTION FOR LLS
  → Phase 3 EIA submission is a hard catalyst. Historical comp: Phase 2B
    EIA approval in 2019 → land prices in 1km zone up 18% in 12 months.
    Current North BLR land at ₹3,500-5,000/sqft. Target: acquire before
    full alignment map published (est. Q4 2026).
```

---

## Implementation Sequence

### Sprint 1 — RSS + Google News (No Scraping, No API Cost)
1. `scrapers/news_aggregator.py` — RSS feed parser for 6 sources
2. Google News RSS queries (free, no API key)
3. Store in `news_articles` table
4. LLM classify: Cerebras — category, sentiment, impact_score

### Sprint 2 — Policy Tracker (Manual + Semi-Auto)
1. `policy_events` table — manually seed current policies (repo rate, stamp duty, GST)
2. `policy_calendar` table — seed upcoming dates (MPC, Budget, RERA board)
3. Terminal screen: Policy Tracker

### Sprint 3 — NewsAPI Integration
1. NewsAPI free tier: 100 req/day, 1 month history
2. Keyword groups above → fetch structured articles
3. Deduplication against existing headlines

### Sprint 4 — News Agent + Morning Brief Integration
1. `agents/news_agent.py` — runs every 2hr via scheduler
2. News summary injected into CEO morning brief prompt
3. Alert rules → trigger `developer_events` + Slack

### Sprint 5 — Deep Source Scraping
1. ET Realty full article scraper (Playwright)
2. RERA Karnataka notification page (requests + BeautifulSoup)
3. BDA notification page scraper
4. RBI circular RSS full-text parser

### Sprint 6 — Theme Clustering + Macro Dashboard
1. LLM theme assignment per article
2. `news_themes` aggregation queries
3. Terminal: Macro Themes screen
4. Sentiment trend chart (30d / 90d)

---

## Files to Create / Modify

```
NEW:
  scrapers/news_aggregator.py     — RSS + NewsAPI + Google News
  scrapers/govt_portals.py        — RERA Karnataka, BDA, RBI circular scrapers
  agents/news_agent.py            — News classification + policy impact agent
  utils/news_organizer.py         — DB upserts for news_articles, policy_events

MODIFY:
  database/schema.sql             — news_articles, policy_events, news_themes tables
  agents/ceo_agent.py             — inject news summary into morning brief prompt
  config/scheduler.py             — add 2-hr news scrape job
  crews/market_intel_crew.py      — optionally add news_agent to pipeline
```

---

## The Edge This Creates

A real estate professional using RE_OS knows:
- **RBI rate move** → impact on home loan EMIs → demand impact estimate → which segments, which markets
- **BMRCL announcement** → which stations, which land parcels in influence zone → how much already priced in
- **BDA CDP change** → which villages newly developable → which developers likely to move first
- **Karnataka Budget** → stamp duty change → registration volume forecast for next quarter

None of this requires a newspaper subscription, a research subscription, or a consultant. It's all inside RE_OS, structured, scored, and cross-referenced to the actual projects and parcels in the database.

That is the Bloomberg edge applied to Indian real estate.

---

*Plan authored: 2026-05-13*
*Companion to: plans/bloomberg_re_terminal_plan.md, plans/data_moat_deep_plan.md, plans/developer_intelligence_plan.md*
