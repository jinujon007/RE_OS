# RE_OS — Claude Handout
**Last updated: 2026-05-13**
**Owner: Jinu — Employee, Land & Life Space (LLS)**
**Working directory: `D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS`**

---

## What This Is

RE_OS is a **multi-agent real estate intelligence operating system** built for LLS, a Bengaluru developer-builder. It runs a crew of five AI agents that scrape, parse, store, and analyze real estate market data for Karnataka micro-markets — producing actionable intelligence for land acquisition, project positioning, and competitive analysis.

This is not a demo. Jinu uses this to make real decisions about where to build.

---

## The Business Context

**Company:** Land & Life Space (LLS) — developer-builder focused on North Bengaluru.
**Decision-maker:** Jinu. He reads the output directly.
**Primary markets:** Yelahanka, Devanahalli, Hebbal (North Bengaluru corridor).
**Use cases:**
- Should LLS enter a given micro-market? At what price point? Who are the Grade A competitors?
- Which RERA projects have high unsold inventory (distressed developer signal)?
- What is the absorption rate trend in Yelahanka vs Devanahalli?
- Where is the pricing white space for a new LLS project?

Everything in this system exists to answer those questions.

---

## Architecture — The 5-Agent Crew

```
CEO Agent (Orchestrator)
    ├── Scraper Agent  → pulls raw data from RERA Karnataka + listing portals
    ├── Parser Agent   → normalizes messy HTML/JSON into clean typed records
    ├── Organizer Agent → upserts into PostgreSQL, deduplicates, logs runs
    └── Analyst Agent  → queries DB, calculates metrics, produces the brief
```

Runtime order is sequential in 3 stages: Data Crew (Scraper) → Python Organizer (validate + DB upsert) → Intel Crew (Analyst → CEO synthesis).
Parser + Organizer agents remain in repo for standalone use, but main runtime path is Stage 2 Python pipeline.
The CEO does not touch data directly — it orchestrates, reviews, and synthesizes.

---

## Infrastructure — Docker Compose (5 Containers)

| Container | Image | Port | Role |
|-----------|-------|------|------|
| `re_os_db` | postgis/postgis:15-3.3 | 5432 | Primary data store (PostGIS enabled) |
| `re_os_ollama` | ollama/ollama:latest | 11434 | Local LLM engine (llama3.1:8b pulled) |
| `re_os_redis` | redis:7-alpine | 6379 | Task queue (RQ) |
| `re_os_agents` | custom (Dockerfile) | — | Runs the crew (stays alive via `tail -f /dev/null`) |
| `re_os_scheduler` | custom (Dockerfile) | — | APScheduler: daily RERA refresh at 2AM IST |

**Start stack:** `docker compose up -d`
**Status check:** `docker compose ps`
**Run crew manually:** `docker compose exec agents python crews/market_intel_crew.py --market Yelahanka`

---

## LLM Routing Architecture

Three tiers, completely separate pools — no TPM conflicts.

```
HEAVY tier (CEO agent):
  PRIMARY:  Groq  meta-llama/llama-4-scout-17b-16e-instruct  (30,000 TPM — was 12k)
  BACKUP 1: Google AI Studio  gemini-2.5-flash               (250,000 TPM, 20 req/day)
  BACKUP 2: NVIDIA NIM  llama-3.1-405b-instruct              (40 req/min, no TPM cap)
  BACKUP 3: OpenRouter  llama-3.3-70b:free                   (50-1000 req/day)
  BACKUP 4: Ollama local

ANALYSIS tier (Analyst agent):
  PRIMARY:  Cerebras  llama3.1-8b                            (60-100k TPM, 1M tok/day)
  BACKUP 1: Groq  meta-llama/llama-4-scout-17b-16e-instruct  (shares CEO 30k bucket)
  BACKUP 2: Ollama local

LIGHT tier (Scraper + Parser + Organizer agents):
  PRIMARY:  Cerebras  llama3.1-8b                            (60-100k TPM, 1M tok/day)
  BACKUP 1: Google AI Studio  gemma-3-27b-it                 (15,000 TPM, 14,400 req/day)
  BACKUP 2: NVIDIA NIM  llama-3.3-70b                        (40 req/min)
  BACKUP 3: Ollama local
```

**Why this works:** Cerebras provides 1M tokens/day free — Light + Analysis never touch Groq budget.
CEO on Groq Scout (30k TPM) has 2.5× more headroom than old 70B (12k TPM). Google Gemini backup
for CEO provides 250k TPM if Groq runs out.

**Cerebras caveat:** 8,192 token context cap — fine for Light (structured extraction) and Analysis
(DB query JSON). NOT used for CEO (synthesis context can exceed 8k).

**Keys needed (all free, no credit card):**
- `CEREBRAS_API_KEY` — sign up at cloud.cerebras.ai (instant)
- `GEMINI_API_KEY` — sign up at aistudio.google.com → Get API Key (Google account only)
- `GROQ_API_KEY` — already set, new model name auto-applied via .env

**Router file:** `config/llm_router.py` — functions: `get_heavy_llm()`, `get_analysis_llm()`, `get_light_llm()`
**Settings file:** `config/settings.py` — all model names and provider config

---

## Key File Map

```
RE_OS/
├── CLAUDE.md                      ← YOU ARE HERE
├── MODELS.md                      ← Complete free model reference + daily capacity math
├── docker-compose.yml             ← 5-container stack definition
├── Dockerfile                     ← Python 3.11-slim + Chromium + all deps
├── requirements.txt               ← Pinned deps (crewai==0.80.0, no LangChain)
├── .env                           ← API keys (GROQ, NVIDIA, OPENROUTER set — never commit)
│
├── agents/
│   ├── ceo_agent.py              ← Orchestrator, allows delegation, max_iter=10
│   ├── analyst_agent.py          ← 3 tools: MarketSummary, CompetitorAnalysis, ReportGenerator
│   ├── scraper_agent.py          ← 3 tools: RERAScraperTool (saves checkpoint), ListingsScraper, GuidanceValue
│   ├── parser_agent.py           ← 2 tools: RERAParserTool, PriceParserTool (no longer in main crew)
│   └── organizer_agent.py        ← DEPRECATED in main crew — kept for standalone use only
│
├── crews/
│   └── market_intel_crew.py      ← v2: Data Crew → Python Organizer → Intel Crew (3-stage pipeline)
│
├── scrapers/
│   ├── rera_karnataka.py         ← RERA portal scraper (Playwright + POST fallback + hardcoded fallback)
│   └── listings_scraper.py       ← 99acres / MagicBricks scraper (with fallback sample data)
│
├── utils/
│   ├── validator.py              ← RERA record validation (format, non-empty, type checks)
│   └── db_organizer.py           ← Pure Python batch DB upsert — no LLM, 100× faster than v1
│
├── config/
│   ├── llm_router.py             ← LLM tier routing (get_heavy_llm / get_analysis_llm / get_light_llm)
│   ├── settings.py               ← All env vars, model names, market keyword maps, grade criteria
│   ├── run_logger.py             ← Writes logs/run_history.jsonl + logs/runs_summary.md
│   ├── checkpointer.py           ← File-based task checkpoints — failed runs resume from last stage
│   └── scheduler.py             ← APScheduler: 2AM RERA refresh, 6AM snapshots, 6h listings scan
│
├── database/
│   └── schema.sql                ← Full PostGIS schema (10 tables + views incl. v_market_brief + seed)
│
├── logs/
│   ├── crew.log                  ← Live loguru output from agent runs
│   ├── run_history.jsonl         ← Machine-readable run log (one JSON line per run)
│   └── runs_summary.md           ← Human-readable run history table (auto-generated)
│
└── outputs/
    └── yelahanka/                ← Generated intelligence reports land here
```

---

## Database Schema (PostgreSQL + PostGIS)

12 tables, all UUIDs as primary keys:

| Table | Purpose |
|-------|---------|
| `micro_markets` | Geographic anchors — 20 markets seeded (Yelahanka, Devanahalli, Hebbal are priority=1) |
| `developers` | Every RERA promoter — graded A/B/C by unit count + known brand list |
| `rera_projects` | Primary intel layer — all RERA-registered projects with unit inventory + pricing |
| `project_snapshots` | Quarterly absorption velocity tracking (delta from last snapshot) |
| `listings` | Live portal listings (99acres, MagicBricks, NoBroker) |
| `kaveri_registrations` | Actual registered transaction prices — ground truth for market values |
| `guidance_values` | Karnataka government circle rates by zone |
| `regulatory_zones` | DC Rules: FAR by road width, setbacks, height limits, parking norms |
| `overlay_constraints` | Lake buffers, rajakaluv, HT lines, airport funnel — these trump zoning |
| `infrastructure_pipeline` | Metro, roads, expressways — future value signals |
| `market_snapshots` | Aggregated daily/weekly/monthly snapshots per micro-market |
| `agent_runs` | Every agent job logged with status, counts, duration, error type |

**Useful views (pre-built):**
- `v_active_projects` — RERA projects joined with developer + market name
- `v_market_inventory` — per-market summary (units, absorption, psf range)
- `v_developer_scorecard` — developer rankings with delay metrics
- `v_market_brief` — ✅ NEW — single-query market brief (inventory + risk flags + developer grades)

---

## The 3-Stage Pipeline v2 (one market run)

```
STAGE 1 — Data Crew (scraper agent, LLM-assisted)
  Task 1: scrape_rera        → Playwright pulls RERA projects → saves checkpoint
  Task 2: scrape_listings    → 99acres/MagicBricks listings  → saves checkpoint

STAGE 2 — Python Organizer (no LLM — pure Python)
  Step 1: Load RERA checkpoint from disk
  Step 2: Validate records (validator.py — format/type/non-empty checks)
  Step 3: Batch upsert valid records (db_organizer.py — single transaction per record)
  Step 4: Log run stats to agent_runs table

STAGE 3 — Intel Crew (analyst + CEO, LLM reasoning)
  Task 3: analyze            → queries DB, produces market brief
  Task 4: ceo_synthesis      → strategic read + one action for LLS
```

Checkpointing: if today's RERA checkpoint exists, Stage 1 is skipped (RERA only scraped once/day).
If Stage 3 fails, Stage 1+2 are already done — restart resumes from Stage 3 at zero cost.

---

## Run Commands (Quick Reference)

```powershell
# Start / stop
docker compose up -d
docker compose down
docker compose ps

# Run crew
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
docker compose exec agents python crews/market_intel_crew.py --market Devanahalli
docker compose exec agents python crews/market_intel_crew.py --market Hebbal
docker compose exec agents python crews/market_intel_crew.py          # all markets

# Scrapers standalone (test without crew)
docker compose exec agents python scrapers/rera_karnataka.py --market Yelahanka
docker compose exec agents python scrapers/listings_scraper.py --market Yelahanka

# Database
docker compose exec postgres psql -U re_os_user -d re_os
# In psql: SELECT * FROM v_market_inventory;

# Ollama
docker compose exec ollama ollama list
docker compose exec ollama ollama pull llama3.1:8b

# Run history
docker compose exec agents python config/run_logger.py
tail -1 logs/run_history.jsonl | python -m json.tool

# Live log tail (PowerShell)
Get-Content logs/crew.log -Wait -Tail 50
```

---

## Current State (as of 2026-05-13) — WHAT IS BROKEN AND WHY

### Bug 1 — RERA Portal Scraper Returns Zero Results ✅ FIXED (2026-05-13 session 2)

**Fix applied:**
- `scrapers/rera_karnataka.py` — replaced `_search_by_locality()` + `_scrape_html_results()` with Playwright-based implementation
- Strategy: Playwright navigates the portal headlessly, intercepts the DataTables AJAX response (`/getAllProjects`), and captures raw JSON — bypasses JS rendering entirely
- Falls back to direct POST (no-JS API) if Playwright gets 0 results, then to hardcoded data as last resort
- `Dockerfile` updated: `playwright install chromium --with-deps` added after pip install (Playwright needs its own Chromium — system Chromium is Selenium-only)

**To activate:** Rebuild the agents container: `docker compose build agents && docker compose up -d agents`

**Caveat:** Portal may require a working locality input field to trigger the search. If the portal has changed its form layout, the DataTables interception still captures all rows loaded on page init — which may be all projects (paginated), not filtered. Check `logs/crew.log` for `[Playwright] Intercepted N rows`.

---

### Bug 2 — Groq Rate Limit + Wrong Analyst Model Name ✅ FIXED (2026-05-13)

**What was happening:**
- CEO on Groq 70B (12k TPM) burned through TPM, synthesis call (2,520 tokens) hit limit
- Analyst model name `llama-4-scout-instruct` → wrong → `NotFoundError`

**Fix applied (2026-05-13):**
- Cerebras added as primary for Light + Analysis: 1M tokens/day, 60-100k TPM, completely separate from Groq
- CEO switched to Groq `meta-llama/llama-4-scout-17b-16e-instruct`: 30,000 TPM (2.5× old limit)
- Corrected Analyst model name — now uses Cerebras anyway so Groq not called for Analyst
- Google AI Studio (Gemini) added as CEO fallback: 250k TPM, 20 req/day

**Keys needed to activate fix:** `CEREBRAS_API_KEY` and `GEMINI_API_KEY` (both free, no CC)

---

### Bug 3 — schema.sql GENERATED COLUMN Error (Deferred)

**Symptom:** `delay_months` generated column may fail on PostgreSQL if the expression is not considered immutable.

**File:** `database/schema.sql` around line 134

**Status:** DB container healthy. Bug surfaces only on DB wipe + reinit. Fix: move to view-level calculation or trigger.

---

## What Has Been Done (Chronological Build Log)

| Date | What Happened |
|------|--------------|
| Pre 2026-05-12 | Project designed. Docker Compose stack written. All 5 agents scaffolded. Schema designed. |
| 2026-05-12 AM | Stack booted for first time. All 5 containers healthy. Ollama pulled llama3.1:8b. |
| 2026-05-12 AM | LLM router tested — all 4 providers confirmed active (groq/nvidia/openrouter/ollama). |
| 2026-05-12 ~13:00 | First crew run. Failed: Groq rate limit (light tier on Groq burned TPM). |
| 2026-05-12 ~18:14 | Light tier moved to Ollama-only. RERA scraper returns 0 real results, falls back to 8 sample projects. |
| 2026-05-12 ~18:22 | Run with sample data: crew advances further, still hits Groq 12k TPM on CEO. |
| 2026-05-12 ~19:32 | NVIDIA NIM tried for light tier. Analyst fails: `llama-4-scout-instruct` model not found. |
| 2026-05-13 session 1 | LLM routing overhauled. Cerebras added (1M tok/day). Groq Scout correct name. Gemini fallback. |
| 2026-05-13 session 2 | RERA scraper rewritten with Playwright (AJAX interception). Dockerfile updated for playwright install. CEREBRAS + GEMINI keys still missing from .env — crew will fall back to Groq for Analysis/Light until added. |
| 2026-05-13 session 3 | **Major reliability overhaul (Crew v2).** Schema fixed (delay_months uses date arithmetic, duration_seconds converted to regular column). Pipeline split: Data Crew (scraper only) → Python Organizer (pure Python batch upsert, zero LLM) → Intel Crew (analyst + CEO). New: `utils/validator.py` (RERA record validation), `config/checkpointer.py` (file-based task resume), `utils/db_organizer.py` (batch DB writes). Scraper tools auto-save checkpoints — failed runs resume from last checkpoint. `v_market_brief` view added to schema. VS Code extensions expanded (+8 extensions). |
| 2026-05-13 session 4 | **Phase 7 — Kaveri registrations scraper.** New `scrapers/kaveri_karnataka.py` (KaveriScraper: guidance values + registrations, Playwright primary + POST fallback + hardcoded 2024 GV rates). `GuidanceValueTool` upgraded from stub. `KaveriRegistrationTool` added to scraper agent. `DBOrganizer.run_kaveri()` added. Stage 1 gets `scrape_kaveri` task. Stage 2 upserts GV + registrations. `MarketSummaryTool` now returns `kaveri_transactions` (avg_actual_psf, guidance_gap_pct) + `guidance_values`. CEO now has actual vs asking price gap. |

---

## Immediate Next Steps (Prioritized)

### P0 — Get API keys for Cerebras + Gemini ✅ DONE (2026-05-13)
Both keys confirmed in `.env`: `CEREBRAS_API_KEY` + `GEMINI_API_KEY` set.
LLM routing now fully active: Cerebras handles Light + Analysis, Groq Scout handles CEO.

**Next action — rerun pipeline and validate fresh output:**
```powershell
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
```
Watch `logs/crew.log` — should see `[Playwright] Intercepted N rows` + `[Router] LIGHT tier → Cerebras` + `[Checkpoint] Saved Yelahanka/rera_scraped`.

### P1 — Fix RERA Scraper (live data) ✅ DONE (2026-05-13)
Playwright AJAX interception implemented in `scrapers/rera_karnataka.py`. Dockerfile updated.
Container already running with updated code in mounted volume; rebuild only needed if Dockerfile/requirements changed.

### P2 — Fix schema bugs ✅ DONE (2026-05-13 session 3)
`delay_months` uses immutable date arithmetic. `duration_seconds` is regular column. `v_market_brief` view added.

### P3 — Implement Kaveri registrations scraper
The `kaveri_registrations` table is seeded but the scraper is a placeholder (`GuidanceValueTool` returns a stub). This is the most valuable data source — actual transaction prices.

### P4 — Build report output to file
Currently the CEO final output prints to terminal. Wire it to save as `.txt` or `.html` in `outputs/{market}/intel_report_{timestamp}.txt` so Jinu can read it without being in the terminal.

### P5 — Database seeding with real data
Once RERA scraper works, run a full seed run to populate the DB with real project data. Until then, the Analyst agent queries return empty results.

---

## API Keys Status (as of 2026-05-13)

| Key | Status | Free Quota | Sign-up |
|-----|--------|-----------|---------|
| `CEREBRAS_API_KEY` | ✅ Set | 1M tokens/day, 60-100k TPM | cloud.cerebras.ai (instant, no CC) |
| `GEMINI_API_KEY` | ✅ Set | 250k TPM (Flash), 14,400 req/day (Gemma) | aistudio.google.com (Google account) |
| `GROQ_API_KEY` | ✅ Set | 30k TPM (Scout), 1k req/day | console.groq.com |
| `NVIDIA_API_KEY` | ✅ Set | 40 req/min | build.nvidia.com |
| `OPENROUTER_API_KEY` | ✅ Set | 50-1000 req/day | openrouter.ai |
| Ollama | ✅ Local | Unlimited (slow) | — |

**Rotate Groq key:** `console.groq.com` → API Keys → delete old, create new → update `.env` → `docker compose restart agents scheduler`

**After rotating any key:** `docker compose restart agents scheduler` — no rebuild needed.

---

## Developer Grade Logic (for Competitor Analysis)

Defined in `config/settings.py` and applied in `agents/organizer_agent.py`:

- **Grade A:** Known major brand (Prestige, Brigade, Sobha, Puravankara, Godrej, Mahindra, Lodha, DLF, Shapoorji, Embassy, Mantri, Salarpuria, Total Environment, Adarsh) OR ≥500 units launched
- **Grade B:** 100–499 units
- **Grade C:** <100 units OR unknown developer

LLS positioning: typically Grade B+/approaching A. Relevant for knowing who you're competing against.

---

## Known RERA Fallback Data (Yelahanka)

The scraper returns these 8 hardcoded projects when the portal is unreachable:
1. Shriram Suhaana — 648 units, 80% absorbed
2. Prestige Lakeside Habitat — 3,426 units, 85% absorbed
3. Brigade Orchards — 2,400 units (integrated township), 75% absorbed
4. Sobha Dream Gardens — 1,152 units, 85% absorbed
5. (+ 4 more Grade A/B projects)

These are real publicly-known projects but figures may be stale. Mark as `source: fallback_sample` in analysis.

---

## VS Code Workflow

**Recommended extensions** (see `.vscode/extensions.json`): Python, Pylance, Black Formatter, Docker, GitLens, SQLTools + PostgreSQL driver, REST Client.

**Tasks panel** (Ctrl+Shift+P → "Run Task"):
- `🚀 Run: Yelahanka` — single market run
- `🐳 Docker: Start Stack` / `Stop Stack`
- `🦙 Ollama: Pull llama3.1:8b`
- `🗄️ DB: Open psql Shell`
- `📋 Tail Live Log`

**Debug panel** (F5 or Run & Debug):
- `🚀 Run: Yelahanka` — runs crew with debugger attached
- `🔍 Test RERA Scraper` — test scraper standalone

**Integrated terminal tips:**
- Always be in `D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS` when running docker commands
- Use PowerShell (default in `.vscode/settings.json`)
- `Get-Content logs/crew.log -Wait -Tail 50` for live log tailing

---

## How to Brief a New Claude Session in VS Code

If you open Claude Code in VS Code terminal from this directory, it will read this file automatically. Tell it:

> "Read CLAUDE.md fully, then help me with [specific task]."

The session should understand: the full architecture, the bugs, the run history, the business context, and the next steps — without you having to explain any of it.

For complex multi-file changes, start with: "What's the current state of RE_OS?" — the answer should come straight from this document.

---

## Multi-Brain Co-Development

RE_OS is built by Claude Code + Cline. Any brain can plan and execute — no role restrictions. The rule is: read before you act, log after you act. See `AGENTS.md` for the full protocol.

**Session start read order:** `CLAUDE.md` → `DEVLOG.md` → `CHANGELOG.md` → `.cline_logs/CHANGELOG.md` → `AGENTS.md` backlog → proceed.

**Scraping tool upgrade path** (AGENTS.md backlog has full list):
- P1 adds: `httpx`, `price-parser`, `dateparser`
- P2 adds: `curl_cffi`, `cloudscraper` (when portals start blocking)

---

*This file is the single source of truth for project state. Update it after every significant session.*

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
