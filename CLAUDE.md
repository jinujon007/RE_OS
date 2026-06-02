# RE_OS — Claude Handout
**Last updated: 2026-06-02**
**Owner: Jinu — Employee, Land & Life Space (LLS)**
**Working directory: `D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS`**

---

## What This Is

Multi-agent real estate intelligence OS for LLS. Six AI scouts scrape RERA Karnataka + listing portals + developer sites + news. A 3-stage pipeline stores and analyzes data for North Bengaluru micro-markets. Jinu reads the output for land acquisition and project positioning decisions.

**Primary markets:** Yelahanka, Devanahalli, Hebbal
**Questions it answers:** Enter a micro-market at what PSF? Who are Grade A competitors? Which developers are distressed (JD/JV targets)? Absorption trends? Go/no-go on a market right now?

**Phase 1 (Scout Integration): ✅ COMPLETE**
**Phase 2 (Dashboard): ✅ COMPLETE — 2026-05-30**
**Phase 3 (Board Room): ✅ COMPLETE — 2026-05-30 — 5 dept heads (BD/Finance/Eng/Ops/Legal), GATE-10 PASSED**
**Phase 4 (Agent Memory): ✅ COMPLETE — read/write/decay/confidence, weekly decay cron, pipeline injection**
**Phase 5 (Engineering): ✅ COMPLETE — 2026-06-01 — FSI calc, Architect, Renderer, Green Coverage, GATE-12 PASSED**
**Phase 6 (Finance Dept): ✅ COMPLETE — IRR model, FeasibilityAnalystTool, Finance Head, Board Room auto-IRR, GATE-13 PASSED**
**Phase 7 (Discord Alerts): 🟡 MOSTLY COMPLETE — alerts coded (T-380–T-389 DONE); GATE-14 pending live Discord verification**
**Phase 8.5 (Intelligence Layer): ✅ COMPLETE — 2026-06-01 — ChromaDB semantic search + FinBERT sentiment + scheduler jobs, GATE-15 PASSED**
**Phase 8 (Agent Hiring): ✅ COMPLETE — Sprint 31 (GATE-17 PASSED 2026-06-01)**
**Phase 12 (Legal Dept — Real Tools): ✅ COMPLETE — 2026-06-01 — RERAComplianceChecker, ZoneRiskChecker, EncumbranceChecker, Legal Head auto-context, GATE-16 PASSED**

**HF Intelligence Upgrade Roadmap (Sprints 32–38 — 2026-06-01+):**
- Sprint 32: BGE-M3 embeddings + GPU Ollama validation + Qwen2.5-1.5B LLM tier + ST fallback ✅ COMPLETE (GATE-18 PASSED)
- Sprint 33: Semantic dedup (e5-small-v2) + cross-encoder reranker + BERTScore eval infrastructure ✅ COMPLETE (GATE-19 PASSED)
- Sprint 34: Legal PDF QA (roberta-base-squad2) + LegalDocQATool — DEFERRED (after v2 Phase 5)
- Sprint 35: finbert-tone directional sentiment + CI BERTScore gate — DEFERRED (after v2 Phase 5)
- Sprint 36: QLoRA Qwen2.5-3B RERA extractor fine-tune + Ollama deploy — DEFERRED (after v2 Phase 5)
- Sprint 37: Florence-2-base vision evaluation — DEFERRED (after v2 Phase 5)
- Sprint 38: DEFERRED — data publishing decision not made yet; dataset stays private

**Hardware: RTX 3050 4GB VRAM, CUDA 12.5 — Ollama GPU mode ACTIVE (2026-06-01)**
- Ollama runs on CUDA0: 1.0 GiB model weights, 24 MiB KV cache, 64 MiB compute graph, 1.1 GiB total GPU RAM
- `nvidia-smi` confirms GPU utilization >0% during inference, first token <2s for llama3.1:8b
- GPU allocated to ollama container via `deploy.resources.reservations.devices[0].capabilities[gpu]` in docker-compose.yml
- sentence-transformers uses same GPU when Ollama embedding unavailable (Sprint 32)

**Current state (2026-06-02):** Sprint 39 COMPLETE — GATE-25 PASSED. Next: T-710 (/ce-compound Sprint 39 learnings, Claude runs) then Sprint 60 v2 Phase 0 — complete 20-table schema (T-709, T-652–T-659, GATE-44). v1 Sprints 40–57 PAUSED. HF Sprints 34–38 DEFERRED.

**Dev workflow:** Claude Code (architect) + Kilo Code (sole implementer). Cline retired 2026-05-29. See `AGENTS.md` + `KILO_BRIEF.md`.

---

## Architecture

```
CEO Agent (Orchestrator)
    ├── Scraper Agent  → 6 scouts: RERA + RERA Detail + Portal + Developer + News + Kaveri
    ├── Analyst Agent  → queries DB, 6 market signals + FSI/IRR tools + IntelSearchTool
    ├── Sentinel Agent → system health monitor (docker-compose healthcheck)
    └── Parser Agent   → standalone only (not in main crew)

Board Room (separate crew):
    ├── BD Head, Finance Head, Engineering Head, Ops Head, Legal Head — concurrent
    ├── Architect Agent → FSI + Typology + Green Coverage (Engineering dept)
    ├── Finance Head Agent → FeasibilityAnalystTool + IRR (Finance dept)
    └── Renderer Agent → Midjourney/DALL-E prompt generation (Engineering / Creative)
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
HEAVY  (CEO):      Groq Scout 17b → Gemini 2.5 Flash → NVIDIA 405b → SambaNova 70b → OpenRouter 70b → Cloudflare → Ollama
ANALYSIS (Analyst): Cerebras 8b → Groq Scout → SambaNova → Ollama
LIGHT  (Scraper):  Cerebras 8b → Gemini Gemma 27b → NVIDIA 70b → SambaNova → Cloudflare → Ollama
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
├── VISION.md                     ← 14-phase roadmap (Phases 1–6 + 8.5 complete; 7 mostly done)
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
│   ├── architect_agent.py       ← FSI calc + Typology + GreenCoverage tools (Phase 5)
│   ├── renderer_agent.py        ← Midjourney/DALL-E prompt generator (Phase 5)
│   ├── finance_head_agent.py    ← FeasibilityAnalystTool + IRR (Phase 6)
│   └── parser_agent.py          ← standalone only
│
├── crews/
│   ├── market_intel_crew.py     ← 3-stage pipeline (6-task Stage 1 + Stage 2 + Stage 3)
│   └── board_room.py            ← 5-dept Board Room: BD/Finance/Eng/Ops/Legal concurrent
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
│   ├── db.py                    ← Shared SQLAlchemy engine singleton
│   ├── agent_memory.py          ← Phase 4: per-agent memory read/write/decay/confidence
│   ├── fsi_calculator.py        ← Phase 5: FSI + typology pure-Python calculator
│   ├── green_coverage.py        ← Phase 5: landscape area + tree count estimator
│   ├── irr_model.py             ← Phase 6: LandCost + GDV + IRR + ScenarioComparator
│   ├── feasibility.py           ← Phase 6: simple LandFeasibility dataclass (analyst tool)
│   ├── embedder.py              ← Phase 8.5: ChromaDB semantic search (IntelEmbedder)
│   ├── sentiment.py             ← Phase 8.5: FinBERT via HF Inference API
│   ├── discord_notifier.py      ← Phase 7: Discord webhook alerts (5 formatters)
│   ├── scheduler_helpers.py     ← safe_job wrapper for APScheduler error isolation
│   ├── status.py                ← Health dashboard
│   └── diagnose.py              ← Diagnostic utility
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
├── docs/solutions/              ← documented solutions to past problems (integration patterns, DB patterns, best practices); organized by category with YAML frontmatter (module, tags, problem_type)
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
curl http://localhost:8050/api/intel/cards
curl "http://localhost:8050/api/intel/search?q=Yelahanka+PSF+trend&market=yelahanka"
curl http://localhost:8050/api/alerts
curl http://localhost:8050/api/board/sessions

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

## Governance Gates (as of 2026-06-02)

| Gate | Name | Status |
|------|------|--------|
| GATE-2 | Dashboard Smoke Test — all 5 endpoints return live data | ✅ PASSED |
| GATE-4 | Intel Quality Baseline — ≥50 live RERA projects for Yelahanka/Hebbal | ✅ PASSED |
| GATE-7 | Test coverage ≥55% | ✅ PASSED |
| GATE-8 | API security + dashboard routes | ✅ PASSED |
| GATE-9 | CORS + Alembic startup | ✅ PASSED |
| GATE-10 | Phase 3 DoD — Board Room session → 2 tasks approved → Task Board | ✅ PASSED |
| GATE-11 | FSI calculator ≥12 tests | ✅ PASSED |
| GATE-12 | Phase 5 DoD — Architect + Renderer standalone verified | ✅ PASSED |
| GATE-13 | Phase 6 DoD — Finance Head returns real IRR from live data | ✅ PASSED |
| GATE-14 | Phase 7 DoD — RERA scrape → Discord alert within 30s | 🔴 PENDING (code done; live Discord verification outstanding) |
| GATE-15 | Phase 8.5 DoD — semantic query returns past report excerpts | ✅ PASSED |
| GATE-16 | Phase 12 DoD — Legal Head cites RERA data + zone risk from DB | ✅ PASSED (2026-06-01) |
| GATE-17 | Phase 8 DoD — hire agent from dashboard, appears in org chart | ✅ PASSED (2026-06-01) |
| GATE-18 | HF Foundation — BGE-M3 + Qwen2.5-1.5B + ST fallback | ✅ PASSED (2026-06-01) |
| GATE-19 | HF Search Quality — semantic dedup + reranker + BERTScore | ✅ PASSED (2026-06-01) |
| GATE-25 | Sprint 39 — IGR live + distressed dev alert + months_of_supply | ✅ PASSED (2026-06-02) |
| GATE-44 | v2 Phase 0 — complete 20-table schema live | 🔴 PENDING |
| GATE-45 | v2 Phase 1 — Unified Ingest Engine all plugins run | 🔴 PENDING |
| GATE-46 | v2 Phase 2a — all 5 intel modules return IntelPackage | 🔴 PENDING |
| GATE-47 | v2 Phase 2b — Opportunity Engine scores ≥5 opportunities | 🔴 PENDING |
| GATE-48 | v2 Phase 3 — /api/evaluate returns Board Room + Deal Memo + Investor Brief | 🔴 PENDING |
| GATE-49 | v2 Phase 4 — Telegram → /api/evaluate → compact verdict | 🔴 PENDING |
| GATE-50 | v2 Phase 5 — full end-to-end pipeline with feedback loop | 🔴 PENDING |

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

**16 tables** (Alembic migrations 0001–0010 applied):
`micro_markets`, `developers`, `rera_projects`, `project_snapshots`, `listings`,
`kaveri_registrations`, `guidance_values`, `regulatory_zones`, `overlay_constraints`,
`infrastructure_pipeline`, `market_snapshots`, `agent_runs`, `news_articles` (+ sentiment columns),
`board_sessions`, `agent_memories`, `tasks`, `alerts`

**Views:** `v_active_projects`, `v_market_inventory`, `v_developer_scorecard`, `v_market_brief`

**Current data (2026-06-01):** Devanahalli 317 live RERA + Yelahanka 165 + Hebbal 736 (post GATE-4). 35+ intel reports. 339 unit tests passing.

Developer grades: Grade A = known major brand OR ≥500 units. B = 100–499. C = <100.

---

## API Keys

| Key | Status | Quota |
|-----|--------|-------|
| `CEREBRAS_API_KEY` | ✅ Set | 1M tok/day, 8192 ctx cap |
| `GEMINI_API_KEY` | ✅ Set | 250k TPM Flash / 14.4k req/day Gemma |
| `GROQ_API_KEY` | ✅ Set | 30k TPM Scout, 1k req/day |
| `NVIDIA_API_KEY` | ✅ Set | 40 req/min |
| `OPENROUTER_API_KEY` | ✅ Set | 50-1000 req/day |
| `SAMBANOVA_API_KEY` | ✅ Set | 20M tok/day, 20 RPM (Tier 4) |
| `CLOUDFLARE_API_KEY` | ✅ Set | 10K neurons/day — last-resort (Tier 5) |
| `HF_API_KEY` | ✅ Set | FinBERT sentiment — always-warm free tier |
| `JINA_API_KEY` | Optional | 1M tok free bucket for embeddings |
| Ollama | ✅ Local | Unlimited (CPU-slow) — nomic-embed-text for ChromaDB |

**Rotate Groq:** `console.groq.com` → delete old → create new → update `.env` → `docker compose restart agents scheduler`

---

## Goal-Driven Execution

Every task spec written for Kilo Code must define verifiable success criteria — not just what to do, but how to confirm it's done.

**Transform imperatives into goals:**
- "Fix the Kaveri scraper" → "Write a test that hits the Kaveri endpoint and asserts ≥1 guidance value returned. Make it pass."
- "Add IGR transaction ingestion" → "Run the IGR scraper against Yelahanka; assert ≥10 rows in `kaveri_registrations`; pytest green."
- "Fix a bug" → "Write a test that reproduces it. Make it pass. The test must fail before the fix and pass after."

**Multi-step tasks get a plan with a verify step per stage:**
```
1. Add DB column → verify: alembic upgrade head succeeds
2. Wire scraper → verify: scraped records appear in table
3. Add alert → verify: alert fires within 30s of scrape
```

Strong success criteria let Kilo loop independently. Weak criteria ("make it work") require Jinu to eyeball every step.

**The gate is the success criterion at phase scale.** Individual task specs follow the same pattern.

---

## Skill Routing

- Bugs/errors → `/investigate`
- Architecture decisions → `/plan-eng-review`
- Code review → `/review`
- QA/testing → `/qa`

*Run `python utils/status.py` for instant health snapshot at session start.*
*Read `TASK_QUEUE.md` SPRINT BRIEF for current work priorities.*
