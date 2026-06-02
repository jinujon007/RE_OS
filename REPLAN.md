# RE_OS v2 — Complete Redesign
**Date: 2026-06-02 | Author: Claude Code | Status: REVIEW DRAFT**

---

## The Problem With the Current Plan

177 tasks across 19 sprints. Each sprint adds a feature. Features don't talk to each other. The system answers questions you already know to ask.

A land acquisition manager should wake up to:
> *"Devanahalli — 4.8 acres, Sy No 112/3. Brigade delayed by 14 months, distress score 0.79. IGR transaction PSF Rs4,800 vs listing Rs6,200. JD IRR 24.3%. Litigation clean. AIZ clear. Absorption accelerating. Act in next 21 days — BDA sanction expires."*

The current plan cannot produce that. It can run a Board Room if you ask it to. That is not the same thing.

**The gap:** reactive system vs proactive system.

---

## Five Architectural Failures in the Current Plan

**1. Schema designed incrementally (32 migrations planned)**
Every sprint adds tables. No one designed the full data model first. The result: foreign key gaps, no data lineage, tables that don't join correctly, and migrations that break on fresh deploy (Bug 3 is already evidence).

**2. Six scrapers with six different patterns**
RERA uses Playwright. Kaveri uses requests. Portal uses Scrapling. Each has its own retry logic, its own dedup, its own error handling. Adding IGR and Bhoomi makes it eight. The Unified Ingest Engine fixes this in one sprint.

**3. Intelligence is isolated in agents**
The Board Room BD Head doesn't know what the Legal Head knows. The Analyst doesn't know what the Distressed Developer Scanner found. Information is in different tables, injected separately into different agents. There is no shared knowledge state.

**4. The primary output is a text report**
After a full pipeline run, the output is a `.txt` file in `outputs/`. A developer making a Rs10Cr decision needs a structured, numbered verdict — not prose. The Deal Memo (Sprint 42) is the right direction but it's too late in the plan and not connected to the Opportunity Engine.

**5. No proactive surface**
Nothing in the current plan runs unprompted and tells Jinu *"here is the best opportunity available right now, here is why, here is what to do next."* The Opportunity Queue concept in Sprint 56 is a CRM for deals already in progress. That's not the same thing.

---

## The v2 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    OPPORTUNITY QUEUE                        │
│   "Top 5 actionable opportunities — updated nightly"        │
│   Each entry: score, survey_no, action, expiry, deal_type   │
└────────────────────┬────────────────────────────────────────┘
                     │ feeds
┌────────────────────▼────────────────────────────────────────┐
│                 OPPORTUNITY ENGINE (nightly)                 │
│   Scores every known survey + developer + market            │
│   Inputs: all 5 intelligence modules below                  │
└──┬──────────┬──────────┬──────────┬──────────┬─────────────┘
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
MARKET     LEGAL      FINANCE    LAND       DEMAND
INTEL      INTEL      INTEL      INTEL      INTEL
(supply,   (title,    (IRR,      (RTC,      (DOM,
 RERA,      litiga-    JD/JV,     owner-     config,
 news,      tion,      cash       ship,      ticket,
 sentiment) Khata,     flow,      aggre-     NRI)
            zone)      bench)     gation)

All 5 modules read from ONE knowledge store (below)

┌─────────────────────────────────────────────────────────────┐
│                   KNOWLEDGE STORE                           │
│   PostgreSQL + PostGIS                                      │
│   Entities: Survey | Developer | Project | Market | Deal    │
│   Facts: typed, source-cited, confidence-scored             │
│   Designed upfront. One migration. All tables present.      │
└─────────────────────────────────────────────────────────────┘
                     ▲
┌────────────────────┴────────────────────────────────────────┐
│                UNIFIED INGEST ENGINE                        │
│   One HTTP client (Scrapling). One retry policy.            │
│   One dedup system. One error envelope.                     │
│   All data sources as plugins:                              │
│   RERA | IGR | Kaveri | Bhoomi | Portals | Devs | News      │
│   SARFAESI | BDA | Indiankanoon | BBMP Khata                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    OUTPUT LAYER                             │
│   Deal Memo (auto, on demand, PDF)                          │
│   Investor Brief (market data + IRR + benchmark)            │
│   Telegram (field verdict, 3 min)                           │
│   Dashboard (mission control, opportunity queue)            │
│   Discord (async alerts)                                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase Structure — 5 Phases, ~55 Tasks, 10 Weeks

### Phase 0 — Schema First (Week 1, 8 tasks)
**Design the complete data model before writing one line of application code.**

Current plan has 32 Alembic migrations planned. v2 has one. Every table exists from day one. Foreign keys are correct. Joins work. Data lineage is built in.

**Complete entity list:**

| Entity | Purpose |
|--------|---------|
| `surveys` | Land parcels — the atomic unit of every acquisition decision |
| `developers` | Entities with RERA track record, health score, alias list |
| `projects` | RERA-registered projects (existing 16-table schema + extensions) |
| `markets` | Yelahanka / Devanahalli / Hebbal |
| `facts` | Typed, confidence-scored, source-cited knowledge items |
| `igr_transactions` | Actual sale deed registrations |
| `rtc_records` | Bhoomi agricultural ownership records |
| `khata_records` | BBMP Khata status |
| `litigations` | Indiankanoon court records per survey |
| `distressed_opps` | SARFAESI + BDA auctions |
| `developer_health` | Rolling distress scores |
| `demand_signals` | DOM, config absorption, ticket size, NRI % |
| `deals` | Pipeline: lead → signed. Full CRM. |
| `deal_memos` | Generated memos, versioned |
| `lls_projects` | VEL + future LLS projects, milestones |
| `agreements` | Development agreements, milestone tracker |
| `compliance_log` | LLS RERA filing deadlines |
| `opportunity_scores` | Nightly scored opportunities, ranked |
| `ingest_log` | Every scraper run: source, status, records, freshness |
| `board_sessions` | Board Room transcripts (existing) |
| `agent_memories` | (existing) |

**Tasks:**

| ID | Task |
|----|------|
| V2-001 | Write `database/schema_v2.sql` — complete schema, all 20 tables, all FK constraints, all indexes, PostGIS extensions, views; single source of truth |
| V2-002 | Write `alembic/versions/0100_v2_schema.py` — one migration that creates everything not in current schema; idempotent; backward compatible with existing 16 tables |
| V2-003 | `database/views_v2.sql` — 6 computed views: v_opportunity_queue, v_developer_health, v_market_pulse, v_survey_full_picture, v_deal_pipeline_kanban, v_data_freshness |
| V2-004 | `database/seed_v2.sql` — all reference data: AIZ zones, soil risk zones, developer aliases, regulatory zones, BDA zone rules; one idempotent seed file |
| V2-005 | `utils/db_v2.py` — typed query helpers for every table; no raw SQL in application code; connection pool with health check |
| V2-006 | Schema validation test — `tests/test_schema_v2.py`: every table exists, every FK valid, every index present, all views return without error |
| V2-007 | Migrate existing data — script to populate new tables from existing 16 tables; zero data loss |
| V2-008 | Update CLAUDE.md with complete v2 schema documentation |

---

### Phase 1 — Unified Ingest Engine (Week 2–3, 12 tasks)
**One scraper base class. All data sources as plugins. Replace 8 scattered scrapers.**

**Current:** 8 different files, 8 different patterns, 8 different dedup schemes.
**v2:** One `IngestEngine` with a plugin interface. Every source is a `DataPlugin`. The engine handles HTTP, retry, rate limiting, dedup, error envelopes, and ingest logging. Plugins only handle extraction.

**Plugin interface:**
```python
class DataPlugin(ABC):
    source_id: str          # "igr_karnataka", "rera_karnataka", etc.
    rate_limit_rps: float   # requests per second
    cache_ttl_hours: int    # how long results are valid

    @abstractmethod
    def fetch(self, market: str, **kwargs) -> list[RawRecord]: ...

    @abstractmethod
    def parse(self, raw: RawRecord) -> list[ParsedRecord]: ...

    @abstractmethod
    def validate(self, parsed: ParsedRecord) -> ValidationResult: ...
```

**Standard envelope — every record from every source:**
```python
@dataclass
class ParsedRecord:
    source_id: str
    market: str
    entity_type: str        # "project" | "transaction" | "listing" | "litigation"
    entity_id: str          # natural key (survey_no, rera_no, etc.)
    data: dict
    confidence: float       # 0–1
    scraped_at: datetime
    raw_hash: str           # SHA-256 for dedup
    validation_errors: list[str]
```

**Tasks:**

| ID | Task |
|----|------|
| V2-009 | `ingest/engine.py` — IngestEngine: plugin registry, parallel fetch with ThreadPoolExecutor, unified rate limiter per source, exponential backoff, SHA dedup via ingest_log, error envelope, ingest_log write on every run |
| V2-010 | `ingest/base.py` — DataPlugin ABC + ParsedRecord + ValidationResult dataclasses |
| V2-011 | `ingest/plugins/rera_plugin.py` — RERA Karnataka as DataPlugin (replace scrapers/rera_karnataka.py) |
| V2-012 | `ingest/plugins/igr_plugin.py` — IGR Karnataka transactions as DataPlugin |
| V2-013 | `ingest/plugins/kaveri_plugin.py` — Kaveri guidance values + Bhoomi RTC as DataPlugin; try 3 endpoints in order, log which succeeded |
| V2-014 | `ingest/plugins/portal_plugin.py` — 99acres / MagicBricks / Housing as DataPlugin (replace portal_scout.py) |
| V2-015 | `ingest/plugins/developer_plugin.py` — Brigade / Prestige / Sobha etc. as DataPlugin |
| V2-016 | `ingest/plugins/news_plugin.py` — Google News + ET Realty as DataPlugin |
| V2-017 | `ingest/plugins/distressed_plugin.py` — SARFAESI + BDA auctions + Indiankanoon as DataPlugin |
| V2-018 | `ingest/plugins/bbmp_plugin.py` — BBMP Khata status as DataPlugin |
| V2-019 | `tests/test_ingest_engine.py` — >=15 tests: plugin registry, dedup by hash, rate limit enforcement, error envelope, ingest_log write, parallel fetch, partial failure graceful |
| V2-020 | Scheduler: replace 6 separate cron jobs with `IngestEngine.run_all(markets)` at 02:00 IST; per-plugin schedules configurable in settings |

---

### Phase 2 — Intelligence Modules (Week 3–5, 15 tasks)
**Five focused modules. Each reads from the Knowledge Store. Each writes computed facts back.**

Not agents. Not LLM calls. Deterministic Python functions that read the DB and return structured intelligence. The Board Room agents consume these — they don't compute them.

**Module 1 — Market Intel**
```python
class MarketIntel:
    def get_pulse(self, market: str) -> MarketPulse:
        # Returns: active_projects, avg_psf (IGR), months_supply,
        # absorption_trend (ACCELERATING/STABLE/DECELERATING),
        # sentiment (FinBERT score), news_signal_count
```

**Module 2 — Legal Intel**
```python
class LegalIntel:
    def get_survey_picture(self, survey_no: str, market: str) -> SurveyPicture:
        # Returns: TitleRiskChecklist (8 flags), litigation_status,
        # khata_type, encumbrance_status, zone_risk, aiz_flag
```

**Module 3 — Financial Intel**
```python
class FinancialIntel:
    def evaluate(self, survey_no: str, market: str,
                 ask_psf: int, area_acres: float,
                 deal_type: str = "compare") -> FinancialEvaluation:
        # Returns: Purchase IRR, JD IRR, JV IRR, peak_drawdown,
        # cp_brokerage, escalation scenarios, verdict per structure
```

**Module 4 — Land Intel**
```python
class LandIntel:
    def get_land_picture(self, survey_no: str, market: str) -> LandPicture:
        # Returns: RTC ownership (from Bhoomi), DC status,
        # co_owner_count, aggregation_opportunity, assembly_status
```

**Module 5 — Demand Intel**
```python
class DemandIntel:
    def get_signals(self, market: str) -> DemandSignals:
        # Returns: median_dom, fastest_config, ticket_distribution,
        # nri_pct, price_revision_rate, psf_bias (listing vs IGR)
```

**Tasks:**

| ID | Task |
|----|------|
| V2-021 | `intelligence/market_intel.py` — MarketIntel module; all signals from DB; no LLM; <100ms per call |
| V2-022 | `intelligence/legal_intel.py` — LegalIntel module; TitleRiskChecker + litigation + Khata + zone |
| V2-023 | `intelligence/financial_intel.py` — FinancialIntel module; all IRR models + cash flow + escalation |
| V2-024 | `intelligence/land_intel.py` — LandIntel module; RTC + landowner CRM + aggregation |
| V2-025 | `intelligence/demand_intel.py` — DemandIntel module; DOM + config + ticket + NRI + PSF bias |
| V2-026 | `intelligence/registry.py` — IntelRegistry: single entry point, `get_full_picture(survey_no, market, ask_psf, deal_type)` calls all 5 modules, assembles IntelPackage; memoized 1h |
| V2-027 | `tests/test_intelligence_modules.py` — >=20 tests across all 5 modules; each module tested in isolation with fixture data |

**Opportunity Engine (the system's brain):**

| ID | Task |
|----|------|
| V2-028 | `intelligence/opportunity_engine.py` — OpportunityEngine.score_all(market): for every survey_no in DB + every known distressed opportunity: run IntelRegistry.get_full_picture(); compute opportunity_score = f(IRR, legal_risk, market_timing, developer_distress, deal_availability); store in opportunity_scores table |
| V2-029 | OpportunityScore formula: `score = (irr_score * 0.30) + (legal_score * 0.20) + (timing_score * 0.20) + (distress_score * 0.15) + (exclusivity_score * 0.15)`; each component 0–1; overall 0–1; threshold: >0.70 = SURFACE, 0.50–0.70 = WATCH, <0.50 = IGNORE |
| V2-030 | Scheduler: OpportunityEngine.score_all() runs nightly at 03:00 IST after IngestEngine completes; writes top-10 per market to opportunity_scores; Discord alert if any score >0.80 |
| V2-031 | `tests/test_opportunity_engine.py` — >=12 tests: score formula, threshold labels, top-N ranking, partial data graceful, Discord mock on >0.80 |

---

### Phase 3 — Decision Layer (Week 5–7, 12 tasks)
**Board Room, Deal Memo, Investor Brief — all consuming IntelPackage, not recomputing.**

**The key architectural change:** Board Room agents receive a pre-computed IntelPackage. They don't call tools. They interpret structured data and form strategic opinions. This makes them faster, cheaper, and more consistent.

**Current Board Room:** Each agent calls its own tools, queries its own data, forms its own context. Duplicate DB queries. Inconsistent data (Legal Head may see different RERA data than Finance Head if the DB updated mid-session).

**v2 Board Room:**
```python
# One DB read. One IntelPackage. All agents get the same data.
intel = IntelRegistry.get_full_picture(survey_no, market, ask_psf, deal_type)
board_session = BoardRoom.convene(pitch, intel)
# Each agent receives intel as structured context, not as tool access
```

| ID | Task |
|----|------|
| V2-032 | `crews/board_room_v2.py` — BoardRoom.convene(pitch, intel_package): passes IntelPackage to all 5 dept heads; agents receive structured data not raw prompts; one DB read per session not N |
| V2-033 | Update all 5 board_room agent system prompts — remove tool calls from agents; prompts now say "You receive a structured IntelPackage. Interpret it from your department's lens." |
| V2-034 | `utils/deal_memo_v2.py` — DealMemoGenerator.generate(intel_package) — consumes IntelPackage directly; no secondary DB calls; all 7 sections populated from one data structure |
| V2-035 | `utils/investor_brief_v2.py` — InvestorBriefGenerator.generate(intel_package) — investor-facing output from same IntelPackage; includes PeerBenchmark from MarketIntel |
| V2-036 | `/api/evaluate` POST — single endpoint: {survey_no, market, ask_psf, area_acres, deal_type} → runs IntelRegistry → runs BoardRoom → generates DealMemo → generates InvestorBrief; returns all three; saves to DB |
| V2-037 | `/api/opportunity/queue` GET — returns ranked opportunity_scores for all markets; includes next_action per opportunity; market filter; auth-protected |
| V2-038 | Deal pipeline v2 — `deals` table now links to opportunity_scores; one-click "start evaluation" from queue runs /api/evaluate automatically |
| V2-039 | `utils/deal_pipeline_v2.py` — DealPipelineManager: stage transitions, velocity tracking, exclusivity check, competing developer alert; all from deals table |
| V2-040 | `tests/test_board_room_v2.py` + `tests/test_deal_memo_v2.py` — >=15 tests: IntelPackage consumed correctly, all sections present, consistent data across agents |

---

### Phase 4 — Interface (Week 7–8, 8 tasks)
**Three interfaces. One data source. Telegram is primary.**

Telegram is primary because that's where decisions happen — in the field, on a site visit, before you're back at your desk. The dashboard is mission control. Discord is async monitoring.

| ID | Task |
|----|------|
| V2-041 | `interface/telegram_bot.py` — FieldMessageParser + bot: parse → /api/evaluate → compact verdict (200 chars/dept + RECOMMENDATION badge); async, 3-minute target; handles site-visit quality input |
| V2-042 | `interface/dashboard_v2.py` — Flask + HTMX dashboard, rebuilt around Opportunity Queue as homepage: ranked opportunities table with one-click evaluate; market pulse cards; deal pipeline Kanban; data freshness panel |
| V2-043 | Dashboard Opportunity Queue panel — primary homepage panel: ranked opportunities, score bar, deal type badge, expiry countdown, "Evaluate" button; auto-refresh 5 min |
| V2-044 | Dashboard Heat Map panel — Leaflet.js PSF heat map; listings geocoded via Nominatim; colored by PSF band; market selector |
| V2-045 | Dashboard Deal Pipeline — Kanban (lead→signed); velocity metrics; bottleneck stage highlighted |
| V2-046 | `/api/intel/search` — semantic search over intel reports (existing ChromaDB); enhanced with IntelPackage indexing |
| V2-047 | `interface/discord_v2.py` — unified Discord notifier; 6 channel types; all alerts (distressed dev, opportunity >0.80, data stale, compliance deadline, competitor launch, system health) |
| V2-048 | `tests/test_interface.py` — >=10 tests: Telegram parse, compact verdict format, dashboard endpoints, opportunity queue ranking, Discord formatters |

---

### Phase 5 — Compounding Intelligence (Week 8–10, 8 tasks)
**The system gets smarter over time. Not through fine-tuning. Through feedback loops.**

| ID | Task |
|----|------|
| V2-049 | Shareholder Personas — 4 agents reviewing every Board Room session from distinct investment lenses; one sentence each; YAML spec; HEAVY LLM tier |
| V2-050 | `intelligence/feedback_loop.py` — when a deal closes (won/lost), write outcome back to opportunity_scores: was the score predictive? Over time this calibrates the scoring formula |
| V2-051 | LLS Compliance Calendar — RERA filing deadlines for LLS's own projects; VEL seeded at Seed Funding milestone; daily scheduler check + Discord alert |
| V2-052 | Developer alias disambiguation — canonical names + variant lookup; RERAComplianceChecker uses canonical |
| V2-053 | Data Quality Monitor — freshness scores per source; PSF bias (listing vs IGR); cross-source validation; daily 09:00 IST; Discord stale alert |
| V2-054 | Process Optimizer (Phase 9 concept) — reads ingest_log + board_sessions; flags: sources with >20% error rate, agents with >60s response time, opportunities scored >0.80 that were never acted on |
| V2-055 | `tests/test_compounding.py` — >=10 tests: feedback loop write, alias disambiguation, compliance deadline calc, data quality scores |
| V2-056 | Full end-to-end test — `tests/test_e2e.py`: seed 3 surveys → IngestEngine → OpportunityEngine → /api/opportunity/queue returns ranked list → /api/evaluate on top result → DealMemo + InvestorBrief generated → DealPipeline entry created → Telegram verdict formatted |

---

## What Gets Deleted From the Current Plan

These 50+ tasks from the current 177 become unnecessary or are absorbed:

| Deleted Tasks | Why |
|---------------|-----|
| T-476, T-502, T-511, T-519, T-554, T-556, T-577, T-583, T-586, T-596, T-629, T-633, T-643 (13 individual migration tasks) | Replaced by V2-001/V2-002 — one complete schema upfront |
| T-483 (Kaveri portal fix as isolated task) | Absorbed into V2-013 (Kaveri as IngestEngine plugin) |
| T-484/T-485 (months_of_supply wiring) | Absorbed into MarketIntel module (V2-021) |
| T-505/T-506 (absorption tracker + wiring) | Absorbed into MarketIntel module |
| T-509/T-510 (DealMemoGenerator v1) | Replaced by V2-034 (DealMemoGenerator v2 from IntelPackage) |
| T-524/T-525 (CP commission + price reduction scrapers) | Absorbed into DeveloperHealth in IntelRegistry |
| T-539 (geocoding as separate task) | Absorbed into portal_plugin.py (V2-014) |
| T-563/T-564/T-565/T-566/T-567 (5 separate IRR tasks) | Absorbed into FinancialIntel module (V2-023) |
| T-604 (listing dates migration) | In schema_v2.sql (V2-001) |
| T-605/T-606/T-607/T-608/T-609 (5 demand tracker tasks) | Absorbed into DemandIntel module (V2-025) |
| T-642/T-643/T-644 (data quality log + scheduler) | Absorbed into V2-053 |
| Sprints 32–38 (HF work, 7 sprints) | Deferred until Phase 5 business value is delivered |

---

## Task Count Comparison

| | Current Plan | v2 Plan |
|--|-------------|---------|
| Total tasks | 177 | 56 |
| Sprints / phases | 19 | 5 |
| DB migrations | 32 | 1 |
| Scraper files | 8+ | 1 engine + 8 plugins |
| Intel computation location | Inside agents (at query time) | Intelligence modules (pre-computed) |
| Primary output | Text report | Ranked Opportunity Queue |
| System behavior | Reactive (answers when asked) | Proactive (surfaces best opportunity daily) |
| Test coverage target | Per-feature | End-to-end pipeline |

---

## The Three Design Decisions That Make It 100x

**1. IntelPackage as the unit of information**

Everything computed once, stored as a structured object, consumed by all downstream systems (Board Room, Deal Memo, Investor Brief, Telegram). No agent recomputes what another agent already computed. No inconsistency between what the Legal Head and Finance Head saw.

**2. Opportunity Score as the primary output**

The system's job is not to answer questions. It is to surface the best land acquisition opportunity available right now, quantified, with a clear next action. This is the thing that makes RE_OS a competitive weapon, not an intelligence library.

**3. Schema first, features second**

32 migrations = 32 moments where the data model was not fully thought through. One complete schema = one moment of serious design that everything else is built on. The view `v_opportunity_queue` does in SQL what the current plan requires 3 agents and 2 API calls to produce.

---

## Sequencing

```
Week 1:   Phase 0 (Schema) → everything else is possible
Week 2-3: Phase 1 (Ingest) → data starts flowing into clean tables
Week 3-5: Phase 2 (Intel)  → five modules + Opportunity Engine
Week 5-7: Phase 3 (Decision) → Board Room v2 + Deal Memo + Investor Brief
Week 7-8: Phase 4 (Interface) → Telegram + Dashboard v2
Week 8-10: Phase 5 (Compound) → Shareholder, Feedback, Optimizer
```

First working output: **End of Week 3** — Opportunity Queue populated with scored opportunities from live RERA + IGR data. No Board Room. No agents. Just ranked, scored land opportunities.

First complete decision flow: **End of Week 7** — Telegram message → IntelPackage → Board Room → Deal Memo → Pipeline entry. Under 5 minutes, field-quality input tolerated.

---

## Open Questions Before v2 Starts

1. **Migrate or parallel-build?** v2 can run alongside v1 (new `ingest/` and `intelligence/` packages don't conflict with existing scrapers). Or full cutover. Recommendation: parallel-build through Phase 2, cutover at Phase 3. Existing Board Room stays live until v2 Board Room passes GATE.

2. **The HF sprints (32–38):** Defer all until Phase 5 is complete. BGE-M3 and QLoRA are engineering ambition. The Opportunity Queue is business value. Do business value first.

3. **VEL milestone seeding:** VEL is at Seed Funding. The 8-milestone template starts from Land Identification. Jinu seeds the target dates when known. The tracker is live from Phase 0 (lls_projects is in schema_v2.sql).

---

*This document supersedes the 177-task plan in TASK_QUEUE.md for architectural direction.*
*TASK_QUEUE.md remains valid for Kilo Code execution — tasks can be picked up in v2 phase order.*
*Review this document. Decide: migrate to v2 or continue v1? Both are valid. v2 is just 100x better.*
