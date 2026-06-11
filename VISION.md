# RE_OS — Virtual Real Estate Office: Vision & Roadmap
**v1.5 — 2026-06-11 | Owner: Jinu Joshi | LLS**

---

## The Vision

RE_OS becomes a complete Virtual Real Estate Office — a living org chart where every department runs autonomously, reports up the chain, and executes on instructions from Jinu via a Mission Control web interface.

The analogy: you own the company. You don't do the work. You set direction, approve decisions, read outcomes — and hire new people when the work demands it. Every employee (agent) has a role, a memory, a reporting line, and a personality. The org chart grows as you grow. You can address one agent directly, call a board meeting, or post a job opening — and a new specialist joins the team within minutes, no code changes needed.

The output of every agent feeds the institutional knowledge base. Nothing is lost. Nothing is filed and forgotten. Intelligence compounds.

---

## What Exists Today

| Component | Status | Location |
|-----------|--------|----------|
| CEO Agent (orchestrator) | ✅ Live | `agents/ceo_agent.py` |
| Scraper Agent (RERA + listings) | ✅ Live | `agents/scraper_agent.py` |
| Analyst Agent (market briefs) | ✅ Live | `agents/analyst_agent.py` |
| PostgreSQL + PostGIS + Redis | ✅ Live | Docker Compose |
| Scheduler (2AM cron) | ✅ Live | `config/scheduler.py` |
| RERA Scout | ✅ Live | `scrapers/rera_karnataka.py` |
| News Scout | ✅ Live — in pipeline | `scrapers/news_scout.py` |
| Portal Scout | ✅ Live — in pipeline | `scrapers/portal_scout.py` |
| Developer Scout | ✅ Live — in pipeline | `scrapers/developer_scout.py` |
| RERA Detail Scout | ✅ Live — in pipeline (session fix pending T-207) | `scrapers/rera_detail_scout.py` |
| Scout Memory (dedup) | ✅ Live | `scrapers/scout_memory.py` |
| Sentinel Agent (system health) | ✅ Live — docker-compose healthcheck | `agents/sentinel_agent.py` |
| Kaveri Scout | ✅ Live — guidance values + registrations | `scrapers/kaveri_karnataka.py` |
| Dashboard Flask backend | ✅ Live — /api/health, port 8050 | `dashboard/app.py` |
| Dashboard UI | ✅ Live — Org Chart, Intel Board, Task Board, Log Stream, Board Room, Sentinel, Pipeline Control, DB Explorer, Live Feed | `dashboard/templates/` |
| Board Room crew | ✅ Live — 5 dept heads (BD/Finance/Engineering/Ops/Legal), action extraction, approval UI | `crews/board_room.py` |
| Agent Memory layer | ✅ Live — read/write/decay/confidence, weekly decay job, pipeline injection, Memory Explorer panel, conflict badge | `utils/agent_memory.py`, `dashboard/templates/memory_explorer.html` |
| Parser Agent | 🔵 Standalone only | `agents/parser_agent.py` |
| Organizer Agent | 🗑️ Removed — replaced by `utils/db_organizer.py` | — |
| 3-market pipeline | ✅ Live — Yelahanka, Devanahalli, Hebbal | `crews/market_intel_crew.py` |
| Enterprise tests + CI | ✅ Live — pytest, ruff, .github/workflows | `tests/` |

**Status as of 2026-06-11:** All 14 phases complete. GATE-87 LAUNCH GATE PASSED — 6/6 assertions. 87 gates total. RE_OS declared production-ready. 33 scheduler jobs registered. Pipeline runs across Yelahanka, Devanahalli, Hebbal. 1,824+ unit tests green.

---

## Target Architecture

```
╔══════════════════════════════════════════════════════════════════╗
║                   MISSION CONTROL  (Web UI)                      ║
║   Org chart · Direct comms · Board Room · Task board · Logs      ║
╚══════════════════════════════════════════════════════════════════╝
                               │  Jinu's instructions
                               ▼
╔══════════════════════════════════════════════════════════════════╗
║           BOARD OF SHAREHOLDERS  (4 members)                     ║
║  [Cautious Investor] [Growth Seeker] [Risk Hawk] [Visionary]     ║
║  Strategic review · Approve major decisions · Hold CEO account.  ║
╚══════════════════════════════════════════════════════════════════╝
                               │  appoints + holds accountable
                               ▼
╔══════════════════════════════════════════════════════════════════╗
║                          CEO                                     ║
║             Orchestrator. Decomposes. Delegates.                 ║
╚══════════════════════════════════════════════════════════════════╝
     │           │           │           │           │          │
     ▼           ▼           ▼           ▼           ▼          ▼
ENGINEERING   FINANCE    PR & BRAND  OPERATIONS   LEGAL    PROCESS
   DEPT        DEPT        DEPT        DEPT        DEPT    AUTOMATION

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ENGINEERING DEPARTMENT
├── Div A — Creative Engineering
│   ├── Architect Agent         (FSI, typology, floor plates, amenities)
│   └── Renderer Agent          (image briefs for Midjourney / DALL-E)
├── Div B — Tech Engineering
│   ├── Tool Builder Agent      (builds scrapers, APIs, internal tools)
│   ├── Process Mapper Agent    (SOPs, flowcharts, workflow design)
│   └── The Optimizer (Thinker) (watches all agents, cuts token waste,
│                                proposes efficiency improvements)
└── Div C — Scout Division      (tech-dependent: tools built by Div B)
    ├── RERA Scout              (live RERA approvals + project data)
    ├── Portal Scout            (99acres, MagicBricks, Housing.com)
    ├── News Scout              (real estate news, press, signals)
    ├── Developer Scout         (competitor tracking, launches)
    └── Kaveri Scout            (registration data, guidance values)

FINANCE DEPARTMENT
├── Finance Head Agent          (financial strategy, reports to CEO)
└── Feasibility Analyst         (land cost, GDV, IRR scenarios)

PR & BRAND DEPARTMENT
├── PR Head Agent               (brand narrative, press, positioning)
├── Social Media Agent          (LinkedIn, Instagram, content calendar)
└── Content Writer Agent        (project copy, marketing collateral)

OPERATIONS DEPARTMENT
├── Operations Head             (cross-dept manager, reports to CEO)
├── Project Manager(s)          (one per active project — owns lifecycle)
└── Dept Manager Liaisons       (bridges CEO to each dept head)

LEGAL DEPARTMENT
├── Legal Head Agent            (real estate law, strategy, risk)
└── Compliance Researcher       (RERA, BDA, BBMP, encumbrance, title)

PROCESS AUTOMATION TEAM
├── Log Analyst Agent           (reads all crew logs continuously)
├── Efficiency Optimizer        (finds waste, proposes process fixes)
└── Runbook Documenter          (writes SOPs from observed patterns)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DATA LAYER
  PostgreSQL/PostGIS · Redis task queue · Scout Memory (dedup)
  Agent Registry · Agent Memories · Board Transcripts · Run Logs
```

---

## Mission Control Interface

One web app. Two modes. One source of truth for everything happening in the office.

### Mode 1 — Direct Comms
- Org chart on screen. Every agent shown as an employee card: name, role, status, last run.
- Click any card. A chat panel opens.
- Type instruction. Agent executes. Response logged in real time.
- Useful for: "Scout Portal for new Devanahalli launches in the last 7 days", "Run feasibility on 3-acre site at Yelahanka PSF 4500".

### Mode 2 — Board Room
- You pitch an idea in a single text box.
- CEO decomposes it into department sub-tasks.
- Each department head responds concurrently:
  - Their read on the idea
  - What their team would need to execute
  - Risk flags from their lens (BD sees market risk, Finance sees unit economics, Engineering sees site constraints)
- Full transcript rendered as a structured panel: one column per department.
- Action items auto-extracted. Each action goes to the Task Board.
- Jinu approves or rejects each department's proposed actions.
- Transcript stored in DB. Searchable. Every board session is institutional memory.

### Mode 3 — Shareholder Review
- Triggered by Jinu or on a schedule (weekly/monthly).
- All 4 shareholders read the latest performance data (market briefs, project progress, financials).
- Each shareholder responds from their own mindset — cautious, growth-oriented, risk-focused, visionary.
- Conflicts between shareholder views surface as a structured debate.
- CEO synthesizes and presents a decision recommendation.
- Full transcript saved as institutional memory.

### Dashboard Panels

| Panel | What It Shows |
|-------|---------------|
| Org Chart | Live tree, registry-driven. Agent → dept, status, last run |
| Intel Board | Latest market brief per micro-market |
| Scout Feed | Real-time: latest N records from each scout source |
| Task Board | Kanban: Queued → Running → Done → Failed |
| Log Stream | Live tail of `crew.log` via SSE |
| Board Room | Pitch interface + transcript viewer |
| Shareholder Room | Shareholder review panel + debate transcript |
| Hiring Panel | Post a job, browse templates, hire from dashboard |
| Process Audit | Log analysis output, efficiency flags, open improvement items |
| DB Explorer | Key views rendered as sortable tables |

---

## Phase Roadmap

### Phase 1 — Scout Division Integration
**Goal:** All 4 untracked scouts live in the pipeline. Dedup working. Scraper Agent knows about all scouts.
**Effort:** 2–3 sessions
**Status:** ✅ COMPLETE — 2026-05-19

**Tasks:**
- [x] P1.1 — Review + test `scrapers/news_scout.py` standalone
- [x] P1.2 — Review + test `scrapers/portal_scout.py` standalone
- [x] P1.3 — Review + test `scrapers/developer_scout.py` standalone
- [x] P1.4 — Review + test `scrapers/rera_detail_scout.py` standalone
- [x] P1.5 — Review `scrapers/scout_memory.py` dedup logic
- [x] P1.6 — All 4 scouts wired as tools to `agents/scraper_agent.py`
- [x] P1.7 — Scout outputs wired into Stage 2 organizer (`utils/db_organizer.py`)
- [x] P1.8 — Schema: all scout output tables confirmed in `database/schema.sql`
- [x] P1.9 — Integration test: full 6-scout run for Yelahanka (31+ reports)
- [x] P1.10 — Scheduler wired (2AM UTC RERA refresh; Yelahanka daily cron pending T-189)
- [x] P1.11 — `agents/sentinel_agent.py` wired into docker-compose health check

**Definition of done:** ✅ Met. All 6 scouts run in pipeline. Devanahalli: 317 live RERA projects. Yelahanka/Hebbal: fallback data (live fix pending T-207).

---

### Phase 2 — Mission Control Dashboard
**Goal:** Working web interface. Org chart, task board, log stream, intel board. No board room mode yet.
**Effort:** 3–4 sessions
**Status:** ✅ COMPLETE — 2026-05-30

**Tasks:**
- [x] P2.14 — Expose dashboard port in `docker-compose.yml` (8050) — DONE T-067
- [x] P2.1 — Wire `dashboard/app.py` to PostgreSQL: agent_runs, views
- [x] P2.2 — `/api/agents` endpoint: live agent states + last run
- [x] P2.4 — `/api/intel` endpoint: latest report per micro-market
- [x] P2.6 — `/logs/stream` SSE endpoint
- [x] P2.7 — Org chart UI component — T-357
- [x] P2.8 — Agent status cards with status badges — T-357
- [x] P2.10 — Intel board panel (3 market cards)
- [x] P2.11 — Log stream panel
- [x] P2.13 — `/api/run` POST endpoint
- [x] P2.15 — Auto-refresh 30s
- [x] P2.3 — `/api/tasks` CRUD — built via Phase 3 (T-353/T-354)
- [ ] P2.5 — `/api/scout-feed` — deferred
- [x] P2.9 — Task board Kanban panel — built via Phase 3 (T-354)
- [ ] P2.12 — Scout feed panel — deferred

**Remark:** All Phase 2 DoD criteria met. Scout Feed (P2.5/P2.12) deferred — not required for DoD.

**Decision resolved:** Vanilla JS + HTMX approach. No framework, no build step.

**Definition of done:** Open `http://localhost:8050` — org chart with live agent states, 3 market intel cards, log stream, trigger a Yelahanka run from UI.

---

### Phase 3 — Board Room Mode
**Goal:** Jinu pitches any idea. All department heads respond. Transcript saved. Actions queued.
**Effort:** 2–3 sessions
**Status:** ✅ COMPLETE — 2026-05-30

**Tasks:**
- [x] P3.1 — Decision: CrewAI Hierarchical Process vs custom parallel orchestration — resolved (custom parallel chosen, see Open Decisions #1)
- [x] P3.2 — Create `crews/board_room.py`: full implementation with 5 dept heads, ThreadPoolExecutor, action extraction
- [x] P3.3 — CEO decomposes pitch into one sub-question per department
- [x] P3.4 — Department head agents run concurrently (BD, Finance, Engineering, Operations, Legal)
- [x] P3.5 — Each response structured: `{dept, read, execution_requirements, risk_flags}`
- [x] P3.6 — Action item extractor: Cerebras 8b + rule-based fallback → structured action list
- [x] P3.7 — DB: `board_sessions` table with individual dept-response columns + legal_response (Alembic 0006/0007)
- [x] P3.8 — Dashboard: Board Room panel — pitch text box, market selector, CONVENE BOARD button
- [x] P3.9 — Dashboard: Response panels — 5-column grid (BD/FINANCE/ENG/OPS/LEGAL), coloured headers
- [x] P3.10 — Dashboard: Action items panel — approve/reject per action creates queued task (POST /api/tasks)
- [x] P3.11 — `/api/board/pitch` POST endpoint
- [x] P3.12 — `/api/board/sessions` GET endpoint (session history)
- [x] P3.13 — GATE-10: end-to-end validation passed — session af4d2a61, 5 dept responses, 2 tasks approved

**Definition of done:** ✅ Met. Board Room panel in dashboard, pitch one idea, all **5 department heads (BD/Finance/Engineering/Ops/Legal)** respond concurrently, transcript saved to DB, two action items approved and visible on Task Board.

---

### Phase 4 — Agent Memory Layer
**Goal:** Every agent remembers what it has learned. Intel compounds. Conflicts are flagged.
**Effort:** 3–4 sessions
**Status:** ✅ COMPLETE — Memory Explorer panel live at /memory, conflict badge in nav, GATE-86 ✅ 2026-06-11

**Tasks:**
- [x] P4.1 — DB: `agent_memories` table with UNIQUE(agent_id, market, fact) constraint, row cap 500/agent+market — in Alembic baseline + T-297
- [x] P4.2 — Memory injection: on agent startup, load relevant memories into system prompt context — wired into pipeline
- [x] P4.3 — Memory write: after every run, agent writes new facts to `agent_memories` — T-297, T-298
- [x] P4.4 — Confidence system: new fact starts at 0.6, strengthens with each confirming source, decays after 30 days; weekly decay cron (Monday 03:00 UTC) — T-298
- [x] P4.5 — Auto-promote: 3+ scouts confirm same claim → confidence promoted to 0.9, flagged as high-confidence
- [ ] P4.6 — Conflict detection: two sources give contradictory values for same metric → flagged for Jinu review
- [ ] P4.7 — Weekly digest generator: top 5 new high-confidence facts per micro-market
- [x] P4.8 — Dashboard: Memory Explorer panel (filter by agent, market, confidence) — GATE-86 ✅ 2026-06-11
- [x] P4.9 — Dashboard: Conflict alert badge (new conflicts since last login) — GATE-86 ✅ 2026-06-11
- [ ] P4.10 — Obsidian sync (optional): write weekly digest to `D:\Brain\JINU JOSHI\03 LLS\01 Wiki\markets\`

**Definition of done:** Core engine complete (memory read/write/decay/confidence). Memory Explorer UI panel deferred to Phase 4.5.

---

### Phase 5 — Engineering Department
**Goal:** Architect and Renderer agents. Given land data, output typology + image brief.
**Effort:** 2–3 sessions
**Status:** ✅ COMPLETE — 2026-06-01 (GATE-12)

**Tasks:**
- [x] P5.1 — `agents/architect_agent.py`: tools for FSI calculation, floor plate typology, green coverage — T-361
- [x] P5.2 — Tool: `FSICalculator(land_area, zone, plot_coverage)` → buildable area, max floors — T-360
- [x] P5.3 — Tool: `TypologyRecommender(land_area, target_segment, psf)` → unit mix, carpet areas, amenity list — T-360
- [x] P5.4 — Tool: `GreenCoverageEstimator(land_area, built_coverage)` → landscape area, tree count — T-366, T-370
- [x] P5.5 — `agents/renderer_agent.py`: generates detailed image brief for Midjourney/DALL-E — T-368
- [x] P5.6 — Tool: `ImageBriefGenerator(project_type, typology, location, style)` → prompt string — T-368
- [x] P5.7 — Inputs from DB: `regulatory_zones` table seeded (9 rows) — T-359
- [x] P5.8 — Wire to BD dept: Analyst can request typology check before finalizing feasibility — T-369
- [x] P5.9 — Wire to Board Room: Engineering head auto-calls FSI calc on acreage mention — T-363
- [x] P5.10 — Dashboard: Engineering panel (show current site brief, typology output, image prompts) — T-371

**Definition of done:** ✅ Met. 3-acre Yelahanka R2 → FSI (buildable 326,700 / sellable 212,355 sqft, max 4 floors), typology (55% 2BHK, mid-range ₹6,500), green coverage (45%, 294 trees, BDA compliance). Renderer outputs Midjourney prompt with `--ar 16:9 --v 6`.

---

### Phase 6 — Finance Department
**Goal:** Full feasibility automation. Land + market data → go/no-go with IRR scenarios.
**Effort:** 2–3 sessions
**Status:** ✅ COMPLETE — Sprint 27 (T-373–T-379)

**LLS Standard Model (confirmed 2026-05-30):**
- Construction cost: ₹2,200/sqft hard cost
- Target IRR: ≥20% = GO | 12–20% = MARGINAL | <12% = NO-GO
- Financing: 60% equity / 40% debt
- Timeline: 18mo land→RERA + 36mo RERA→possession

**Tasks:**
- [x] P6.1 — LLS feasibility model inputs confirmed: ₹2,200/sqft, 20% IRR, 60:40, 54mo — T-373
- [x] P6.2 — `agents/finance_head_agent.py` — T-376
- [x] P6.3 — `utils/irr_model.py` (LandCostCalc + GDVEstimator + IRRModel + ScenarioComparator) — T-373
- [x] P6.4 — Tool: `FeasibilityAnalystTool` in analyst_agent.py — T-375
- [x] P6.5 — Wire to Board Room: Finance head auto-runs IRR when PSF + area in pitch — T-377
- [x] P6.6 — Dashboard: Finance panel — T-378
- [x] P6.7 — GATE-13: Phase 6 DoD validation — T-379

**Definition of done:** ✅ Met. Board Room pitch "5-acre Yelahanka ₹6,500 PSF JD model" → Finance Head returns calculated Base IRR 10.5% (NO-GO) / Bull 13.8% (MARGINAL) / Bear 7.2% (NO-GO) via LLS standard model — not LLM estimates. GATE-13 PASSED.

---

### Phase 7 — Discord Alerts
**Goal:** Every meaningful market event → Discord channel. Per-market channels. System health channel.
**Effort:** 1–2 sessions
**Status:** 🟡 MOSTLY COMPLETE — Sprint 28 (T-380–T-389 DONE); GATE-14 pending live verification

**Decision resolved (2026-05-30):** Discord with per-market channels and category structure.

**Discord Channel Structure:**
```
LLS Intel Server/
├── MARKET INTELLIGENCE/
│   ├── #rera-yelahanka       ← new RERA approvals
│   ├── #rera-devanahalli
│   ├── #rera-hebbal
│   └── #intel-reports        ← completed pipeline runs
├── COMPETITOR INTELLIGENCE/
│   └── #competitor-launches  ← new developer project detections
├── MARKET SIGNALS/
│   └── #price-movements      ← PSF delta >5%
└── SYSTEM/
    └── #re-os-health         ← scheduler errors, failures
```

**Tasks:**
- [x] P7.1 — `database/schema.sql` + Alembic 0009: alerts table — T-380
- [x] P7.2 — `utils/discord_notifier.py` — DiscordNotifier with 5 formatters — T-381
- [x] P7.3 — `settings.py` + `.env.example` Discord config keys — T-382
- [x] P7.4 — Wire RERA alerts to scheduler — T-384
- [x] P7.5 — Wire intel report alerts to market_intel_crew — T-385
- [x] P7.6 — Wire competitor alerts to developer_scout — T-386
- [x] P7.7 — Wire price movement alerts to portal_scout — T-387
- [x] P7.8 — Wire system health alerts to scheduler exception handler — T-388
- [x] P7.9 — Dashboard: Alerts panel — T-389
- [ ] P7.10 — GATE-14: RERA scrape → Discord message verified — pending live stack test

**Definition of done:** New RERA project scraped → Discord message appears in #rera-{market} channel within 30 seconds. GATE-14 passed.

---

## Task Backlog — Ready to Build Now

Any AI brain can pick a task, execute, log in `CHANGELOG.md`, mark done. No overlap if tasks are picked by ID.

| ID | Task | Phase | Agent | Blocked By |
|----|------|-------|-------|------------|
| T001 | Standalone test: `news_scout.py --market Yelahanka` | P1 | Cline/Claude | Nothing |
| T002 | Standalone test: `portal_scout.py --market Yelahanka` | P1 | Cline/Claude | Nothing |
| T003 | Standalone test: `developer_scout.py --market Yelahanka` | P1 | Cline/Claude | Nothing |
| T004 | Standalone test: `rera_detail_scout.py --market Yelahanka` | P1 | Cline/Claude | Nothing |
| T005 | Review `scout_memory.py` — confirm SHA ID scheme, dedup logic | P1 | Cline/Claude | Nothing |
| T006 | Wire all scouts as tools in `scraper_agent.py` | P1 | Claude | T001–T004 |
| T007 | Wire scout outputs into `db_organizer.py` | P1 | Claude | T005 |
| T008 | Schema audit: confirm scout output tables in `schema.sql` | P1 | Claude | T001–T004 |
| T009 | Full integration test: all scouts for Yelahanka | P1 | Cline | T006, T007 |
| T010 | Wire sentinel_agent.py into docker-compose healthcheck | P1 | Claude | Nothing |
| T011 | Wire dashboard to PostgreSQL (agent_runs, views) | P2 | Claude | Nothing |
| T012 | `/api/agents` endpoint in dashboard/app.py | P2 | Claude | T011 |
| T013 | `/api/tasks` endpoint | P2 | Claude | T011 |
| T014 | `/api/intel` endpoint | P2 | Claude | T011 |
| T015 | `/logs/stream` SSE endpoint | P2 | Claude | Nothing |
| T016 | Org chart UI component | P2 | Claude | T012 |
| T017 | Task board Kanban panel | P2 | Claude | T013 |
| T018 | Log stream panel | P2 | Claude | T015 |
| T019 | Expose port 8050 in docker-compose.yml | P2 | Claude | Nothing |

---

## Open Architecture Decisions

These need Jinu's input before the relevant phase can start.

**Decision 1 — Board Room orchestration (needed before P3.1)**
Two options:
- CrewAI Hierarchical Process: all department heads as a hierarchical crew. Cleaner, less control.
- Custom parallel orchestration: each dept head runs as a separate async call, responses aggregated in Python. More code, full control over transcript format.
Recommendation: custom parallel — board room needs a structured transcript, not a CrewAI conversation.

**Decision 2 — Dashboard frontend (needed before P2.7)**
- Vanilla JS/HTML (current approach): consistent with existing dashboard, no build step.
- Minimal React/Vue: better for real-time panels and component reuse.
Recommendation: Vanilla JS + HTMX for real-time panels. No build step, minimal JS, server-side rendered.

**Decision 3 — LLS Feasibility Model (needed before P6.1)**
Finance department needs standard assumptions:
- Construction cost PSF range (by segment)
- Target IRR threshold (project go/no-go)
- Standard financing mix (equity/debt)
- Timeline assumptions (design to launch, launch to possession)
Jinu to provide or confirm these from LLS standard model.

**Decision 4 — Alert delivery channel (needed before P7.2)**
- Telegram bot: instant push, free, needs bot setup
- Email: lower friction to set up, higher friction to read
- Dashboard-only: no external dependency, alerts only visible when logged in
Recommendation: Telegram bot. One-time setup, real-time push.

**Decision 5 — Shareholder personas (needed before P14.1)**
The 4 shareholder mindsets need names, backstories, investment theses, and communication styles defined by Jinu. Archetypes are sketched in Phase 14 — Jinu to confirm or rewrite them. These personas shape every strategic review and board-level decision.

**Decision 6 — PR/Social Media scope (needed before P11.1)**
Does the PR team just *draft* content for Jinu to post, or does it have publishing access (LinkedIn API, Instagram API)? Publishing requires API keys and brand approval workflows. Drafting-only is simpler and safer to start.
Recommendation: drafting-only for Phase 11. Publishing pipeline as Phase 11.5.

**Decision 7 — Legal tool data sources (needed before P12.3)**
Encumbrance checks and title searches require access to Kaveri Online (already partially scraped). Litigation scanning requires Indiankanoon.org or equivalent. Confirm which data sources are accessible/scrapable before building Legal tools.

**Decision 8 — Scout Division reporting line (needs clarification)**
Scouts were described as "under or collaborating with Engineering." Current architecture places them as Div C inside Engineering (tech-dependent for tools). Confirm this is correct or if scouts should be a standalone division reporting directly to CEO alongside Engineering.

---

## Execution Protocol

Two AI brains co-develop (Claude Code + Cline). Rules:
- Read before act. Log after act.
- Every file change logged in `CHANGELOG.md`
- Every completed task updates this VISION.md backlog (mark ✅)
- Every phase completion → `DEVLOG.md` entry
- Never start Phase N+1 until Phase N Definition of Done is met
- Open Decisions must be resolved before dependent tasks are picked

**Session start protocol:**
1. `python utils/status.py` — health snapshot
2. Read `VISION.md` backlog — pick first unblocked task
3. Check `CHANGELOG.md` — confirm no conflicts with other brain's recent work
4. Execute. Log. Mark done.

---

### Phase 8.5 — Intelligence Layer (Semantic Search + Sentiment)
**Goal:** Accumulated intel reports become queryable. News articles scored by FinBERT sentiment. Analyst uses past intelligence as context before forming market assessments.
**Effort:** 1–2 sessions
**Status:** ✅ COMPLETE — 2026-06-01 (GATE-15 PASSED)

**Tasks:**
- [x] P8.5.1 — Alembic 0010: sentiment_score + sentiment_label on news_articles — T-390
- [x] P8.5.2 — utils/sentiment.py — HF FinBERT API, graceful skip if key unset — T-392
- [x] P8.5.3 — utils/embedder.py — IntelEmbedder (ChromaDB + nomic-embed-text Ollama) — T-393
- [x] P8.5.4 — /api/intel/search endpoint — T-396
- [x] P8.5.5 — Dashboard Intel Search panel — T-397
- [x] P8.5.6 — IntelSearchTool in Analyst Agent — T-398
- [x] P8.5.7 — Scheduler: register embedding + sentiment cron jobs — T-399
- [x] P8.5.8 — GATE-15 DoD — T-400

**Definition of done:** Semantic query "Yelahanka PSF trend" returns excerpts from past reports. Sentiment job scores new articles nightly.

---

### Phase 8 — Agent Hiring & Onboarding System
**Goal:** The office is never frozen at a fixed headcount. New agents (employees) can be defined, hired, and onboarded without touching core code. Jinu writes a job description; the system creates the agent.
**Effort:** 2–3 sessions
**Status:** 🟡 IN PROGRESS — Sprint 31 (T-409–T-419). Registry scaffold, agent factory, DB table, built-in YAML agents, and dashboard hiring panel all pending.

**The concept:**
Every agent is defined by a spec file — their "employment contract." The system reads these specs at startup and instantiates agents dynamically. New hire = new spec file + registry entry. No hardcoded imports. No Dockerfile rebuild.

**Agent Spec Schema (`agents/registry/{role_id}.yaml`):**
```yaml
id: market_analyst_devanahalli
name: "Rohan Sharma"
role: "Market Analyst — Devanahalli"
department: bd
reports_to: bd_head
persona: |
  Senior analyst specialising in Devanahalli micro-market.
  Deep knowledge of airport corridor dynamics, SEZ zones, and
  Grade A developer activity north of BIAL.
llm_tier: analysis          # heavy / analysis / light — maps to llm_router.py
tools:
  - MarketSummary
  - CompetitorAnalysis
  - ReportGenerator
memory_context: devanahalli  # which memories to inject at startup
markets: [Devanahalli]
active: true
hired_on: 2026-05-15
```

**Tasks:**
- [ ] P8.1 — Create `agents/registry/` folder + schema definition (YAML spec format)
- [ ] P8.2 — `agents/agent_factory.py`: reads spec → instantiates CrewAI Agent dynamically
- [ ] P8.3 — DB: create `agent_registry` table (id, name, role, dept, spec JSON, hired_on, active)
- [ ] P8.4 — On container startup: scan `agents/registry/` → upsert into `agent_registry` table
- [ ] P8.5 — Crews load agents from registry, not hardcoded imports
- [ ] P8.6 — Dashboard: Hiring panel — "Post a job" form (role, dept, persona, tools, LLM tier)
- [ ] P8.7 — Dashboard: Org chart driven by `agent_registry` table, not static config
- [ ] P8.8 — On hire: YAML file written to `agents/registry/`, container hot-reload without rebuild
- [ ] P8.9 — On fire/deactivate: agent marked `active: false` in registry, removed from future runs, memory preserved
- [ ] P8.10 — Specialization library: curated list of role templates (Scout, Analyst, Architect, Negotiator, Legal Researcher, PR Agent) — hire by template, customize persona

**Role Templates (starter library):**
| Template | Department | Specialization |
|----------|------------|----------------|
| Market Analyst | Engineering / Scout | Micro-market deep dive |
| Scout — News | Engineering / Scout | Real estate news extraction |
| Scout — Portal | Engineering / Scout | Listing portal scraping |
| Scout — Regulatory | Engineering / Scout | RERA, BDA, BBMP tracking |
| Architect | Engineering / Creative | Typology, floor plate, amenities |
| Renderer | Engineering / Creative | Image briefs, visual concepts |
| Tool Builder | Engineering / Tech | Internal tool development |
| Feasibility Analyst | Finance | Land cost, GDV, IRR modelling |
| Legal Researcher | Legal | Encumbrance, title chain, litigation |
| PR Agent | PR & Brand | Press coverage, brand monitoring |
| Social Media Agent | PR & Brand | Content, posting calendar |
| Project Manager | Operations | Full project lifecycle ownership |
| Negotiator | Operations | Deal structuring, landowner profiling |
| Process Optimizer | Process Automation | Log analysis, efficiency improvements |
| Shareholder | Board | Strategic review, governance |

**Definition of done:** Hire a new "Hebbal Specialist" market analyst from the dashboard without touching any Python file. Restart agents container. New agent appears in org chart, responds to direct comms, participates in board room.

---

### Phase 9 — Tech Engineering Division B (Tool Builder + Optimizer)
**Goal:** A team inside Engineering that builds tools for everyone else and watches all processes for waste.
**Effort:** 2–3 sessions
**Status:** Not started. Foundational — other departments should exist first so the Optimizer has something to watch.

**The Optimizer / Thinker concept:**
One agent whose only job is watching the other agents. It reads run logs, measures token consumption per task, identifies redundant calls, spots patterns where agents ask for the same data multiple times. It then proposes tooling changes — new cache layers, smarter prompts, pre-computed results. This is the agent that makes the whole office cheaper and faster to run over time.

**Tasks:**
- [ ] P9.1 — `agents/tool_builder_agent.py`: given a task description, generates a Python tool class
- [ ] P9.2 — `agents/process_mapper_agent.py`: given a workflow description, produces a structured SOP
- [ ] P9.3 — `agents/optimizer_agent.py`: reads `agent_runs` + `logs/crew.log`, identifies waste patterns
- [ ] P9.4 — Tool: `TokenUsageAuditor(run_id)` → breakdown of tokens used per agent per task
- [ ] P9.5 — Tool: `RedundancyDetector(time_window)` → finds agents calling same data multiple times
- [ ] P9.6 — Tool: `CacheRecommender(usage_patterns)` → proposes which results should be cached
- [ ] P9.7 — Optimizer runs on a schedule (post every crew run) and writes findings to `outputs/optimizer/`
- [ ] P9.8 — Dashboard: Optimizer panel — token usage breakdown, open recommendations, accepted/rejected
- [ ] P9.9 — Optimizer can propose a code change → creates a task on the Task Board for a human (Jinu) to approve before it's applied

**Definition of done:** After a full scout run, Optimizer report shows token usage by agent, identifies one redundancy, and proposes one caching improvement. Recommendation visible in dashboard.

---

### Phase 10 — Operations Department (Project Managers + Dept Liaisons)
**Goal:** Coordination layer. Project Managers own full project lifecycles. Dept Liaisons bridge CEO to each department.
**Effort:** 2–3 sessions
**Status:** Not started. Becomes valuable once 3+ departments exist.

**Tasks:**
- [ ] P10.1 — `agents/operations_head_agent.py`: cross-department manager, routes CEO instructions
- [ ] P10.2 — `agents/project_manager_agent.py`: owns one project end-to-end
- [ ] P10.3 — DB: create `projects` table (project_id, name, status, pm_agent_id, created_at)
- [ ] P10.4 — DB: create `project_tasks` table (task_id, project_id, owner_agent_id, status, due_date)
- [ ] P10.5 — Tool: `ProjectStatusReport(project_id)` → milestone progress, blockers, next actions
- [ ] P10.6 — Tool: `TaskDelegator(task, dept, priority)` → routes task to correct dept head
- [ ] P10.7 — Board Room: Operations Head responds to all pitches with an execution timeline + resource plan
- [ ] P10.8 — Dashboard: Projects panel — active projects, milestones, owner, % complete
- [ ] P10.9 — Dashboard: per-project drill-down (all tasks, agent assignments, blockers)
- [ ] P10.10 — Project Manager auto-generates weekly status brief for CEO

**Definition of done:** Assign the Yelahanka market study as a "project" to a Project Manager. PM tracks all tasks (scout runs, analysis, feasibility) under one project view. Weekly status brief generated without manual input.

---

### Sprint 37 — HF Vision: Florence-2 Evaluation
**Goal:** Evaluate Florence-2-base on RTX 3050 4GB for site plan analysis and Kannada OCR.
**Effort:** 1 session
**Status:** ✅ COMPLETE (GATE-23 PASSED) — 2026-06-02

**Decision:** GO (with conditions). Florence-2-base runs within RTX 3050 4GB budget (2.05 GB VRAM, 3.55s max inference). OCR quality is FAIR — degrades on watermarks, Kannada text, and dense tables. Primary integration: Phase 12 as fallback OCR for scanned PDFs. PaddleOCR recommended as primary OCR engine for Production. Full report: `outputs/florence2_eval.md`.

### Phase 11 — PR & Brand Department
**Goal:** LLS brand intelligence and content generation. Monitors press, plans social, writes copy.
**Effort:** 2–3 sessions
**Status:** ✅ FULLY ACTIVE (2026-06-08) — PR Head + Content Writer + Social Media Agent + Brand Monitor + PR Studio panel all live via GATE-61 + GATE-67.

**Tasks:**
- [x] P11.1 — `agents/pr_head_agent.py`: brand narrative, positioning, press strategy — ✅ GATE-61 (2026-06-06)
- [x] P11.2 — `agents/social_media_agent.py`: content calendar, post drafts, engagement tracking — ✅ GATE-67 (2026-06-08)
- [x] P11.3 — `agents/content_writer_agent.py`: marketing copy, project brochures, investor comms — ✅ GATE-61 (2026-06-06)
- [x] P11.4 — Tool: `BrandMentionMonitor(brand, time_window)` → scrapes press + social for LLS mentions — ✅ GATE-67 (2026-06-08)
- [x] P11.5 — Tool: `CompetitorBrandTracker(developer_list)` → monitors competitor PR + launches — covered by `CompetitiveIntelEngine` (GATE-62)
- [x] P11.6 — Tool: `ContentCalendarGenerator(month, projects)` → drafts 30-day social calendar — ✅ GATE-67 (2026-06-08)
- [ ] P11.7 — Tool: `CopyWriter(brief, tone, channel)` → LinkedIn post / brochure copy / press release — covered by ContentWriterAgent
- [x] P11.8 — Integration with News Scout: developer scout flags competitor news → PR team responds — ✅ via CompetitiveIntelEngine + PR brief
- [x] P11.9 — Dashboard: PR panel — brand mentions, content calendar, pending copy reviews — ✅ GATE-67 (2026-06-08)
- [x] P11.10 — Weekly PR brief: top 5 brand mentions, one content recommendation, one competitor move — ✅ GATE-67 (2026-06-08)

**Definition of done:** PR Head produces a weekly brief with LLS brand mentions, one competitor PR move flagged, one LinkedIn post draft ready for Jinu to approve and post. ALL CRITERIA MET.

---

### Phase 12 — Legal Department (Real Tools)
**Goal:** Real estate legal intelligence. Title chains, encumbrance, RERA compliance, regulatory risk — all DB-grounded, not LLM guesses.
**Effort:** 1–2 sessions
**Status:** ✅ COMPLETE — Sprint 30 (T-401–T-408)

**Decision 7 resolved (2026-05-30):** Data sources = Kaveri Online (already scraped) + RERA Karnataka DB + regulatory_zones table. Indiankanoon deferred.

**Tasks:**
- [x] P12.1 — utils/rera_compliance_checker.py — T-401
- [x] P12.2 — utils/zone_risk_checker.py — T-402
- [x] P12.3 — RERAComplianceTool + ZoneRiskTool → Legal Head agent — T-403
- [x] P12.4 — agents/compliance_researcher_agent.py — T-404
- [x] P12.5 — Wire Legal Head auto-context to Board Room — T-405
- [x] P12.6 — Dashboard Legal panel — T-407
- [x] P12.7 — GATE-16 DoD — T-408

**Definition of done:** ✅ Met. Board Room pitch "5-acre Devanahalli site, R2 zone, Brigade developer" → Legal auto-context computes Brigade RERA record (1 Devanahalli project, CLEAN signal) + Devanahalli R2 zone risk (LOW, FAR=3.0, height=24m, coverage=60%) from DB. Dashboard Legal panel shows CLEAR/RISK/BLOCKED badge. GATE-16 passed.

---

---

### Phase 13 — Process Automation Team
**Goal:** The team that watches the whole office and makes everything run better. Reads all logs. Finds waste. Fixes processes. Documents what works.
**Effort:** 3–4 sessions (ongoing — this team never stops)
**Status:** Not started. Sentinel Agent is a precursor — it monitors DB health. This team goes deeper.

**Distinction from Phase 9 (Tech Engineering Optimizer):**
- Tech Engineering Optimizer: *builds tools* to reduce waste — code, caches, APIs
- Process Automation Team: *diagnoses and redesigns processes* — watches patterns, rewrites workflows, updates SOPs

**Tasks:**
- [ ] P13.1 — `agents/log_analyst_agent.py`: continuously reads `logs/crew.log` + `run_history.jsonl`
- [ ] P13.2 — `agents/efficiency_optimizer_agent.py`: identifies bottlenecks, slow agents, failed retries
- [ ] P13.3 — `agents/runbook_documenter_agent.py`: writes SOPs from observed successful run patterns
- [ ] P13.4 — Tool: `BottleneckFinder(time_window)` → which agent/task has highest avg duration
- [ ] P13.5 — Tool: `FailurePatternAnalyzer(time_window)` → which tasks fail most, common error signatures
- [ ] P13.6 — Tool: `ProcessDiagramGenerator(crew_name)` → auto-generates mermaid flowchart from run logs
- [ ] P13.7 — Tool: `ImprovementProposal(finding)` → structured proposal: current state, problem, fix, expected gain
- [ ] P13.8 — Process Automation runs after every 10 crew runs (or daily) and files a report
- [ ] P13.9 — Reports written to `outputs/process_audit/YYYY-MM-DD.md`
- [ ] P13.10 — Dashboard: Process Audit panel — latest report, open findings, accepted/rejected improvements
- [ ] P13.11 — Closed loop: accepted improvement → creates task on Task Board → assigned to Tech Engineering or relevant dept

**Definition of done:** After 10 crew runs, Process Automation team files a report with one confirmed bottleneck, one SOP document, and one improvement proposal that Jinu can approve. Accepted improvement creates a task in the Task Board.

---

### Phase 14 — Board of Shareholders
**Goal:** Four board members with distinct mindsets who review strategy, stress-test decisions, and hold the CEO accountable.
**Effort:** 2–3 sessions
**Status:** Not started. Needs all departments working first — shareholders review the full company picture.

**The four shareholder mindsets (to be named and detailed by Jinu):**
| Seat | Working title | Mindset |
|------|--------------|---------|
| 1 | The Cautious Investor | Risk-first. Asks: what can go wrong? What's the downside? Is the cash position safe? |
| 2 | The Growth Seeker | Opportunity-first. Asks: are we moving fast enough? Are we leaving margin on the table? |
| 3 | The Risk Hawk | Forensic. Asks: show me the data. What assumptions are we making? What's the confidence level? |
| 4 | The Visionary | Long-horizon. Asks: where does this put us in 5 years? What's the brand play? What's the legacy? |

**Tasks:**
- [ ] P14.1 — Jinu defines 4 shareholder personas (name, backstory, investment thesis, communication style)
- [ ] P14.2 — `agents/shareholder_agent.py`: parameterized — one class, 4 instances with different system prompts
- [ ] P14.3 — `crews/shareholder_review.py`: quarterly review crew — reads company performance data, each shareholder responds
- [ ] P14.4 — Tool: `PerformanceDigest(period)` → pulls company metrics: projects active, markets covered, feasibilities run, intel reports generated
- [ ] P14.5 — Tool: `DecisionAuditor(period)` → reviews which board room decisions were made, which were implemented
- [ ] P14.6 — Shareholder debate: when two shareholders disagree, structured back-and-forth (max 2 rounds) before CEO synthesizes
- [ ] P14.7 — DB: `shareholder_sessions` table — session, period, each shareholder response, debate transcript, CEO synthesis
- [ ] P14.8 — Dashboard: Shareholder Room panel — trigger review, view debate, read CEO synthesis
- [ ] P14.9 — On major decisions (land acquisition >₹5Cr, new market entry): auto-trigger shareholder review before Jinu approves
- [ ] P14.10 — Monthly shareholder letter: CEO auto-generates a one-page letter summarizing the period for the board

**Definition of done:** Trigger a quarterly review. All 4 shareholders read the performance digest and respond in character. One disagreement surfaced as a structured debate. CEO synthesis produced. Letter saved to `outputs/shareholder_letters/`.

---

## What This Becomes

At full build (all 14 phases), RE_OS is:

- A company that runs 24/7. Scouts scrape. Analysts synthesise. The office never sleeps.
- Every morning: new intel on 3 micro-markets waiting on the dashboard.
- Any land opportunity: feed it in, receive Legal risk + Engineering typology + Finance IRR in minutes.
- Competitor launches flagged before they appear in the press.
- Board meeting on any idea in 60 seconds. Shareholders review quarterly. CEO synthesises.
- PR team monitoring LLS brand mentions and drafting content. Legal team scanning titles.
- Process Automation team reading every log, tightening every process, filing weekly reports.
- The Optimizer watching token spend — making the whole office cheaper to run each week.
- Full audit trail of every decision, every run, every agent, every conflict resolved.
- Obsidian vault updated weekly. Monthly shareholder letter generated. Annual intelligence digest.

The competitive advantage is structural: LLS makes land and product decisions faster than any competitor, with more structured intelligence, backed by a Legal + Finance + Engineering review that a mid-size developer firm can't afford to run on every opportunity — but RE_OS runs it on all of them, automatically.

The headcount grows with the opportunity, not with the payroll. When a new micro-market opens up — Tumkur corridor, Sarjapur East, Hosur Road — Jinu posts one job, hires a specialist scout in 5 minutes, and that market is covered by morning.

This is not a tool. This is the institutional brain of LLS. Every decision it makes, every report it files, every conflict it surfaces — that is the competitive moat being built, one run at a time.

---

*This document is the master plan. It is updated by Claude and Cline after each session. Phase status, task completion, and open decisions are live. If this document is stale, the project is off track.*
