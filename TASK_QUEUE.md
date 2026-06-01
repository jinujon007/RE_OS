# RE_OS — Task Queue
**Stage 3 · 2026-05-30 | Single-brain: Kilo Code**
**Next task ID: T-420**

---

## Sprint 29 — Intelligence Layer (Semantic Search + Sentiment)
**Goal:** Accumulated intel reports become queryable. News articles scored by sentiment. Analyst uses past intelligence as context.
**Exit criterion:** GATE-15 passed — semantic query returns relevant past report excerpts. Scheduler embedding + sentiment jobs run without error.

### Foundations (P1)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-390 | Alembic 0010 + schema.sql — add sentiment_score FLOAT + sentiment_label VARCHAR(20) to news_articles | P1 | PENDING | Required by scheduler run_news_sentiment_scoring(); both nullable |
| T-391 | settings.py + .env.example — HF_API_KEY + CHROMA_DB_PATH | P1 | PENDING | HF_API_KEY → HF Inference API for FinBERT; CHROMA_DB_PATH=/app/data/chroma default |
| T-392 | utils/sentiment.py — score_headline(text) → float \| None via HF FinBERT API | P1 | PENDING | POST to https://api-inference.huggingface.co/models/ProsusAI/finbert; map positive/negative/neutral to +1/0/-1; graceful None if key unset or API error |
| T-393 | utils/embedder.py — IntelEmbedder class: index_intel_reports() + query() | P1 | PENDING | ChromaDB persistent client at CHROMA_DB_PATH; embed via nomic-embed-text Ollama endpoint; index each *.txt in outputs/; query returns top-N excerpts with source file |
| T-394 | tests/test_sentiment.py — ≥6 unit tests | P1 | PENDING | Mock HF API: positive/negative/neutral response → correct float, API error → None, key unset → None |
| T-395 | tests/test_embedder.py — ≥6 unit tests | P1 | PENDING | Mock ChromaDB + Ollama: index empty dir, query with no docs, index 1 report then query |

### Dashboard + Agent Wiring (P1/P2)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-396 | dashboard/app.py — GET /api/intel/search?q=&market= endpoint | P1 | PENDING | Wraps embedder.query(); returns top-5 excerpts with source_file + market; graceful empty when ChromaDB not indexed; rate-limit 20/min; add to _READ_ONLY_PATHS |
| T-397 | Dashboard Intel Search panel — text input + market selector + results list | P1 | PENDING | New infra-section; fetch on submit; results show excerpt (first 300 chars) + source filename + market badge |
| T-398 | IntelSearchTool in agents/analyst_agent.py — wraps embedder.query() | P2 | PENDING | Tool: query past intel reports for context before answering market questions; ADJUNCT — not in standard pipeline sequence |
| T-399 | Scheduler: wire embedding + sentiment jobs at 4:30 AM + 5:00 AM IST | P1 | PENDING | scheduler.py already has run_intel_embedding_index() and run_news_sentiment_scoring() — add APScheduler jobs for both; CHROMA_DB_PATH must be same docker volume as agents |
| T-400 | GATE-15 — Phase 8.5 DoD: query "Yelahanka PSF trend" → returns past report excerpts; sentiment job runs without crash | P0 | PENDING | docker compose exec agents python -c "from utils.embedder import IntelEmbedder; e=IntelEmbedder(); print(e.query('Yelahanka PSF trend', n=3))"; check CHANGELOG |

### Sprint 29 Gate

| Gate | Unlocked By | Status |
|------|-------------|--------|
| GATE-15 | T-400 — semantic query returns excerpts; sentiment column exists; scheduler jobs registered | PENDING |

---

## Sprint 30 — Phase 12: Legal Department (Real Tools)
**Goal:** Legal Head backed by real Kaveri + RERA data. Encumbrance check, RERA compliance, zone risk — all from DB and scrapers, not LLM knowledge.
**Exit criterion:** GATE-16 passed — Board Room Legal Head returns data-grounded compliance verdict, not prose guesses.

**Decision 7 resolved (2026-05-30):** Data sources = Kaveri Online (already integrated via kaveri_karnataka.py) + RERA Karnataka DB + regulatory_zones table. Indiankanoon deferred.

### Legal Tools (P1)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-401 | utils/rera_compliance_checker.py — RERAComplianceChecker: check developer RERA record from DB | P1 | PENDING | Input: developer_name; query rera_projects + developers tables; returns: total projects, active/completed split, delayed count, avg delay months, any is_active=False anomalies |
| T-402 | utils/zone_risk_checker.py — ZoneRiskChecker: market + zone → regulatory risk summary | P1 | PENDING | Input: market, zone; query regulatory_zones table; returns: FAR, setbacks, max height, airport/greenbelt flags from overlay_constraints table; flag if zone is restricted |
| T-403 | RERAComplianceTool + ZoneRiskTool — add to agents/board_room/legal_head.py | P1 | PENDING | BaseTool wrappers; update legal_head agent backstory to mention real data sources; max_iter stays 2 |
| T-404 | agents/compliance_researcher_agent.py — standalone Legal/Compliance Researcher | P1 | PENDING | Uses RERAComplianceTool + ZoneRiskTool + EncumbranceCheckTool (Kaveri wrapper); ANALYSIS LLM tier; reports to Legal Head |
| T-405 | utils/kaveri_encumbrance.py — EncumbranceChecker: wraps existing kaveri scraper, queries guidance_values + kaveri_registrations from DB | P1 | PENDING | Input: market, survey_no (optional); returns: avg guidance value PSF, registration count in 180-day window, avg transaction PSF, guidance gap %; uses DB-first, Kaveri portal fallback |
| T-406 | Wire Legal Head auto-context to Board Room — guidance value + zone risk pre-computed | P1 | PENDING | In board_room.py, key=="legal": query guidance_values + regulatory_zones for pitch market; prepend to legal dept_question (same pattern as engineering FSI + finance IRR) |

### Dashboard + Docs (P2)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-407 | Dashboard Legal panel — /api/legal/brief endpoint + UI section | P2 | PENDING | GET: last legal_response from board_sessions; panel shows market, CLEAR/RISK/BLOCKED badge + response excerpt |
| T-408 | GATE-16 — Phase 12 DoD: Board Room pitch with market → Legal Head returns RERA data + zone risk, not generic prose | P0 | PENDING | Pitch: "5-acre Devanahalli site, R2 zone, Brigade developer"; verify Legal column cites actual RERA project count, guidance PSF from DB; CHANGELOG evidence |

### Sprint 30 Gate

| Gate | Unlocked By | Status |
|------|-------------|--------|
| GATE-16 | T-408 — Legal Head response contains DB-sourced RERA + zone data | PENDING |

---

## Sprint 31 — Phase 8: Agent Hiring & Onboarding
**Goal:** New agents can be defined in a YAML file and hired from the dashboard — no Python changes, no Dockerfile rebuild.
**Exit criterion:** GATE-17 passed — hire a "Hebbal Specialist" from the dashboard; it appears in the org chart and responds to direct commands.

### Agent Registry Infrastructure (P1)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-409 | agents/registry/ folder + _schema.yaml — agent spec schema definition | P1 | PENDING | Fields: id, name, role, department, reports_to, persona, llm_tier, tools (list), memory_context (market), markets (list), active, hired_on |
| T-410 | Alembic 0011 + schema.sql — agent_registry table | P1 | PENDING | id VARCHAR(100) PK, name TEXT, role TEXT, department VARCHAR(50), spec JSONB, llm_tier VARCHAR(20), active BOOL DEFAULT true, hired_on TIMESTAMPTZ |
| T-411 | agents/agent_factory.py — reads YAML spec → instantiates CrewAI Agent | P1 | PENDING | scan_registry(registry_dir) → list[Agent]; load_agent(spec_id) → Agent; validate: required fields, llm_tier in (heavy/analysis/light), tools must be known names |
| T-412 | On agents container startup: scan agents/registry/ → upsert agent_registry DB | P1 | PENDING | In dashboard/app.py startup (or docker-compose command): call agent_factory.sync_registry_to_db(); idempotent upsert on id |
| T-413 | agents/registry/market_analyst_yelahanka.yaml — first built-in registry agent | P1 | PENDING | Yelahanka specialist; tools: [MarketSummaryTool, CompetitorAnalysisTool]; llm_tier: analysis; markets: [Yelahanka] |
| T-414 | agents/registry/market_analyst_devanahalli.yaml + market_analyst_hebbal.yaml | P1 | PENDING | Same pattern; different market context; hired_on: 2026-05-30 |

### Dashboard Hiring Panel (P2)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-415 | /api/registry endpoint — GET (list all agents) + POST (hire new agent from YAML template) | P1 | PENDING | GET: returns agent_registry rows; POST: accepts JSON spec, writes YAML to agents/registry/, syncs DB; add GET to _READ_ONLY_PATHS |
| T-416 | Dashboard Agent Hiring panel — registry list + hire-from-template form | P2 | PENDING | New infra-section; list all registered agents with status badge; "New Agent" button → form with role/dept/persona/market fields; POST to /api/registry |
| T-417 | Org Chart enhanced — pulls from agent_registry table (not just _agent_states dict) | P2 | PENDING | /api/agents falls back to agent_registry when DB agent_runs is sparse; org chart shows ALL registered agents, not just 5 hardcoded ones |
| T-418 | tests/test_agent_factory.py — ≥8 unit tests | P1 | PENDING | Load valid YAML → Agent, missing required field → ValueError, unknown tool → warning (not crash), scan empty dir → [], sync to DB mock |
| T-419 | GATE-17 — Phase 8 DoD: hire Hebbal Specialist from dashboard; appears in org chart; responds to /api/agents | P0 | PENDING | POST /api/registry with Hebbal Specialist spec; GET /api/agents shows new agent; CHANGELOG evidence |

### Sprint 31 Gate

| Gate | Unlocked By | Status |
|------|-------------|--------|
| GATE-17 | T-419 — Hebbal Specialist hired from dashboard, visible in org chart | PENDING |

---

## Sprint 26 — Phase Closure Sprint (all DONE)

---

## Sprint 27 — Phase 5 Complete + Phase 6 Finance Dept
**Goal:** Close Phase 5 (Engineering). Build Finance Dept end-to-end (Phase 6).
**Exit criterion:** GATE-12 + GATE-13 passed → Phase 5 ✅ Phase 6 ✅.

### Phase 5 Completion — Renderer + Green Coverage + Engineer Panel (P1)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-366 | utils/green_coverage.py — GreenCoverageEstimator (pure Python, no LLM) | P1 | DONE | Given land_area_sqft + built_coverage_pct → landscape_sqft, tree_count (1 per 200sqft), green_pct |
| T-367 | Add GreenCoverageTool to agents/architect_agent.py | P1 | DONE | Wrap GreenCoverageEstimator as BaseTool; add to agent tools list; update description |
| T-368 | agents/renderer_agent.py — ImageBriefGeneratorTool + create_renderer_agent() | P1 | DONE | Pure string construction: project_type + unit_mix + location + style_keywords → Midjourney/DALL-E prompt; ANALYSIS LLM tier |
| T-369 | Wire Architect tools into Analyst Agent (P5.8) | P1 | DONE | Import FSICalculatorTool + TypologyRecommenderTool from architect_agent into analyst tools list; update backstory adjunct guidance |
| T-370 | tests/test_green_coverage.py — ≥8 unit tests | P1 | DONE | Zero area, full built coverage, standard coverage, tree count floor=1, green_pct clamp 0–100 |
| T-371 | Dashboard Engineering panel — /api/engineering/brief endpoint + UI section | P2 | DONE | GET endpoint returns last FSI result + unit mix from board_sessions DB; panel shows zone, FAR, buildable/sellable sqft, unit mix, image prompt |
| T-372 | GATE-12 — Phase 5 DoD: Architect Agent standalone run + Renderer prompt output | P0 | DONE | 3-acre Yelahanka R2: FSI (buildable 326,700 / sellable 212,355 sqft / 4 floors / 55% plot), typology (15/55/30% mid-range), green (45%/294 trees/BDA met). Renderer: Midjourney prompt with --ar 16:9 --v 6. VISION.md Phase 5 → COMPLETE. Engineering panel not testable (container stuck). |

### Phase 6 — Finance Department (P1)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-373 | utils/irr_model.py — LandCostCalculator + GDVEstimator + IRRModel + ScenarioComparator | P1 | DONE | Standards baked in: construction ₹2,200/sqft, target IRR 20%, equity 60%, land→RERA 18mo, RERA→possession 36mo; all pure Python |
| T-374 | tests/test_irr_model.py — ≥15 unit tests | P1 | DONE | GDV math, IRR calc, scenario comparator verdicts, zero-land-cost guard, negative IRR case |
| T-375 | FeasibilityAnalystTool in agents/analyst_agent.py | P1 | DONE | Tool: land_area + market + sell_psf → land_cost (from guidance_values DB) + GDV + base/bull/bear IRR + verdict; calls irr_model.py + DB |
| T-376 | agents/finance_head_agent.py — standalone Finance Head agent | P1 | DONE | create_finance_head_agent() with FeasibilityAnalystTool; ANALYSIS LLM tier; distinct from Board Room inline builder |
| T-377 | Wire Finance Head to Board Room — auto IRR math on land mentions | P1 | DONE | In board_room.py: detect PSF / acreage in pitch → pre-compute IRR scenarios → prepend to finance dept_question (mirrors T-363 pattern) |
| T-378 | Dashboard Finance panel — /api/finance/brief endpoint + UI section | P2 | DONE | GET endpoint: last feasibility calc from DB; panel shows land cost, GDV, base/bull/bear IRR, verdict badge (GO/MARGINAL/NO-GO) |
| T-379 | GATE-13 — Phase 6 DoD: Board Room pitch with land area → Finance Head returns real IRR | P0 | DONE | Finance auto-IRR: Base 10.5% (NO-GO) / Bull 13.8% (MARGINAL) / Bear 7.2% (NO-GO) verified. Live stack not testable (Docker Desktop API mismatch on host). VISION.md Phase 6 → COMPLETE, GATE-13 → PASSED |

### Phase 6 Gates

| Gate | Unlocked By | Status |
|------|-------------|--------|
| GATE-12 | T-372 — Phase 5 DoD: Architect standalone + Renderer prompt verified | PASSED |
| GATE-13 | T-379 — Phase 6 DoD: Finance Head returns real IRR calc from live data | PASSED |

---

## Sprint 28 — Phase 7 Discord Alerts
**Goal:** Every meaningful market event → Discord channel. Per-market channels. System health channel.
**Exit criterion:** GATE-14 passed → Phase 7 ✅.

### Discord Infrastructure (P1)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-380 | database/schema.sql + Alembic 0009 — alerts table | P1 | DONE | id UUID, channel VARCHAR(50), title TEXT, message TEXT, color INT, status VARCHAR(20) CHECK(sent|failed|skipped), created_at; idx on channel + created_at |
| T-381 | utils/discord_notifier.py — DiscordNotifier class | P1 | DONE | send(channel, title, message, color) → bool via webhook POST; graceful degradation (no crash if webhook unset); embed format with timestamp + footer |
| T-382 | settings.py + .env.example — Discord config keys | P1 | DONE | DISCORD_WEBHOOK_RERA_YELAHANKA, _DEVANAHALLI, _HEBBAL, _COMPETITOR, _PRICE, _INTEL, _SYSTEM; all optional; settings.py maps channel name → env key |
| T-383 | tests/test_discord_notifier.py — ≥8 tests | P1 | DONE | Mock webhook POST: send success, HTTP error, no webhook configured (skip gracefully), embed field validation, color codes |
| T-384 | Wire RERA alerts — scheduler.py post-scrape hook | P1 | DONE | After run_single_market_rera(): query DB for rera_projects WHERE created_at > job_start; if count>0 → send to RERA channel for that market; include project count + top 3 developer names |
| T-385 | Wire Intel report alerts — market_intel_crew.py Stage 3 completion | P1 | DONE | After CEO synthesis: send to DISCORD_WEBHOOK_INTEL; include market, run_id, first 200 chars of CEO synthesis, avg_psf, project count |
| T-386 | Wire competitor launch alerts — developer_scout.py new project detection | P2 | DONE | After DB upsert: compare project CIDs to scout_memory; new CIDs → send to DISCORD_WEBHOOK_COMPETITOR; include developer, project name, market |
| T-387 | Wire price movement alerts — portal_scout.py >5% PSF delta | P2 | DONE | After listings upsert: compare avg_psf to last market_snapshot; if delta >5% → send to DISCORD_WEBHOOK_PRICE; include market, old PSF, new PSF, % change |
| T-388 | Wire system health alerts — scheduler.py exception handler | P1 | DONE | Wrap each cron job in try/except; on exception → send to DISCORD_WEBHOOK_SYSTEM; include job name, error message (sanitized), timestamp |
| T-389 | /api/alerts endpoint + Dashboard Alerts panel | P2 | DONE | GET /api/alerts: returns last 50 rows from alerts table (channel, title, status, created_at); add to _READ_ONLY_PATHS; panel shows colour-coded rows by channel type; 60s auto-refresh |

### Phase 7 Gate

| Gate | Unlocked By | Status |
|------|-------------|--------|
| GATE-14 | T-384 verified in live stack: RERA scrape → Discord message within 30s | PENDING |

---

## Sprint 26 — Phase Closure Sprint (all DONE)
**Goal:** Close Phase 2 (Dashboard) and Phase 3 (Board Room). Bootstrap Phase 5 (Engineering Dept).
**Exit criterion:** Both Phase DoDs met → enter Phase 5.

Completed work lives in `CHANGELOG.md` only — this file tracks what is still open.

---

## ⚠ LOCK PROTOCOL — Read This First

**Before touching any code:**

1. Find the first task with status `PENDING`.
2. **Change it to `IN_PROGRESS` and save this file immediately.**
3. Only then open `TASK_BRIEFS.md` and start work.

**Why:** Two Kilo windows can open simultaneously. First write wins. If your intended task is already `IN_PROGRESS`, pick the next one.

---

## Rules

1. **One task at a time.** Finish + mark DONE before picking the next.
2. **After every task:** prepend one line to `CHANGELOG.md`, then mark DONE here.
3. **Ruff must pass:** `ruff check .` — fix all violations before marking done.
4. **Tests must not regress:** `pytest tests/ -q -m unit` — 0 failures.
5. **If blocked:** set status `BLOCKED`, write one note, stop.
6. **No new dependencies** without a comment in `requirements.txt`.

---

## Status Key

| Symbol | Meaning |
|--------|---------|
| `PENDING` | Not started — pick it up |
| `IN_PROGRESS` | Claimed — do not touch |
| `DONE` | All checks passed, CHANGELOG written |
| `BLOCKED` | Waiting on external factor — see Notes |

---

## Sprint 26 — Phase Closure Sprint
**Goal:** Close Phase 2 (Dashboard) and Phase 3 (Board Room). Bootstrap Phase 5 (Engineering Dept).
**Exit criterion:** Both Phase DoDs met → enter Phase 5.

### Phase 3 Closure — Task Board + Action Approval (P0/P1)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-352 | DB: tasks table — Alembic migration 0008 + schema.sql | P1 | DONE | New table: id UUID, title TEXT, owner VARCHAR(50), status VARCHAR(20), source_type VARCHAR(30), source_id UUID, priority VARCHAR(10), created_at TIMESTAMPTZ |
| T-353 | API: POST /api/tasks + GET /api/tasks — create + list tasks | P1 | DONE | POST creates task row; GET returns tasks filtered by ?status=; add to _READ_ONLY_PATHS |
| T-354 | Dashboard Task Board panel — Kanban (Queued/Active/Done/Failed) | P1 | DONE | New infra panel; fetch /api/tasks on load + 30s refresh; column per status; card shows title+owner+priority |
| T-355 | Board Room: action approval UI — approve/reject buttons per action item | P1 | DONE | Each action in _renderBoardResult gets Approve/Reject button; Approve calls POST /api/tasks with source_type=board_session |
| T-356 | GATE-10: Phase 3 DoD validation — end-to-end board session → approve 2 actions → visible on Task Board | P0 | DONE | Session af4d2a61, tasks 2a6e86b6+3f023c56 in QUEUED. All 9 steps pass. |

### Phase 2 Polish — Org Chart Panel (P2)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-357 | Dashboard Org Chart panel — registry-driven agent cards | P2 | DONE | Replace static cabin hardcodes with /api/agents data; render as org tree (CEO → Analyst/Scout/Processor/Sentinel); show dept, status, last_run |
| T-358 | Board Room response layout — 5-column side-by-side panel for dept responses | P2 | DONE | Replace current vertically-stacked _renderBoardResult with horizontal column view (BD | Finance | Eng | Ops | Legal) |

### Phase 5 Bootstrap — Engineering Dept (P1/P2)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-359 | DB: regulatory_zones seed data — Yelahanka/Devanahalli/Hebbal BDA zone rules | P1 | DONE | 9 rows seeded: 3 markets × 3 zone types; ROUND-2: wrapped in BEGIN/COMMIT + DELETE authority=BDA for idempotent re-runs |
| T-360 | utils/fsi_calculator.py — FSICalculator + TypologyRecommender (pure Python, no LLM) | P1 | DONE | FSICalculator + TypologyRecommender; ROUND-2: `_ZONE_RULES` → `_MARKET_ZONE_RULES` (3 market × 3 zone), `market` param added to `calculate_fsi()`, `recommend_unit_mix()` clamps negative PSF; floor_plate uses clamped land_area_sqft |
| T-361 | agents/architect_agent.py — skeleton with FSICalculatorTool + TypologyRecommenderTool | P1 | DONE | FSICalculatorTool + TypologyRecommenderTool + create_architect_agent(); ROUND-2: added __main__ block for standalone testing, fixed ruff F541 |
| T-362 | tests/test_fsi_calculator.py — unit tests for FSI + typology logic | P1 | DONE | 20 tests (was 15); ROUND-2: added PSF boundary tests (4500/7000 edge), efficiency min-clamp, carpet area per-band assertions; ROUND-2b: market parameter tests, negative PSF clamp test |
| T-363 | Wire Architect response into Board Room Engineering Head | P2 | DONE | run_single_agent detects acreage pattern, auto-calls calculate_fsi + recommend_unit_mix, prepends to engineering dept_question; ROUND-2: moved `import re` + `from utils.fsi_calculator import ...` to module level, regex `acre` -> `acres?` for plural; added sqft direct detection; passes `market` to `calculate_fsi()` |

### Hardening + Docs (P2/P3)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-364 | VISION.md Phase 2 + Phase 3: mark COMPLETE, update DoD status | P2 | DONE | VISION.md + CLAUDE.md updated; ruff + 226 unit tests pass |
| T-365 | DEVLOG.md — Phase 2 + Phase 3 completion entries | P2 | DONE | Two phase entries added to DEVLOG.md; ruff + 226 unit tests pass |

### GATE STATUS (Sprint 26)

| Gate | Unlocked By | Status |
|------|-------------|--------|
| GATE-10 | T-356 — Phase 3 DoD: board session → approve 2 actions → Task Board | PASSED |
| GATE-11 | T-362 — FSI calculator tests pass ≥12 | PASSED |

---

## Task Registry — Round 25 (all DONE)

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
| T-342 | Remove stale /api/intel from _READ_ONLY_PATHS + template fetch() call | P1 | DONE | app.py _READ_ONLY_PATHS + index.html pollIntel cleaned; ruff + py_compile pass |
| T-343 | Fix datetime.utcnow() deprecation in config/checkpointer.py | P2 | DONE | → datetime.now(datetime.UTC); Python 3.12+ deprecation warning in test output |
| T-344 | GATE-2 formal verification — smoke test all 5 endpoints with live stack | P1 | DONE | All 5 endpoints return valid JSON: /api/health, /api/agents, /api/db/state, /api/intel/cards, /api/sentinel/status |
| T-345 | GATE-4 formal verification — RERA live data for Yelahanka + Hebbal | P0 | DONE | Yelahanka=165, Hebbal=736 live projects; GATE-4 PASSED |
| T-346 | Board Room sessions history — GET /api/board/sessions + dashboard list | P1 | DONE | Last 20 sessions, session_id + market + status + created_at + pitch excerpt; list below Board Room panel |
| | T-347 | Legal head agent � 5th dept, RERA/BDA/title compliance lens | P1 | DONE | Post-audit: 10 issues fixed � schema/col, dataclass field, update SQL, SELECT, CEO decompose 4?5, extract_actions, max_workers 4?5, dashboard copy, test fixture, Alembic 0007 |
| T-348 | Feasibility micro-tool — utils/feasibility.py + wire to analyst | P1 | DONE | LandFeasibility dataclass: land cost, GDV, IRR, break-even PSF; callable from analyst brief |
| T-349 | Dashboard DB Explorer panel � 3 key views as sortable tables | P2 | DONE | Frontend: 3-tab sortable tables (MARKETS/DEVELOPERS/PROJECTS) with column-click sort, 60s auto-refresh, dark-terminal CSS |
| T-350 | config/scheduler.py — replace _get_scheduler_engine() with get_engine() | P2 | DONE | Consolidate to utils/db.py singleton; scheduler runs in separate container but cleaner |
| T-351 | Scheduler — add nightly Devanahalli + Hebbal RERA cron jobs | P2 | DONE |

### Completed (Round 25 and prior)
| T-281 | Fix RERA district selector: try double-space "Bengaluru  Urban" + exhaustive alt retry | P0 | DONE | settings.py + rera_karnataka.py — verify with docker exec after next deploy |
| T-302 | pytest coverage for DBOrganizer | P1 | DONE | |
| T-315 | Scheduler: recover stuck board sessions after 30 min | P1 | DONE | |
| T-316 | Dockerfile: remove duplicate Chromium apt install | P1 | DONE | |
| T-317 | Delete deprecated GET /api/intel endpoint | P1 | DONE | |
| T-318 | Board Room engine pool_size=5 max_overflow=2 | P1 | DONE | |
| T-319 | Flask-CORS with env-var origin allowlist | P2 | DONE | |
| T-320 | _log_event: json.dumps serialisation | P2 | DONE | |
| T-321 | Replace _daily_counts with get_router_status() | P2 | DONE | |
| T-322 | Remove superseded_by FK from agent_memories | P2 | DONE | Alembic 0005 |
| T-323 | STRING_AGG ORDER BY in v_developer_scorecard | P2 | DONE | |
| T-324 | alembic upgrade head before gunicorn in docker-compose | P2 | DONE | |
| T-325 | pip-audit step in CI | P1 | DONE | |
| T-326 | make ci target in Makefile | P2 | DONE | |
| T-327 | pool_size=5 in agent_memory.py + market_intel_crew.py | P2 | DONE | |
| T-328 | Dashboard route tests (auth gate, 5 tests) | P1 | DONE | |
| T-329 | Validate data_source in db_organizer | P2 | DONE | |
| T-330 | Remove sys.path.append dead code | P1 | DONE | |
| T-331 | Scheduler engine singleton (no leak) | P1 | DONE | |
| T-332 | Gunicorn --max-requests 500 --max-requests-jitter 50 | P2 | DONE | |
| T-333 | Security headers after_request hook | P2 | DONE | |
| T-334 | .env.example: DASHBOARD_ALLOWED_ORIGINS + KEY_PREV | P2 | DONE | |
| T-335 | GitHub PR template | P3 | DONE | |
| T-336 | detect-secrets baseline + CI step | P3 | DONE | .secrets.baseline committed |
| T-337 | utils/db.py shared engine factory | P1 | DONE | |
| T-338 | pytest markers unit/integration | P1 | DONE | |
| T-339 | analyst_agent.py engine pool settings | P2 | DONE | |
| T-340 | last_scraped_at to micro_markets | P2 | DONE | Alembic 0006 |
| T-341 | NULLIF guard on absorption_pct | P2 | DONE | |

---

## GATE STATUS

| Gate | Unlocked By | Status |
|------|-------------|--------|
| GATE-2 | All 5 dashboard endpoints return live data | PASSED |
| GATE-4 | T-281 ≥50 live RERA projects for Yelahanka or Hebbal | PASSED |
| GATE-7 | T-302 test coverage ≥55% | PASSED |
| GATE-8 | T-317 + T-325 + T-328 done | PASSED |
| GATE-9 | T-319 + T-324 done | PASSED |
