# RE_OS — Claude Handout
**Last updated: 2026-05-29**
**Owner: Jinu — Employee, Land & Life Space (LLS)**
**Working directory: `D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS`**

---

## What This Is

Multi-agent real estate intelligence OS for LLS. Six AI scouts scrape RERA Karnataka + listing portals + developer sites + news. A 3-stage pipeline stores and analyzes data for North Bengaluru micro-markets. Jinu reads the output for land acquisition and project positioning decisions.

**Primary markets:** Yelahanka, Devanahalli, Hebbal
**Questions it answers:** Enter a micro-market at what PSF? Who are Grade A competitors? Which developers are distressed (JD/JV targets)? Absorption trends? Go/no-go on a market right now?

**Phase 1 (Scout Integration): ✅ COMPLETE**
**Phase 2 (Dashboard): 🟡 IN PROGRESS — All 5 API endpoints live; all 5 GATE checks passed; UI panels (T-212/213/214/215/216) pending**
**Phase 3 (Board Room): 🟡 IN PROGRESS — board_room.py + DB + API live (T-218/T-260 done); dept-head agents (T-257/258/259) next**
**Phase 4 (Agent Memory): ✅ COMPLETE — read/write/decay implemented + injected into pipeline**

**Current sprint (Round 24):** All T-281 through T-341 complete. Next: GATE-4 verification (live RERA data for Yelahanka/Hebbal after deploy), then Phase 5 roadmap tasks.

**Dev workflow:** Claude Code (architect) + Kilo Code (sole implementer). Cline retired 2026-05-29. See `AGENTS.md` + `KILO_BRIEF.md`.

---

## Architecture

```
CEO Agent (Orchestrator)
    ├── Scraper Agent  → 6 scouts: RERA + RERA Detail + Portal + Developer + News + Kaveri
    ├── Analyst Agent  → queries DB, calculates 6 market signals, produces brief
    ├── Sentinel Agent → system health monitor (docker-compose healthcheck)
    ├── Parser Agent   → standalone only (not in main crew)
    └── Organizer Agent → DEPRECATED (replaced by db_organizer.py)
```

Main runtime: **3-stage pipeline** — Data Crew (6 scouts) → Python Organizer (db_organizer.py) → Intel Crew (Analyst + CEO).

---

## Infrastructure — Docker Compose (5 Containers)

| Container | Image | Port | Role |
|-----------|-------|------|------|
| `re_os_db` | postgis/postgis:15-3.3 | 5432 (internal) | Primary data store |
| `re_os_ollama` | ollama/ollama:latest | 11434 (internal) | Local LLM fallback |
| `re_os_redis` | redis:7-alpine | 6379 (internal) | Task queue |
| `re_os_agents` | custom (Dockerfile) | 8050 exposed | Runs crew + Flask dashboard |
| `re_os_scheduler` | custom (Dockerfile) | — | APScheduler: 2AM UTC RERA refresh |

`docker compose up -d` · `docker compose ps` · `docker compose down`

Only port 8050 is externally exposed — all others are internal (security hardening 2026-05-19).

---

## LLM Routing

```
HEAVY  (CEO):      Groq Scout 17b → Gemini 2.5 Flash → NVIDIA 405b → OpenRouter 70b → Ollama
ANALYSIS (Analyst): Cerebras 8b (1M tok/day) → Groq Scout → Ollama
LIGHT  (Scraper):  Cerebras 8b (1M tok/day) → Gemini Gemma 27b → NVIDIA 70b → Ollama
```

**Critical:** Cerebras 8,192 token context cap — fine for structured extraction + DB queries. NOT for CEO.
**Thread-safe:** LLM exclusion tracking uses threading.Lock — providers excluded on rate-limit, cleared on success.
**After rotating any key:** `docker compose restart agents scheduler` — no rebuild needed.
**Router:** `config/llm_router.py` · **Config:** `config/settings.py`

---

## Key File Map

```
RE_OS/
├── CLAUDE.md                     ← YOU ARE HERE
├── TASK_QUEUE.md                 ← ALL pending work + sprint priorities
├── VISION.md                     ← 14-phase roadmap (Phase 1 complete, Phase 2 in progress)
├── AGENTS.md                     ← Multi-brain coordination protocol
├── CHANGELOG.md                  ← File-level change log (audit trail)
├── DEVLOG.md                     ← Phase-by-phase build history
├── MODELS.md                     ← Free model reference + daily capacity
├── docker-compose.yml / Dockerfile / requirements.txt / .env
│
├── agents/
│   ├── ceo_agent.py             ← Orchestrator, max_iter=3, HEAVY LLM tier
│   ├── analyst_agent.py         ← 6-signal market analysis, ANALYSIS LLM tier
│   ├── scraper_agent.py         ← 8 tools: 6 scouts + 2 kaveri tools, LIGHT LLM tier
│   ├── sentinel_agent.py        ← System health monitor (docker healthcheck)
│   ├── parser_agent.py          ← standalone only
│   └── organizer_agent.py       ← DEPRECATED
│
├── crews/
│   ├── market_intel_crew.py     ← 3-stage pipeline (6-task Stage 1 + Stage 2 + Stage 3)
│   └── board_room.py            ← Phase 3 skeleton (not implemented)
│
├── scrapers/
│   ├── rera_karnataka.py        ← Playwright AJAX intercept + POST + hardcoded fallback
│   ├── rera_detail_scout.py     ← RERA project deep-dive (session fix pending T-207)
│   ├── portal_scout.py          ← 99acres/MagicBricks/Housing.com listings
│   ├── developer_scout.py       ← Brigade/Prestige/Sobha/Godrej etc. project pages
│   ├── news_scout.py            ← Google News + ET Realty (Gemini/Cerebras fallback)
│   ├── kaveri_karnataka.py      ← Guidance values + registrations
│   ├── listings_scraper.py      ← Legacy (99acres/MagicBricks, still used)
│   └── scout_memory.py          ← SHA-based dedup across all scouts
│
├── utils/
│   ├── validator.py             ← RERA record validation + [ESTIMATED] prefix
│   ├── db_organizer.py          ← Batch DB upsert, SAVEPOINT pattern, no LLM
│   ├── status.py                ← Health dashboard
│   ├── diagnose.py              ← Diagnostic utility
│   └── agent_memory.py          ← Phase 4 skeleton (T-220, not yet implemented)
│
├── config/
│   ├── llm_router.py            ← 3-tier routing, thread-safe exclusion tracking
│   ├── settings.py              ← All env vars, model names, market keywords, grade criteria
│   ├── run_logger.py            ← JSONL run history + markdown summary
│   ├── checkpointer.py          ← File-based stage resume (JSONDecodeError handled)
│   └── scheduler.py             ← APScheduler (2AM UTC RERA; Yelahanka 2:30AM IST pending T-189)
│
├── dashboard/
│   ├── app.py                   ← Flask server (port 8050), /api/health live
│   └── templates/index.html     ← Dashboard UI (wiring in progress, Phase D tasks)
│
├── database/
│   ├── schema.sql               ← 12 tables + 4 views + indexes
│   └── migrate_*.sql            ← Applied migrations (data_source, kaveri unique, views)
│
├── tests/                       ← pytest (validator, checkpointer, llm_router) + conftest
├── .github/workflows/ci.yml     ← py_compile + pytest + ruff CI
└── logs/ + outputs/             ← crew.log (573KB), run_history.jsonl, intel reports
```

---

## The 3-Stage Pipeline

```
STAGE 1 — Data Crew (scraper agent, LLM-assisted) — 6 tasks
  scrape_rera        → Playwright AJAX intercept → checkpoint saved
  scrape_rera_detail → RERA project deep-dive (session fix pending T-207)
  scrape_listings    → 99acres/MagicBricks
  scrape_portal      → portal_scout (7 portals)
  scrape_developer   → developer_scout (8 developer sites)
  scrape_news        → news_scout (Google News + ET Realty)

  Cache skip: ALL 6 checkpoints exist → skip Stage 1 entirely

STAGE 2 — Python Organizer (no LLM — pure Python)
  Load checkpoints → validate → batch upsert (SAVEPOINT pattern) → log to agent_runs

STAGE 3 — Intel Crew (LLM reasoning)
  analyze      → queries DB, produces 6-signal market brief
  ceo_synthesis → LLS-framed strategic read (PSF entry, JD/JV targets, go/no-go)
```

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
docker compose exec agents python scrapers/developer_scout.py --developer "Brigade,Prestige" --market Yelahanka
docker compose exec agents python scrapers/news_scout.py --market Yelahanka

# Dashboard
curl http://localhost:8050/api/health
curl http://localhost:8050/api/agents
curl http://localhost:8050/api/intel

# DB (or use MCP postgres tool — no docker exec needed)
docker compose exec postgres psql -U re_os_user -d re_os
# Key views: v_market_inventory, v_market_brief, v_developer_scorecard, v_active_projects

# Health check
docker compose exec agents python utils/status.py

# Tests
docker compose exec agents pytest tests/

# Rebuild after Dockerfile changes
docker compose build agents && docker compose up -d agents

# Live log
Get-Content logs/crew.log -Wait -Tail 50
```

---

## Governance Gates (as of 2026-05-20 — Round 9 Architecture Review)

| Gate | Name | Prerequisite | Unlocks |
|------|------|-------------|---------|
| GATE-1 | Pipeline Observability | T-245 DONE + stage events verified in agent_runs | T-249 (delete log monitor) + T-246 (market parallelism) |
| GATE-2 | Dashboard Smoke Test | T-165 DONE + all 5 endpoints return live data | Phase O dashboard UI build |
| GATE-3 | Auth Hardening | T-235 + T-250 DONE | DASHBOARD_API_KEY can be set in prod |
| GATE-4 | Intel Quality Baseline | T-179 + T-205 + T-206 + Kilo audit T-184 pass | Board Room bootstrap |
| GATE-5 | Log Monitor Eliminated | T-249 DONE | Phase S (scout parallelism) |

**API key rotation procedure (dual-key window, implemented by T-250):**
1. Set `DASHBOARD_API_KEY_PREV=$OLD_KEY` + `DASHBOARD_API_KEY=$NEW_KEY` → `docker compose restart agents`
2. Verify new key works: `curl -H "X-API-Key: $NEW_KEY" http://localhost:8050/api/run/yelahanka`
3. Remove `DASHBOARD_API_KEY_PREV` → `docker compose restart agents`

---

## Architecture Decisions Recorded (2026-05-20)

| Decision | Chosen | Rejected | Rationale |
|----------|--------|----------|-----------|
| Market parallelism | `subprocess.Popen` fan-out | ThreadPoolExecutor | Module-global `_excluded_providers` breaks across threads; processes isolate state for free |
| Scout parallelism | ThreadPoolExecutor (Phase S, deferred) | Immediate | Requires T-248 (per-market logs) + T-247 (fake context chains removed) first |
| State bus | Structured `agent_runs` events (T-245) | Log polling | Log parsing: non-deterministic, breaks on rotation, can't survive restarts |
| Auth scope | before_request exempts read-only paths | Gate all /api/* | Read-only endpoints blocked by API key is a UX defect |
| gunicorn workers | `--workers 1 --threads 8` | `--workers 2` | Multi-worker splits `_running` dict — pipeline status invisible across workers |

---

## Current State — Open Issues

### Bug 3 — schema.sql delay_months GENERATED COLUMN (Deferred)
`delay_months` generated column may fail on PostgreSQL on DB wipe + reinit.
**File:** `database/schema.sql` ~line 134. DB currently healthy — low urgency.
**Fix when hit:** move to view-level calculation or trigger.

### RERA Portal Playwright Timeout (Open — High)
Yelahanka and Hebbal return 8 hardcoded fallback projects (marked [ESTIMATED]).
Devanahalli: 317 live projects ✅. Root cause: RERA portal selector `No locality input found`.
**Fix:** T-207 (rera_detail_scout session state) may help. RERA portal selector fix needed separately.
**Impact:** At 8 fallback projects, Yelahanka PSF signals are unreliable — flag all Yelahanka output as [ESTIMATED] until >50 live RERA projects confirmed.

### Kaveri GV Portal Unreachable (Open — Medium)
`kaveri.karnataka.gov.in` guidance value portal consistently unreachable.
**Current state:** Falls back to 7 seeded guidance values (₹2,800–₹6,500 PSF for Yelahanka).
**Fix:** Try alternative endpoint or scrape via different path.

---

## Database Schema

**14 tables** (12 core + board_sessions + agent_memories — all in Alembic baseline migration 0001_initial.py):
`micro_markets`, `developers`, `rera_projects`, `project_snapshots`, `listings`,
`kaveri_registrations`, `guidance_values`, `regulatory_zones`, `overlay_constraints`,
`infrastructure_pipeline`, `market_snapshots`, `agent_runs`, `news_articles`,
`board_sessions`, `agent_memories`

**Views:** `v_active_projects`, `v_market_inventory`, `v_developer_scorecard`, `v_market_brief`

**Current data (2026-05-19):** Devanahalli 317 live RERA + Yelahanka/Hebbal 8 fallback each. 31+ intel reports for Yelahanka.

Developer grades: Grade A = known major brand OR ≥500 units. B = 100–499. C = <100.

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

## Skill Routing

- Bugs/errors → `/investigate`
- Architecture decisions → `/plan-eng-review`
- Code review → `/review`
- QA/testing → `/qa`

*Run `python utils/status.py` for instant health snapshot at session start.*
*Read `TASK_QUEUE.md` SPRINT BRIEF for current work priorities.*
