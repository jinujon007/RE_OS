# RE_OS — Claude Handout
**Last updated: 2026-05-14**
**Owner: Jinu — Employee, Land & Life Space (LLS)**
**Working directory: `D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS`**

---

## What This Is

Multi-agent real estate intelligence OS for LLS. Five AI agents scrape, parse, store, and analyze RERA Karnataka + listing portal data for North Bengaluru micro-markets. Jinu reads the output directly for land acquisition and project positioning decisions.

**Primary markets:** Yelahanka, Devanahalli, Hebbal
**Questions it answers:** Enter a micro-market at what PSF? Who are Grade A competitors? Which developers are distressed? Absorption trends?

---

## Architecture

```
CEO Agent (Orchestrator)
    ├── Scraper Agent  → RERA Karnataka + listings + Kaveri registrations
    ├── Parser Agent   → normalizes HTML/JSON (standalone only — not in main crew)
    ├── Organizer Agent → DEPRECATED in main crew — standalone only
    └── Analyst Agent  → queries DB, calculates metrics, produces brief
```

Main runtime: **3-stage pipeline** — Data Crew → Python Organizer → Intel Crew.
CEO orchestrates, never touches data. Parser + Organizer kept for standalone use.

---

## Infrastructure — Docker Compose (5 Containers)

| Container | Image | Port | Role |
|-----------|-------|------|------|
| `re_os_db` | postgis/postgis:15-3.3 | 5432 | Primary data store (PostGIS) |
| `re_os_ollama` | ollama/ollama:latest | 11434 | Local LLM fallback |
| `re_os_redis` | redis:7-alpine | 6379 | Task queue (RQ) |
| `re_os_agents` | custom (Dockerfile) | — | Runs the crew |
| `re_os_scheduler` | custom (Dockerfile) | — | APScheduler: 2AM RERA refresh |

`docker compose up -d` · `docker compose ps` · `docker compose down`

---

## LLM Routing

```
HEAVY  (CEO):      Groq Scout 17b (30k TPM) → Gemini 2.5 Flash → NVIDIA 405b → OpenRouter 70b → Ollama
ANALYSIS (Analyst): Cerebras 8b (1M tok/day) → Groq Scout → Ollama
LIGHT  (Scraper):  Cerebras 8b (1M tok/day) → Gemini Gemma 27b → NVIDIA 70b → Ollama
```

**Critical:** Cerebras 8,192 token context cap — fine for structured extraction + DB queries. NOT for CEO.
Cerebras and Groq are completely separate budgets — no TPM conflicts between tiers.
**After rotating any key:** `docker compose restart agents scheduler` — no rebuild needed.
**Router:** `config/llm_router.py` · **Config:** `config/settings.py`

---

## Key File Map

```
RE_OS/
├── CLAUDE.md                     ← YOU ARE HERE
├── MODELS.md                     ← Free model reference + daily capacity math
├── AGENTS.md                     ← Task backlog + multi-brain protocol (read this for open tasks)
├── DEVLOG.md                     ← Phase-by-phase build history (read last 2 phases only)
├── CHANGELOG.md                  ← File-level change log (Claude + Cline edits)
├── .cline_logs/CHANGELOG.md      ← Cline session log
├── docker-compose.yml / Dockerfile / requirements.txt / .env
│
├── agents/
│   ├── ceo_agent.py             ← Orchestrator, allows_delegation=True, max_iter=10
│   ├── analyst_agent.py         ← MarketSummary, CompetitorAnalysis, ReportGenerator tools
│   ├── scraper_agent.py         ← RERAScraperTool, ListingsScraper, GuidanceValue, KaveriReg
│   ├── parser_agent.py          ← standalone only
│   └── organizer_agent.py       ← DEPRECATED in main crew
│
├── crews/market_intel_crew.py   ← v2: 3-stage pipeline
├── scrapers/
│   ├── rera_karnataka.py        ← Playwright AJAX intercept + POST fallback + hardcoded fallback
│   ├── listings_scraper.py      ← 99acres/MagicBricks (sample data fallback)
│   └── kaveri_karnataka.py      ← Guidance values + registrations scraper
│
├── utils/
│   ├── validator.py             ← RERA record validation
│   ├── db_organizer.py          ← Batch DB upsert, no LLM
│   └── status.py                ← Health dashboard
│
├── config/
│   ├── llm_router.py            ← get_heavy_llm / get_analysis_llm / get_light_llm
│   ├── settings.py              ← All env vars, model names, market keywords, grade criteria
│   ├── run_logger.py            ← JSONL run log + runs_summary.md
│   ├── checkpointer.py          ← File-based task resume (failed runs restart from last stage)
│   └── scheduler.py            ← APScheduler
│
├── database/schema.sql          ← 12 tables + views (v_market_brief, v_market_inventory etc.)
└── logs/ + outputs/             ← crew.log, run_history.jsonl, intel reports per market
```

---

## The 3-Stage Pipeline

```
STAGE 1 — Data Crew (scraper agent, LLM-assisted)
  scrape_rera     → Playwright AJAX intercept → checkpoint saved
  scrape_listings → 99acres/MagicBricks       → checkpoint saved
  scrape_kaveri   → Guidance values + regs    → checkpoint saved

STAGE 2 — Python Organizer (no LLM — pure Python)
  Load checkpoints → validate → batch upsert (db_organizer.py) → log to agent_runs

STAGE 3 — Intel Crew (LLM reasoning)
  analyze      → queries DB, produces market brief
  ceo_synthesis → strategic read + one action for LLS
```

Checkpointing: today's checkpoint exists → Stage 1 skipped. Stage 3 fails → restart from Stage 3 only.

---

## Run Commands

```powershell
# Stack
docker compose up -d
docker compose ps
docker compose down

# Run crew
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
docker compose exec agents python crews/market_intel_crew.py --market Devanahalli
docker compose exec agents python crews/market_intel_crew.py --market Hebbal
docker compose exec agents python crews/market_intel_crew.py   # all markets

# Scrapers standalone
docker compose exec agents python scrapers/rera_karnataka.py --market Yelahanka

# DB (or use MCP postgres tool — no docker exec needed)
docker compose exec postgres psql -U re_os_user -d re_os
# Key views: v_market_inventory, v_market_brief, v_developer_scorecard, v_active_projects

# Health check
docker compose exec agents python utils/status.py

# Rebuild after Dockerfile changes
docker compose build agents && docker compose up -d agents

# Live log
Get-Content logs/crew.log -Wait -Tail 50
```

```powershell
# ── AIDER (multi-file editor with automatic Gemini key rotation) ───────────
# Always use the router — it picks the first Gemini key with available quota,
# falls back to Groq Scout if all 4 keys are exhausted.

# Standard launch (from RE_OS root):
python scripts/aider_router.py
# Shorthand:
.\scripts\aider.ps1

# Force a specific model (overrides router default):
python scripts/aider_router.py --model gemini/gemini-2.5-flash
python scripts/aider_router.py --model groq/meta-llama/llama-4-scout-17b-16e-instruct

# Key slots live in .env — paste new keys into next empty slot:
# GEMINI_API_KEY_1=...  (primary)
# GEMINI_API_KEY_2=...  (backup 1)
# GEMINI_API_KEY_3=...  (backup 2)
# GEMINI_API_KEY_4=...  (backup 3)
# GROQ_API_KEY=...      (final fallback — already set)

# Inside Aider session:
# /add <file>    — load file for editing
# /ask <q>       — ask without editing
# /undo          — undo last commit
# /diff          — show pending changes
# /exit          — quit
# Full guide → TOOL_GUIDE.md § 5
```

---

## Current State — Open Issues

### Bug 3 — schema.sql GENERATED COLUMN (Deferred)
`delay_months` generated column may fail on PostgreSQL on DB wipe + reinit.
**File:** `database/schema.sql` ~line 134. DB container currently healthy — low urgency.
**Fix when hit:** move to view-level calculation or trigger.

### Bugs 1 + 2: ✅ Fixed 2026-05-13. Details in DEVLOG.md Phases 3–4.

---

## Database Schema

12 tables (all UUID PKs): `micro_markets`, `developers`, `rera_projects`, `project_snapshots`, `listings`, `kaveri_registrations`, `guidance_values`, `regulatory_zones`, `overlay_constraints`, `infrastructure_pipeline`, `market_snapshots`, `agent_runs`

Pre-built views: `v_active_projects`, `v_market_inventory`, `v_developer_scorecard`, `v_market_brief`

Developer grades (defined in `config/settings.py`): Grade A = known major brand OR ≥500 units. B = 100–499. C = <100.

---

## API Keys

| Key | Status | Quota |
|-----|--------|-------|
| `CEREBRAS_API_KEY` | ✅ Set | 1M tok/day, 60-100k TPM |
| `GEMINI_API_KEY` | ✅ Set | 250k TPM (Flash) / 14.4k req/day (Gemma) |
| `GROQ_API_KEY` | ✅ Set | 30k TPM Scout, 1k req/day |
| `NVIDIA_API_KEY` | ✅ Set | 40 req/min |
| `OPENROUTER_API_KEY` | ✅ Set | 50-1000 req/day |
| Ollama | ✅ Local | Unlimited (slow) |

**Rotate Groq:** `console.groq.com` → delete old → create new → update `.env` → `docker compose restart agents scheduler`

---

## Multi-Brain Protocol

Three brains co-develop: **Claude Code** (architect + reviewer), **Cline** (primary implementer), **Kilo Code** (secondary implementer — T0 read-only tasks, free tier).

**Cline and Kilo Code can run simultaneously** without conflicts. Each only picks tasks labeled with its own brain name in TASK_QUEUE.md. Each marks a task IN-PROGRESS before starting — this prevents double-claiming.

**Cline model switching:** Cline has two mode slots — **Plan mode** (reasoning) and **Act mode** (tool execution) — set independently. Every task spec has a `Plan mode:` and `Act mode:` line. Before running any task, Cline tells Jinu which models to set. Jinu switches manually, confirms, then Cline runs. Providers: Ollama (local free), OpenRouter (free models), NinRouter (NVIDIA + Codex). T3/T4 tasks use Codex in Plan mode.

**The loop:**
- Jinu tells Cline: *"go to next task"* → Cline reads TASK_QUEUE.md → picks first `READY / Brain=Cline` row → marks IN-PROGRESS → reads Plan + Act model from spec → tells Jinu which models to set → waits for confirmation → executes → logs → marks DONE → reports next task's models
- Jinu tells Kilo Code: *"go to next task"* → same loop, only for `Brain=Kilo Code` rows
- After 5–7 tasks: Jinu tells Claude: *"review the project development"* → Claude reads changes, fixes drift, adds tasks
- Neither Cline nor Kilo Code ever makes architecture decisions. They execute what Claude has specced.

**Key files for brains:**
- `AGENTS.md` — protocol, roles, model routing, how-to (full detail)
- `TASK_QUEUE.md` — the atomic task list (INDEX + DETAIL SPECS + model routing at top)
- `VISION.md` — the 14-phase office vision (context, never deviate from this)
- `TOOL_GUIDE.md` — tool setup and Cline model routing guide

**Session start read order:** this file → `DEVLOG.md` (last 2 phases only) → `CHANGELOG.md` → `TASK_QUEUE.md` (find next task)

---

## Skill Routing

- Bugs/errors → `/investigate`
- Architecture → `/plan-eng-review`
- Code review → `/review`
- QA/testing → `/qa`

*Run `python utils/status.py` for instant health snapshot at session start.*
