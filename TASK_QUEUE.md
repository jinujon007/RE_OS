# RE_OS — Task Queue
**Rebuilt: 2026-05-28** — previous file corrupted (36MB runaway write). Reconstructed from git history + CLAUDE.md.
**Highest committed task: T-314 | Next ID: T-315**

---

## SPRINT BRIEF — Round 20 (updated 2026-05-29)

**Test coverage: 214 passed, 0 failed** (was 189 at start of Round 18)

**T-301 ✅** — `tests/test_board_room.py`: 12 tests — session_id, status, DB failure, named column access, dept template structure
**T-303 ✅** — `tests/test_intel_output.py`: 13 tests — CEO fallback logic, boundary at 100 chars, return types
**T-294 ✅ VALIDATED** — Live board session returned 4 structurally differentiated responses:
  - BD: Conditional GO, entry PSF 6200–7200, 3 risks + 3 upsides
  - Finance: CONDITIONAL, break-even ₹10,925, IRR 5%/9%/2% base/bull/bear
  - Engineering: FEASIBLE–CONDITIONAL, BDA+RERA+BBMP, 30/45/25 BHK mix
  - Ops: 45%CP/30%direct/25%digital, Q1-Q4 velocity 30-35-35-27, August 2026 launch

**Board Room schema fixed:**
- `_create_session_row`: was writing to wrong columns (pitch/transcript → pitch_text/dept columns)
- `_update_session_row`: now writes bd_response/finance_response/engineering_response/ops_response
- `get_board_session`: reads individual columns, synthesises transcript dict for dashboard
- Bug: `::uuid` cast in SQLAlchemy text() strips bind parameter — fixed via `uuid.UUID()` objects

**T-295 ✅** / **T-296 ✅** — Already implemented in Round 16. Marked done.
**T-304 ✅** / **T-305 ✅** — Already implemented. Marked done.

**Next:** Phase S (scout parallelism) — needs T-247 (remove fake context chains) first. GATE-4 (Yelahanka/Hebbal live RERA).

---

## SPRINT BRIEF — Round 19 (updated 2026-05-29)

**Phase 4 (Agent Memory): ✅ COMPLETE**
- T-297 ✅ Row cap: 500 per agent+market, prune lowest-confidence on overflow
- T-298 ✅ Decay hook: Monday 03:00 UTC in APScheduler, confirmed in startup log
- T-299 ✅ Obsidian daily log append: live (implemented in earlier round)
- Bug fix: UNIQUE constraint on (agent_id, market, fact) — ON CONFLICT was silently failing
- Bug fix: decay_memories SQL: column is memory_id not id

**T-300 ✅ RERA UA rotation:** 4 UA strings, itertools.cycle, rotates on every retry

**GATE-6: ✅ PASSED (2026-05-29)**
- MarketSummaryTool returns avg_listing_psf=9666 (Devanahalli), floor=8216, ceiling=11115
- Analyst Stage 3 now sees real PSF range — CEO briefs will cite actual numbers

**Scheduler bonus:** avg_psf_sale in market_snapshots now uses listing PSF (was always NULL)

**Test suite: 189 passed, 0 failed** — maintained across both rounds

**Next priorities:**
- T-294 validation: trigger real board session, confirm 4 dept responses are structurally differentiated
- Phase S (scout parallelism): requires T-247 (fake context chains removed) first
- GATE-4: RERA live data for Yelahanka/Hebbal (currently fallback sample)

---

## SPRINT BRIEF — Round 18 (updated 2026-05-29)

**Review fixes (all done):**
- T-R18-1 ✅ CI unblocked — litellm imports local, alias added, 189/189 pass
- T-R18-2 ✅ PSF data live — Yelahanka ₹11,041 / Devanahalli ₹9,666 (from listings)
- T-R18-3 ✅ Connection pool leak fixed — agents_state finally block + health SELECT 1
- T-R18-4 ✅ Board Room thread safety — per-session `_session_excluded` set
- T-R18-5 ✅ T-294 per-agent prompts — BD/Finance/Engineering/Ops structured templates
- T-R18-6 ✅ CEO placeholder detection — length gate (< 100 chars) replaces string match
- T-R18-7 ✅ sync_to_obsidian guarded — non-fatal, logged at WARNING
- T-R18-8 ✅ intel/cards TTL cache — 120s, eliminates 3 file reads per poll
- T-R18-9 ✅ Board Room UI panel — pitch + market + CONVENE BOARD + poll + render

**Next priorities:**
- T-297 (memory row cap) + T-298 (decay hook) — Agent Memory Phase 4 completion
- GATE-6 — run pipeline to confirm avg_listing_psf appears in Analyst brief output
- T-294 validation — trigger a real board session to confirm dept-head responses are structurally differentiated

---

## SPRINT BRIEF — Round 17 (updated 2026-05-29)

**Phase 2 (Dashboard):** T-280 ✅, T-282 ✅, T-283 ✅, T-286 ✅, T-293 ✅ done. T-284 panel exists. GATE-2 PASSED.
**Phase 3 (Board Room):** Dept-heads ✅, CEO decompose ✅, Action extraction ✅. Per-agent task prompts (T-294) next.
**Phase 4 (Agent Memory):** Complete — CEO + Analyst read/write live. Row cap (T-297) + decay hook (T-298) pending.
**Intelligence OS Phase 2:** T-306 ✅, T-308 ✅, T-309 ✅, T-310 ✅, T-311 ✅, T-312 ✅, T-313 ✅, T-314 ✅ — Appreciation layer + Kaveri txn scout integrated.
**GATE-1:** ✅ PASSED (2026-05-28)
**GATE-2:** ✅ PASSED (2026-05-29) — all 5 endpoints 200, all UI panels render, zero JS errors.
**GATE-4:** RERA alternate subdistrict retry live (T-281). Root cause resolved.
**GATE-6:** T-308+T-309+T-310 all done → pending one pipeline run to confirm Analyst output contains PSF trajectory.

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
| T-288 | Board Room: action extraction via Cerebras 8b post dept-heads | Kilo+fix | Round 15 |
| T-290 | LLM Router: daily token usage tracking + is_near_quota() wired | Kilo | Round 15 |
| T-292 | Scheduler: per-market subprocess fan-out, non-blocking thread | Kilo+fix | Round 15 |
| T-314 | LLM Router: Split Shared Gemini Exclusion Key | Kilo | T-314 |
| T-306 | LLM Router: Wire record_token_usage() via litellm callback | Kilo | Round 17 |
| T-308 | Intelligence: bangalore_infrastructure_timeline.json (18 projects) | Kilo | Round 17 |
| T-309 | Intelligence: Appreciation Forecasting Model (utils/appreciation_model.py) | Kilo | Round 17 |
| T-310 | Intelligence: Wire forecasting into Analyst Stage 3 | Kilo | Round 17 |
| T-311 | Intelligence: Kaveri Transaction Scraper (scrapers/kaveri_transaction_scout.py) | Kilo+fix | Round 17 |
| T-312 | Cerebras 404: Model name fixed llama3.1-8b → gpt-oss-120b | Kilo | Round 17 |
| T-313 | Developer Scout: Two-URL listing strategy for Brigade/Prestige/Sobha | Kilo | Round 17 |

---

## PENDING — Round 16 Kilo Code Tasks

---

### T-306 — LLM Router: Wire record_token_usage() into pipeline ✅ DONE (Round 17)

**Assignee:** Kilo Code | **Priority:** P1
**File:** `config/llm_router.py`, `crews/market_intel_crew.py`

T-290 added `record_token_usage(provider, tokens)` and `is_near_quota()` but nothing calls `record_token_usage()` — quota counters are always 0, protection is dormant.

**The hook:** litellm has a global callback system. Add a litellm success callback in `llm_router.py` that fires after every LLM call:
```python
import litellm
def _litellm_usage_callback(kwargs, completion_response, start_time, end_time):
    try:
        provider = kwargs.get("model", "").split("/")[0]
        tokens = completion_response.usage.total_tokens if completion_response.usage else 0
        record_token_usage(provider, tokens)
    except Exception:
        pass
litellm.success_callback = [_litellm_usage_callback]
```
Register this callback at module import time (outside any function). Providers in kwargs model strings: `"openai/llama-..."` → provider is `"openai"` — you need to map to our provider names. Use the API key to determine actual provider: if `api_key == CEREBRAS_API_KEY` → "cerebras", if `base_url` contains "groq" → "groq", etc. Use kwargs `"api_base"` or `"api_key"` to distinguish.

**Done when:** After a full pipeline run, `config.llm_router._daily_counts` has non-zero values for at least one provider. Confirm by adding a temporary log line at the end of `run_market_intelligence()`: `logger.info(f"[Router] Daily counts: {_daily_counts}")`.

---

### T-307 — GATE-1 Verify: Stage events in agent_runs ✅ DONE

**Assignee:** Kilo Code | **Priority:** P1 — unlocks GATE-1 | **Status:** DONE
**Depends on:** Docker stack running with data

Run the pipeline for Devanahalli (it has live RERA data, most reliable):
```bash
docker compose exec agents python crews/market_intel_crew.py --market Devanahalli
```
Then query:
```sql
SELECT event_type, stage, status, metadata, duration_seconds
FROM agent_runs
WHERE market = 'Devanahalli'
ORDER BY created_at DESC LIMIT 15;
```
Expected: at least 3 rows — stage_start/stage_complete events for stages 1, 2, 3. `metadata` column should be non-null JSONB for Stage 1 (records_scraped), Stage 2 (inserted/updated/failed), Stage 3 (has_fallback).

If metadata is null or missing for any stage: check `_write_stage_event_to_db()` call sites in `market_intel_crew.py` — find which calls don't pass the `metadata=` kwarg and add it.

**Done when:** All 3 stages show non-null metadata in agent_runs. Document the query output in `CHANGELOG.md` under `## GATE-1 — 2026-05-28`. GATE-1 is then passed.

**Result (2026-05-28):** PASSED. All 3 stages have non-null metadata. Fixes applied: (1) `_STAGE_STATUS_MAP` in `db_organizer.py` — event statuses `start/success/skip` mapped to DB check constraint values `in_progress/completed/skipped`; (2) empty-records early return in `validator.py` — added missing `pass_rate_pct` key; (3) safe `.get()` in `market_intel_crew.py`. See `kilo_logs/CHANGELOG.md` for query output. Side note: Cerebras `llama3.1-8b` returns 404 — Stage 1+3 LLM calls fail, needs API key/model fix. Stage 2 (Python DB) works regardless.

---

## PENDING — Round 16 Cline Tasks

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
**Partial done (Round 15):** `ALT_SUBDISTRICTS` retry loop added. Hebbal tries `Bangalore North`, Yelahanka tries `Bengaluru North`. Logs raw HTML on failure.

**Remaining:** Run a live scrape in Docker and check the logs. If still 0 results, inspect raw HTML (logged at WARNING) to find the correct subdistrict value or whether the POST payload needs a different field. May need `taluk` field or different payload structure.

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


### T-286 — Dashboard UI: Sentinel Status Footer

**Assignee:** Cline | **Priority:** P1
**File:** `dashboard/templates/index.html`

Sticky footer bar at bottom of page. Calls `GET /api/sentinel/status` on load and every 30 seconds. Display: `last_run.status` as coloured badge (green=success, red=error, grey=null), `last_run.started_at` formatted as local time, `next_run.label`. On API error show "Sentinel unavailable". Vanilla JS only.

**Done when:** Footer renders with live sentinel data and auto-refreshes every 30 seconds.

---







### T-293 — GATE-2 Smoke Test Pass ✅ DONE 2026-05-29

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

## PENDING — Round 17 (New — TPM Sprint 2026-05-28)

---

### T-312 — Cerebras 404: Diagnose + Fix Model Name

**Assignee:** Kilo Code | **Priority:** P0 — all LIGHT + ANALYSIS tier LLM calls degraded
**File:** `config/settings.py`, `.env`

T-307 result logged: "Cerebras `llama3.1-8b` returns 404 — Stage 1+3 LLM calls fail."
When Cerebras returns 404, the `_litellm_usage_callback` fires and `_detect_api_error_provider` marks cerebras excluded. Every LIGHT + ANALYSIS call then falls through to Gemma → NVIDIA → Ollama, adding 3–5x latency and consuming other providers' budgets.

**Steps:**
1. Inside the agents container, run:
   ```bash
   curl -s -H "Authorization: Bearer $CEREBRAS_API_KEY" \
     https://api.cerebras.ai/v1/models | python3 -c "import sys,json; [print(m['id']) for m in json.load(sys.stdin)['data']]"
   ```
2. Compare the returned model IDs against `CEREBRAS_MODEL=llama3.1-8b` in `.env`.
   Common fix: the correct model ID is `llama3.1-8b` OR `llama-3.1-8b` (with hyphen). Cerebras changed naming conventions.
3. If model name is wrong: update `CEREBRAS_MODEL` in `.env` and restart agents.
4. If API key is invalid/expired: log the error clearly and note in CHANGELOG.md.
5. After fix: run one pipeline call and confirm `[Router] LIGHT tier → Cerebras` appears in logs (not fallback).

**Done when:** `logs/crew.log` shows `[Router] LIGHT tier → Cerebras` on next pipeline run AND no 404 error in logs.

---

### T-313 — Developer Scout: Listing Page URL Strategy

**Assignee:** Kilo Code | **Priority:** P1 — developer intelligence limited to 1 project per developer
**File:** `scrapers/developer_scout.py`

After T-208, `DEVELOPER_SITES` entries for Brigade, Prestige, Sobha point to individual project pages (e.g. `brigade-insignia`, `prestige-finsbury-park`, `sobha-palm-court`). This means developer scout can only ever find 1 project per developer — the exact opposite of its purpose.

**The fix — two-URL strategy:**
Add a `listing_url` field alongside `projects_url`. `listing_url` = the developer's "all projects" or "projects in Bengaluru" index page. `projects_url` becomes the fallback if `listing_url` returns < 1000 chars.

**Updated entries (research-validated — verify HTTP 200 before committing):**
```python
"Brigade": {
    "listing_url": "https://www.brigadegroup.com/residential/projects/bengaluru",
    "projects_url": "https://www.brigadegroup.com/residential/projects/bengaluru/brigade-insignia",  # fallback
},
"Prestige": {
    "listing_url": "https://www.prestigeconstructions.com/residential-projects/bangalore",
    "projects_url": "https://www.prestigeconstructions.com/residential-projects/bangalore/prestige-finsbury-park",
},
"Sobha": {
    "listing_url": "https://www.sobha.com/locations/bengaluru/",
    "projects_url": "https://www.sobha.com/bengaluru/sobha-palm-court/",
},
```
For Godrej/Adarsh/Salarpuria/Shriram/Mantri — the existing `projects_url` already points to listing pages, no change needed.

In `_scout_developer()`: try `listing_url` first (if it exists and len > 1000 chars); fall back to `projects_url`.

**Done when:** A standalone `python scrapers/developer_scout.py --developer Brigade --market Yelahanka` returns >1 project for Brigade (or logs a clear reason why Brigade's page returned 0 — HTTP status, keyword filter, etc.).

---

### T-314 — LLM Router: Split Shared Gemini Exclusion Key

**Assignee:** Kilo Code | **Priority:** P2 — LLM reliability / subtle fallback bug
**File:** `config/llm_router.py`, `config/settings.py`, `crews/market_intel_crew.py`

**The bug:** Both Gemini Flash (CEO/ANALYSIS tier, 250k TPM) and Gemma 27B (LIGHT tier, 15k TPM) share the exclusion key `"gemini"`. A Gemma rate-limit (easy to hit at 15k TPM) incorrectly blocks Gemini Flash for the entire pipeline run. This is why `_clear_excluded()` must be called before Stage 3 — it's a workaround for a design flaw.

**Fix:**
1. In `llm_router.py` `get_light_llm()`: change the exclusion check to `_is_excluded("gemini_gemma")` and the exclusion call in crew to `_exclude("gemini_gemma")`.
2. In `get_heavy_llm()` and `get_analysis_llm()`: use `_is_excluded("gemini_flash")`.
3. In `_detect_api_error_provider()`: when the model is `GEMINI_LIGHT_MODEL` (Gemma), return `"gemini_gemma"`; when it's `GEMINI_CEO_MODEL` (Flash), return `"gemini_flash"`.
4. Update `DAILY_LIMITS` dict: add keys `"gemini_flash"` and `"gemini_gemma"` (remove `"gemini"`).
5. Remove the `_clear_excluded()` call before Stage 3 in `market_intel_crew.py` — it's no longer needed and now hides failures by clearing all exclusions.
6. Update `get_router_status()` to show both keys.

**Done when:** `ruff check .` passes. `pytest tests/unit/test_llm_router.py` passes. Manual review confirms Stage 1 Gemma exclusion does NOT appear in `_EXCLUDED` as "gemini" anymore.

---

---

## INTELLIGENCE OS — Bangalore BMR Phase 2 (Infrastructure Appreciation Layer)

> **Context:** Phase 1 complete (2026-05-28) — 130-pincode master table built.
> `RE_OS/data/bangalore_pincode_master.csv` + `03 LLS/01 Wiki/markets/bangalore/Bangalore Pincode Master.md`
>
> Phase 2 goal: make RE_OS **predictive**, not just descriptive. Every pincode query should return a
> 3yr/5yr/10yr PSF trajectory based on infrastructure deployment schedules — not just current price.
> This is the signal that competitors cannot buy from JLL or PropStack. It has to be built.
>
> Phase 3 (after Phase 2): Demographics layer — buyer personas, income distribution, migration patterns,
> job-posting demand signals by corridor.
> Phase 4 (after Phase 3): Kaveri transaction scraper — actual registration prices vs listing prices.
> That delta IS the information moat.

---

### T-308 — Intelligence: Infrastructure Appreciation Data File

**Assignee:** Kilo Code | **Priority:** P1 — Phase 2 foundation
**File:** `data/bangalore_infrastructure_timeline.json` (new)

Create a structured JSON file mapping every major BMR infrastructure project to the pincodes it influences, its completion timeline, and its estimated PSF appreciation impact coefficient.

**Schema per project:**
```json
{
  "project_id": "STRR-HOSKOTE",
  "name": "STRR — Hoskote Node (NH-4 intersection)",
  "type": "STRR",
  "status": "functional",
  "completion_date": "2026-06",
  "completion_probability": 0.95,
  "influenced_pincodes": ["562114", "562115"],
  "influence_radius_km": 5,
  "psf_appreciation_on_completion_pct": 25,
  "psf_appreciation_5yr_pct": 60,
  "psf_appreciation_10yr_pct": 120,
  "notes": "Chennai highway intersection; e-commerce logistics hub forming"
}
```

**Projects to seed (minimum viable set — 18 entries):**

STRR nodes (8): Dobbasapete, Doddaballapura, Devanahalli, Hoskote, Attibele/Anekal, Sarjapura, Kanakapura, Ramanagara/Magadi
PRR/BBC (2): Northern stretch (Tumkur Rd → Ballary Rd), Southern stretch
Metro (5): Phase 2A (ORR corridor), Phase 2B (Airport corridor), Yellow Line extension (Bommasandra), Airport Metro (BIAL), Purple Line extension
Airport expansion (1): BIAL Terminal 2 + cargo hub
Industrial corridors (2): Aerospace SEZ Devanahalli, Hoskote Logistics Park

**Done when:** `data/bangalore_infrastructure_timeline.json` exists with ≥18 project entries, each with all required fields. Validate with `python -c "import json; d=json.load(open('data/bangalore_infrastructure_timeline.json')); print(len(d['projects']), 'projects loaded')"`.

---

### T-309 — Intelligence: Appreciation Forecasting Model

**Assignee:** Kilo Code | **Priority:** P1 — depends on T-308
**File:** `utils/appreciation_model.py` (new)

Python module that takes a pincode and returns a structured appreciation forecast by reading the pincode master CSV and infrastructure timeline JSON.

**Interface:**
```python
def get_appreciation_forecast(pincode: str) -> dict:
    """
    Returns:
    {
        "pincode": "562114",
        "area": "Hoskote Town",
        "current_psf_min": 0,
        "current_psf_max": 0,
        "current_land_cr_per_acre_min": 1.0,
        "current_land_cr_per_acre_max": 2.5,
        "investment_tier": "Tier1_Industrial_Growth",
        "water_risk": "Medium",
        "infrastructure_events": [
            {
                "project": "STRR — Hoskote Node",
                "status": "functional",
                "completion_date": "2026-06",
                "psf_impact_on_completion_pct": 25
            }
        ],
        "forecast": {
            "3yr_appreciation_pct": 45,
            "5yr_appreciation_pct": 80,
            "10yr_appreciation_pct": 150,
            "confidence": "medium",
            "primary_driver": "STRR Node operational + NH-4 logistics hub"
        },
        "recommendation": "Strong Buy — logistics land banking window closing",
        "risks": ["GP title risk in rural parcels", "Industrial absorption slow without anchor tenant"]
    }
    """
```

**Forecasting logic:**
- Base appreciation rate: look up zone_type from CSV → use lookup table (Urban Core Apex = 3%/yr, Peri-Urban High Value = 12%/yr, Peripheral Urban = 8%/yr, Rural Speculative = 4%/yr base)
- Infrastructure multiplier: for each infrastructure event affecting the pincode, if status=functional → apply 60% of `psf_appreciation_on_completion_pct` already realised; if Under Construction → apply on completion_date; if Planned → apply with probability-weighted discount
- Water risk penalty: Very_High = -8% on 5yr forecast; High = -4%; Medium = 0%; Low = +2%
- Output 3yr / 5yr / 10yr compounded from base + infrastructure events

**Done when:** `from utils.appreciation_model import get_appreciation_forecast; print(get_appreciation_forecast("562114"))` returns a complete dict with no exceptions. Unit test: `pytest tests/test_appreciation_model.py` with 3 pincode fixtures (one urban, one STRR node, one rural speculative).

---

### T-310 — Intelligence: Wire Forecasting into Analyst Agent

**Assignee:** Cline | **Priority:** P1 — depends on T-309
**File:** `agents/analyst_agent.py`, `crews/market_intel_crew.py`

When the Analyst generates a market brief, enrich it with appreciation forecasts for the 3–5 key pincodes in that market. The analyst agent should receive forecast data as structured context — not ask the model to guess it.

**Implementation:**
1. In `market_intel_crew.py` Stage 3, before creating the analyst task: call `get_appreciation_forecast(pincode)` for each pincode associated with the market (use the pincode master CSV filtered by micro_market matching the market name).
2. Serialize the forecast dicts to a compact JSON string.
3. Inject into analyst task description as: `\n\n## Appreciation Forecasts (pre-computed)\n{json_string}`
4. Analyst task instructions: "Use the pre-computed appreciation forecasts in the context. Do not invent PSF projections — cite the forecast data."

**Done when:** After a Devanahalli pipeline run, the Analyst output section of `logs/crew.log` contains "3yr" and "appreciation" text sourced from forecast data. The intel report saved to `outputs/` contains a PSF trajectory section.

---

### T-311 — Intelligence: Kaveri Transaction Scraper (The Moat)

**Assignee:** Kilo Code | **Priority:** P2 — standalone; no dependency
**File:** `scrapers/kaveri_transaction_scout.py` (new)

Kaveri Online (`kaveri.karnataka.gov.in`) holds actual property registration transaction data — real prices, real buyers, real survey numbers, real dates. This is ground truth vs the listing fiction every competitor uses. The delta between Kaveri transaction price and listing price on any portal IS the information advantage.

**The portal is hard to scrape.** The current `kaveri_karnataka.py` scout targets guidance values (GV). This task targets transaction search (EC — Encumbrance Certificate search / Sale Deed search).

**Research phase first (do not skip):**
1. Open `https://kaverionline.karnataka.gov.in` in a browser with DevTools network tab open.
2. Navigate to: Property Search → Sale Deed → search by locality + date range (last 90 days, Devanahalli).
3. Record: exact POST endpoint URL, payload structure, required cookies/session tokens, response format (HTML table or JSON).
4. Document findings in `scrapers/kaveri_transaction_scout.py` as a comment block at the top before writing any scraping code.

**Target output per transaction:**
```python
{
    "survey_number": "123/4",
    "village": "Devanahalli",
    "taluk": "Devanahalli",
    "registration_date": "2026-04-15",
    "sale_value_lakh": 85.0,
    "area_sqft": 2400,
    "derived_psf": 3541,
    "document_type": "Sale Deed",
    "buyer_type": "individual"
}
```

**Done when:** Script runs against Kaveri portal for Devanahalli (last 90 days) and returns ≥5 real transaction records stored to `kaveri_registrations` table. If portal remains unreachable, document the exact failure mode and propose an alternate endpoint or CPIO RTI fallback strategy.

---

## GATES STATUS

| Gate | Name | Unlocked By | Status |
|------|------|-------------|--------|
| GATE-1 | Pipeline Observability | T-289 + stage events verified in agent_runs | ✅ PASSED (2026-05-28) |
| GATE-2 | Dashboard Smoke Test | T-280+282+283+284+286+293 | ✅ PASSED (2026-05-29) |
| GATE-3 | Auth Hardening | T-296 | ✅ PASSED (T-296 + T-295 done Round 16) |
| GATE-4 | Intel Quality Baseline | T-281+T-287+T-288 | PENDING — T-281 partial |
| GATE-5 | Log Monitor Eliminated | T-292 | ✅ PASSED |
| GATE-6 | Intelligence OS — Appreciation Layer Live | T-308+T-309+T-310 done; Analyst output contains PSF trajectory for at least one market | ✅ PASSED (2026-05-29) |

---

## OPEN BUGS (fix inline if encountered, no task ID needed)

- **Bug 3:** `delay_months` GENERATED COLUMN in `database/schema.sql` may fail on DB wipe + reinit. Move to view-level calculation when hit. Low urgency — DB currently healthy.
- **Kaveri portal:** `kaveri.karnataka.gov.in` consistently unreachable. 7 seeded GV values in use. Medium urgency.
- **RERA Yelahanka/Hebbal:** 8 hardcoded fallback projects. Fix tracked in T-281.
