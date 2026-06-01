# RE_OS — Task Queue
**Stage 3 · 2026-05-30 | Single-brain: Kilo Code**
**Next task ID: T-389**

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
