# RE_OS — Task Queue
**Rebuilt: 2026-05-28** — previous file corrupted (36MB runaway write). Reconstructed from git history + CLAUDE.md.
**Highest committed task: T-305 | Next ID: T-306**

---

## SPRINT BRIEF — Round 14 (updated 2026-05-28)

**Phase 2 (Dashboard):** All 5 API endpoints live. UI panels still pending (T-280/282/283/284/286). GATE-2 blocked on these.
**Phase 3 (Board Room):** Dept-head agents live (T-257/258 ✅). CEO decompose live (T-287 ✅). Action extraction (T-288) is next.
**Phase 4 (Agent Memory):** Complete — CEO + Analyst read/write both live. Decay scheduler hook (T-298) pending.
**GATE-2:** Requires T-280+282+283+284+286 + smoke test (T-293).
**GATE-4:** RERA fix (T-281) is the remaining blocker — T-285 ✅ + T-287 ✅ already done.

---

## DONE — Recent Completed Tasks

| ID | Title | Assignee | Commit |
|----|-------|----------|--------|
| T-233 | Process reap — zombie guard on pipeline stop | Kilo | 8f9b8e9 |
| T-234 | DB connect_timeout=5 on pool init | Kilo | 8f9b8e9 |
| T-235 | Auth hardening — read-only endpoints exempt from API key | Kilo | 8f9b8e9 |
| T-245 | Stage events — structured writes to agent_runs | Kilo | 8f9b8e9 |
| T-250 | API key dual-window rotation (DASHBOARD_API_KEY_PREV) | Kilo | 8f9b8e9 |
| T-253 | Prometheus counters wired into pipeline | Kilo | 8f9b8e9 |
| T-255 | Agent memory read — inject top-5 facts into CEO + Analyst backstory | Cline | 20c1e56 |
| T-256 | Agent memory write — CEO extracts 1-3 key facts post-synthesis | Cline | 20c1e56 |
| T-260 | Board Room API — POST + GET /api/board/session | Cline | ceccf9f |
| T-257 | 4 dept-head agent builders in agents/board_room/ | Kilo | 1481cfc |
| T-258 | _run_dept_heads() — ThreadPoolExecutor + 90s timeout | Kilo | 1481cfc |
| T-285 | Analyst memory write post-Stage 3 | Kilo | 1481cfc |
| T-287 | CEO decomposition stage — pitch → 4 sub-questions | Kilo | 1481cfc |
| T-289 | Stage event metadata column — migration + _write_stage_event kwarg | Kilo | 1481cfc |
| T-291 | Rate limiting — flask-limiter on 3 write endpoints | Kilo | 1481cfc |
| T-208 | Brigade/Prestige developer scout URL updates | Cline | 1481cfc |
| T-299 | Obsidian sync: confidence/sources/is_estimated + daily log append | Cline | 1481cfc |
| T-304 | agent_factory.py — all 9 agent roles registered | Cline+fix | 1481cfc |
| T-305 | get_board_session() named column access via .mappings() | Claude | 1481cfc |

---

## PENDING — Round 14 Kilo Code Tasks

---

### T-280 — Dashboard UI: Market Inventory Cards

**Assignee:** Cline | **Priority:** P0 — GATE-2 blocker
**File:** `dashboard/templates/index.html`

Call `GET /api/intel/cards` on page load. Render 3 cards (Yelahanka, Devanahalli, Hebbal) showing: market name, project count, avg PSF (dash if null), and a Download Report link calling `GET /api/intel/download?market={market}` as a file download. Show ESTIMATED DATA badge if `estimated: true`. Vanilla JS only, no frameworks.

**Done when:** 3 market cards render on page load with live data from the API.

---

### T-281 — RERA Scraper Fix: Yelahanka + Hebbal

**Assignee:** Kilo Code | **Priority:** P0 — GATE-4 blocker
**File:** `scrapers/rera_karnataka.py`

Yelahanka and Hebbal return 8 hardcoded fallback projects. Devanahalli (317 projects) works via POST to `https://rera.karnataka.gov.in/projectViewDetails`. Read `MARKET_RERA_CONFIG` in `config/settings.py` — compare working Devanahalli vs failing Yelahanka/Hebbal configs. The issue is likely the `subdistrict` field value. For Hebbal: try `Bangalore North` as alternate spelling of `Bengaluru North`. Add retry with alternate spelling if first POST returns 0 rows + HTTP 200. Log first 500 chars of raw response HTML at WARNING on failure.

**Done when:** Yelahanka or Hebbal returns >50 live RERA projects, OR root cause documented in CHANGELOG.md with exact HTTP response and subdistrict values tried.

---

### T-282 — Dashboard UI: Pipeline Trigger Panel

**Assignee:** Cline | **Priority:** P0 — GATE-2 blocker
**File:** `dashboard/templates/index.html`

For each market: Run button calls `POST /api/run/{market}` with `X-API-Key` header from a UI input field. Stop button calls `DELETE /api/run/{market}`. Poll `GET /api/status` every 5 seconds and show each market state (running/done/failed) as a coloured badge. Vanilla JS only.

**Done when:** Run button triggers pipeline, status badge updates within 5 seconds, Stop button terminates it.

---

### T-283 — Dashboard UI: Log Stream Panel

**Assignee:** Cline | **Priority:** P0 — GATE-2 blocker
**File:** `dashboard/templates/index.html`

Log tail box connected to `GET /api/logs/stream?market={market}` via SSE (EventSource). Market selector dropdown. Auto-scrolls to bottom. Max 200 lines shown (discard oldest). Auto-reconnects on disconnect. Vanilla JS only.

**Done when:** Log box shows live lines as pipeline runs, switches market on dropdown change without page reload.

---

### T-284 — Dashboard UI: DB State + Report Viewer

**Assignee:** Cline | **Priority:** P0 — GATE-2 blocker
**File:** `dashboard/templates/index.html`

**Panel 4 — DB State:** Call `GET /api/db/state` on load and every 60 seconds. Show total RERA projects, listings, Kaveri registrations, guidance values, and table of last 5 runs (market, status, start time, duration).

**Panel 5 — Report Viewer:** Market dropdown + Load button. Calls `GET /api/reports/{market}`, renders `content` field in a `<pre>` block with a Copy button.

**Done when:** Both panels render live data without JS errors.

---

### T-285 — Agent Memory: Analyst Memory Write

**Assignee:** Kilo Code | **Priority:** P1
**File:** `crews/market_intel_crew.py`

Agent memories are read for the Analyst before Stage 3 but never written after. After the analyst task completes (before CEO synthesis), extract 2-3 market facts from `analyst_raw` using the same Cerebras LiteLLM extraction pattern already in the file (see CEO memory write block, ~lines 848-882). Write with `write_memory("analyst", market_name, fact, confidence)`. Wrap in try/except — failure must not abort pipeline.

**Done when:** After a successful pipeline run, `SELECT * FROM agent_memories WHERE agent_id = 'analyst'` returns rows.

---

### T-286 — Dashboard UI: Sentinel Status Footer

**Assignee:** Cline | **Priority:** P1
**File:** `dashboard/templates/index.html`

Sticky footer bar at bottom of page. Calls `GET /api/sentinel/status` on load and every 30 seconds. Display: `last_run.status` as coloured badge (green=success, red=error, grey=null), `last_run.started_at` formatted as local time, `next_run.label`. On API error show "Sentinel unavailable". Vanilla JS only.

**Done when:** Footer renders with live sentinel data and auto-refreshes every 30 seconds.

---

### T-287 — Board Room: CEO Decomposition Stage

**Assignee:** Kilo Code | **Priority:** P1
**File:** `crews/board_room.py`

Before the 4 dept heads run in `_run_dept_heads`, add Stage 0: call `_ceo_decompose(pitch, market)` which uses the CEO agent (HEAVY tier from `config/llm_router.get_heavy_llm()`) to decompose the pitch into 4 dept-specific sub-questions as JSON: `{"bd": "...", "finance": "...", "engineering": "...", "ops": "..."}`. Each dept head then receives its specific sub-question as the task description instead of the raw pitch. Store the decomposition result in the board session transcript under the key `ceo_decomposition`. Fall back to raw pitch for all agents if decomposition fails or JSON is malformed.

**Done when:** Board session transcript includes `ceo_decomposition` with 4 department sub-questions after a real pitch.

---

### T-288 — Board Room: Action Extraction

**Assignee:** Kilo Code | **Priority:** P1
**File:** `crews/board_room.py`

After dept heads complete in `_run_board_session_bg`, add `_extract_actions(dept_responses, pitch, market)`: a Cerebras 8b LiteLLM call (same pattern as CEO memory write) that reads the 4 dept responses and extracts 3-5 concrete actions as JSON list: `[{"action": "...", "owner": "bd|finance|engineering|ops", "priority": "high|medium|low"}]`. Write to `board_sessions.transcript.actions`. Wrap in try/except — failure sets `actions: []`, does not crash the session.

**Done when:** Board session transcript includes `actions` array with at least 1 extracted action after a real pitch.

---

### T-289 — Pipeline Observability: Stage Event Metadata Column
Status: IN-PROGRESS
**Assignee:** Kilo Code | **Priority:** P1
**Files:** `database/` (new migration SQL), `utils/db_organizer.py`, `crews/market_intel_crew.py`

Create `database/migrate_add_stage_metadata.sql`:
```sql
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
```
Update `_write_stage_event` in `utils/db_organizer.py` to accept a `metadata: dict = None` kwarg and write it to the new column. Update `_write_stage_event_to_db` calls in `market_intel_crew.py` to pass: Stage 1 `{"records_scraped": N}`, Stage 2 `{"inserted": N, "updated": N, "failed": N}`, Stage 3 `{"has_fallback": bool}`.

**Done when:** `SELECT metadata FROM agent_runs ORDER BY created_at DESC LIMIT 5` returns non-null JSONB after a pipeline run.

---

### T-290 — LLM Router: Daily Token Usage Tracking

**Assignee:** Kilo Code | **Priority:** P1
**File:** `config/llm_router.py`

Add per-provider daily token counters (in-process dict, reset at UTC midnight). Add `DAILY_LIMITS` dict: `cerebras=1_000_000, groq=500_000, gemini=3_500_000, nvidia=2_000_000, openrouter=500_000`. Add `record_token_usage(provider, tokens)` and `is_near_quota(provider) -> bool` (True if >90% of daily limit used). Call `is_near_quota(provider)` inside `get_light_llm()`, `get_analysis_llm()`, `get_heavy_llm()` — if True, treat as excluded and try next provider. Estimate token count from character count / 4.

**Done when:** When a provider is manually set to 90% quota in a unit test, `get_light_llm()` skips it and returns the next available provider.

---

### T-291 — Security: Rate Limiting on Write Endpoints

**Assignee:** Kilo Code | **Priority:** P1
**Files:** `dashboard/app.py`, `requirements.txt`

Add `flask-limiter>=3.5` to `requirements.txt`. Initialize `Limiter` with in-memory storage (no Redis dependency needed — `storage_uri="memory://"`). Apply limits:
- `POST /api/run/<market>` → 10 per hour per IP
- `POST /api/board/session` → 20 per hour per IP
- `POST /api/agents/<id>/command` → 30 per hour per IP

Return 429 with `{"error": "rate limit exceeded"}` on breach. Read-only endpoints exempt.

**Done when:** After 11 rapid POST requests to `/api/run/yelahanka`, the 11th returns 429. Normal usage (< limit) returns 200.

---

### T-292 — Scheduler: Per-Market Log Files

**Assignee:** Kilo Code | **Priority:** P1
**File:** `config/scheduler.py`

The scheduled 2AM RERA job currently calls `run_market_intelligence()` inline — this blocks the APScheduler thread for the full pipeline duration and logs to shared `crew.log`. Change to `subprocess.Popen` fan-out (same pattern as `run_all_markets()` in `crews/market_intel_crew.py`): each market spawns its own subprocess writing to `/app/logs/{slug}.log`. Scheduler thread returns immediately after spawning all subprocesses.

**Done when:** After the scheduled job fires, each market has its own log file, and the APScheduler thread is not blocked (verify with a short test job that fires immediately).

---

### T-293 — GATE-2 Smoke Test Pass

**Assignee:** Kilo Code | **Priority:** P0 — run last, after T-280/282/283/284/286
**Depends on:** T-280, T-282, T-283, T-284, T-286

1. `docker compose up -d` — wait for all containers healthy
2. Curl all 5 endpoints — all must return HTTP 200 with non-empty JSON:
   - `GET /api/health`
   - `GET /api/intel/cards`
   - `GET /api/db/state`
   - `GET /api/sentinel/status`
   - `GET /api/agents`
3. Open `http://localhost:8050` in headless browser — all UI panels render, no JS console errors
4. Document pass/fail for each check in `CHANGELOG.md` under `## GATE-2 — 2026-05-28`
5. Fix any failures before marking done

**Done when:** All GATE-2 checks pass and CHANGELOG.md has the entry.

---

## PENDING — Round 14 Cline Tasks

---

### T-294 — Board Room: Per-Agent Task Prompts

**Assignee:** Cline | **Priority:** P1
**File:** `crews/board_room.py`

Replace the generic `task_description` string in `_run_dept_heads` with 4 agent-specific prompts:
- **BD:** market absorption data + GO/NO-GO verdict + 3 specific risks + 3 specific upsides
- **Finance:** break-even PSF calculation + IRR range estimate + VIABLE/CONDITIONAL/UNVIABLE verdict
- **Engineering:** FEASIBLE/CONDITIONAL/NOT_FEASIBLE verdict + top 3 regulatory/approval blockers + construction cost risk
- **Ops:** recommended channel mix (channel partner/direct/digital %) + quarterly sales velocity assumption + 3 launch KPIs

**Done when:** Board session transcript shows 4 structurally different responses, each following its expected format.

---

### T-295 — Dashboard: Input Validation for Board Session

**Assignee:** Cline | **Priority:** P1
**File:** `dashboard/app.py`

`POST /api/board/session`: validate that `pitch` is a non-empty string ≤ 2000 chars, and `market` is one of `["Yelahanka", "Devanahalli", "Hebbal", ""]` (empty = all markets, valid). Return 400 with `{"error": "pitch required and must be under 2000 characters"}` or `{"error": "invalid market — must be Yelahanka, Devanahalli, or Hebbal"}` on violation.

**Done when:** Empty pitch → 400. Unknown market → 400. Valid request → 200 with session_id.

---

### T-296 — Dashboard: Auth Gate for /metrics Endpoint

**Assignee:** Cline | **Priority:** P1
**File:** `dashboard/app.py`

`/metrics` is currently unauthenticated and leaks pipeline telemetry. Remove `/metrics` from `_READ_ONLY_PATHS` (or don't add it there). Add a dedicated check in the `before_request` handler: if the path is `/metrics` and `DASHBOARD_API_KEY` is set, require the key.

**Done when:** With `DASHBOARD_API_KEY=test` set: `curl /metrics` → 401, `curl -H "X-API-Key: test" /metrics` → 200.

---

### T-297 — Agent Memory: Row Cap Per Agent+Market

**Assignee:** Cline | **Priority:** P1
**File:** `utils/agent_memory.py`

After a successful `write_memory()` insert, if row count for the same `agent_id + market` pair exceeds 500, delete the lowest-confidence rows beyond 500:
```sql
DELETE FROM agent_memories WHERE id IN (
  SELECT id FROM agent_memories
  WHERE agent_id = :agent_id AND market = :market
  ORDER BY confidence ASC, created_at ASC
  LIMIT :excess
)
```
Run this cleanup inside the same `begin()` transaction block as the insert.

**Done when:** After 501 writes for the same agent+market, `SELECT COUNT(*) FROM agent_memories WHERE agent_id=X AND market=Y` returns 500.

---

### T-298 — Agent Memory: Decay Scheduler Hook

**Assignee:** Cline | **Priority:** P1
**File:** `config/scheduler.py`

`decay_memories()` exists in `utils/agent_memory.py` but is never called automatically. Add a weekly APScheduler job: every Monday at 03:00 UTC, call `decay_memories(days=30, decay_amount=0.1)` and log `f"[Scheduler] Memory decay: {n} rows deleted"` where n is the return value.

**Done when:** Scheduler starts without error. The weekly job appears in the APScheduler job list. Confirmed by printing `scheduler.get_jobs()` at startup.

---

### T-299 — Obsidian Sync: Daily Log Append

**Assignee:** Cline | **Priority:** P2
**File:** `utils/obsidian_sync.py`

After writing the wiki page, also append a one-liner to the current day's daily log. Path: resolve `OBSIDIAN_VAULT_PATH` parent → `01 Daily/[AI] YYYY-MM-DD.md` (create if not exists). Content to append: `- RE_OS: {market} market brief synced (confidence: {confidence}, sources: {sources})`. Non-fatal on failure — wrap in try/except and log at WARNING.

**Done when:** After a pipeline run, the daily log file at the correct path contains the sync entry.

---

### T-300 — RERA Scraper: User-Agent Rotation

**Assignee:** Cline | **Priority:** P2
**File:** `scrapers/rera_karnataka.py`

Add a list of 4 Chrome User-Agent strings to `RERAKarnatakaScraper`. Use `itertools.cycle` to rotate through them on each retry attempt. Log the UA string used at DEBUG level. This is a defensive measure against portal UA fingerprinting (may help with Yelahanka/Hebbal fallback issue).

**Done when:** On second retry attempt, the UA header is different from the first attempt. Confirmed by DEBUG log.

---

### T-301 — CI: Board Room Smoke Test

**Assignee:** Cline | **Priority:** P1
**File:** `tests/test_board_room.py` (new)

Create `tests/test_board_room.py`. Use `unittest.mock.patch` to mock:
- `crews.board_room._run_dept_heads` → returns `{"bd": "GO", "finance": "VIABLE", "engineering": "FEASIBLE", "ops": "3 channels"}`
- `crews.board_room._create_session_row` → returns `True`
- `crews.board_room._update_session_row` → returns `True`

Call `run_board_session("Should LLS enter Yelahanka at 6500 PSF?", "Yelahanka")`. Assert: returned dict has `session_id` (valid UUID string), `status == "pending"`, `market == "Yelahanka"`. No real DB connection needed.

**Done when:** `pytest tests/test_board_room.py` passes with no database required.

---

### T-302 — Test Coverage: DB Organizer

**Assignee:** Cline | **Priority:** P1
**File:** `tests/test_db_organizer.py` (new)

Use real PostgreSQL via `DATABASE_URL` env var (docker-compose test DB). Test:
1. `DBOrganizer.run()` with 2 valid RERA project dicts → `inserted == 2` first run, `updated == 2` second run with same data
2. Record missing `project_name` field → skipped, no exception raised
3. SAVEPOINT rollback: one bad record in a batch doesn't prevent the rest from inserting

**Done when:** `pytest tests/test_db_organizer.py` passes against the live DB container.

---

### T-303 — Test Coverage: Intel Output Parsing

**Assignee:** Cline | **Priority:** P1
**File:** `tests/test_intel_output.py` (new)

Mock `crew.kickoff()` return value. Test the output extraction logic in `run_market_intelligence()`:
1. `tasks_output[1].raw` contains `"the final answer to the original input question"` → `report_body` falls back to `analyst_raw`
2. Valid CEO output (>50 chars, no placeholder) → `report_body == ceo_raw`, `ceo_section == ""`
3. CEO output < 50 chars → fallback path triggered

No real LLM calls. Extract the output parsing logic into a testable function if needed.

**Done when:** `pytest tests/test_intel_output.py` passes with no LLM calls.

---

### T-304 — agent_factory.py: Register Board Room Roles

**Assignee:** Cline | **Priority:** P2
**File:** `utils/agent_factory.py`

Add board room role entries to `_AGENT_FACTORIES`:
```python
"bd": "agents.board_room.bd_head.build_bd_head_agent",
"finance": "agents.board_room.finance_head.build_finance_head_agent",
"engineering": "agents.board_room.engineering_head.build_engineering_head_agent",
"ops": "agents.board_room.ops_head.build_ops_head_agent",
```
After this, `create_agent("bd", "analysis")` should return a configured BD head Agent without error.

**Done when:** `create_agent("bd", "analysis")` returns an Agent instance. `create_agent("unknown", "analysis")` raises `ValueError`.

---

### T-305 — board_room.py: Named Column Access

**Assignee:** Cline | **Priority:** P2
**File:** `crews/board_room.py`

`get_board_session()` uses positional tuple indices (`row[0]`, `row[1]` etc.) — brittle if schema column order changes. Switch to `conn.execute(...).mappings().fetchone()` (SQLAlchemy 2.x) to return a dict-like `RowMapping` accessed by column name: `row["session_id"]`, `row["pitch"]`, etc.

**Done when:** `get_board_session()` returns identical output to before, accessed by column name not index. Manual test: call the function and verify all 7 fields are returned correctly.

---

## GATES STATUS

| Gate | Name | Unlocked By | Status |
|------|------|-------------|--------|
| GATE-1 | Pipeline Observability | T-289 + stage events verified in agent_runs | PENDING |
| GATE-2 | Dashboard Smoke Test | T-280+282+283+284+286+293 | PENDING |
| GATE-3 | Auth Hardening | T-296 | PENDING |
| GATE-4 | Intel Quality Baseline | T-281+T-287+T-288 | PENDING |
| GATE-5 | Log Monitor Eliminated | T-292 | PENDING |

---

## OPEN BUGS (fix inline if encountered, no task ID needed)

- **Bug 3:** `delay_months` GENERATED COLUMN in `database/schema.sql` may fail on DB wipe + reinit. Move to view-level calculation when hit. Low urgency — DB currently healthy.
- **Kaveri portal:** `kaveri.karnataka.gov.in` consistently unreachable. 7 seeded GV values in use. Medium urgency.
- **RERA Yelahanka/Hebbal:** 8 hardcoded fallback projects. Fix tracked in T-281.
