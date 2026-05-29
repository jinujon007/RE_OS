# RE_OS — Task Briefs
**Stage 3 · 2026-05-29**

This file is the single execution reference for both brains. Each brief gives complete context to perform the task with minimum back-and-forth. Read only the section for your assigned task — the rest is noise.

---

## How to Use This File

> **If you are reading this without first marking your task `IN_PROGRESS` in `TASK_QUEUE.md` — stop. Go do that first. Then come back.**

1. Mark task `IN_PROGRESS` in `TASK_QUEUE.md` (write the file, save it).
2. Find your task ID in this file and jump to that section.
3. Read the brief fully before writing a single line of code.
4. Follow the steps in order. Do not skip.
5. Run the "Done when" checks. All must pass before marking DONE.
6. Write the CHANGELOG.md entry and update TASK_QUEUE.md status to `DONE`.

---

## Operating Standard

Both brains execute at the level of a **senior tech product engineering lead**. That means:

- You understand why the change exists before making it, not just what to change.
- You do not introduce regressions. You check first, change second.
- You do not over-engineer. The smallest correct change wins.
- You do not leave the codebase in a worse state than you found it. If you see a problem adjacent to your task, note it in TASK_QUEUE.md — do not fix it unless it blocks your task.
- You test your own work. "It looks right" is not a done criterion.
- You write one precise CHANGELOG.md entry per task. No summaries of intent — only concrete changes made.

---

## System Context (read once, applies to all tasks)

**Stack:** 5-container Docker Compose — postgres/PostGIS, ollama, redis, agents (Flask :8050), scheduler.
**Pipeline:** 3-stage — Scrape (LLM) → DB Organizer (Python) → Intel (LLM).
**LLM tiers:** HEAVY (Groq → Gemini → NVIDIA → OpenRouter → Ollama), ANALYSIS (Cerebras → Groq → Gemini → NVIDIA → Ollama), LIGHT (Cerebras → Gemma → NVIDIA → Ollama).
**Working dir:** `/app` inside containers. Host mirror: `D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS`.
**Run tests:** `docker compose exec agents pytest tests/ -q` or `pytest tests/ -q` with DB_PASSWORD set.
**Lint:** `ruff check .` and `ruff format --check .` — both must pass clean.
**CHANGELOG format:** `TYPE | file/path | what changed | who | YYYY-MM-DD`

---

---

# T-281 — RERA Scraper: Fix Yelahanka + Hebbal Locality Selectors

**Assigned:** Kilo Code | **Priority:** P0 | **Gate:** GATE-4

## Why

Yelahanka and Hebbal return 8 hardcoded fallback projects instead of live RERA data. Devanahalli works (317 projects from `Bengaluru Rural` district). The RERA portal uses a POST-based DataTables search. The scraper sends a locality string but the portal doesn't recognise it, so it returns the global fallback.

Current state (`scrapers/rera_karnataka.py`): `ALT_SUBDISTRICTS` retry loop already exists — Hebbal tries `Bangalore North`, Yelahanka tries `Bengaluru North`. These still return 0. The raw HTML is logged at WARNING on failure.

## Steps

1. **Reproduce the failure first.** Run a standalone scrape inside Docker and read the raw HTML warning:
   ```bash
   docker compose exec agents python scrapers/rera_karnataka.py --market Yelahanka
   ```
   Find the line `[RERA] Raw HTML logged` in the output. Read the actual HTML to see what field names and option values the portal expects.

2. **Find the correct subdistrict value.** The RERA Karnataka portal (`rera.karnataka.gov.in`) has a locality/subdistrict dropdown. Inspect the network POST payload from a working Devanahalli request to understand the exact field structure. Compare with Yelahanka — the field name may be `taluk`, `locality`, or `subDistrict`. Check `ALT_SUBDISTRICTS` values against the dropdown options visible in the raw HTML.

3. **Update `ALT_SUBDISTRICTS`** in `scrapers/rera_karnataka.py` with the correct values found in step 2. If the field name itself is wrong, fix the POST payload builder too.

4. **Run a live validation:**
   ```bash
   docker compose exec agents python scrapers/rera_karnataka.py --market Yelahanka
   docker compose exec agents python scrapers/rera_karnataka.py --market Hebbal
   ```
   Log the result count.

5. **If the portal is still unreachable** (HTTP 403/timeout, not a selector issue): document the exact HTTP response code, headers, and what was tried in CHANGELOG.md. Do not mark DONE — mark BLOCKED with the finding.

## Done When

- [ ] Yelahanka OR Hebbal returns ≥ 50 live RERA projects (not fallback)
- [ ] The scrape checkpoint file is written with `data_source: portal_scraped` (not `seed_estimated`)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written with exact result counts

---

---

# T-302 — Test Coverage: DBOrganizer

**Assigned:** Cline | **Priority:** P1 | **Gate:** GATE-7

## Why

`DBOrganizer` is the most critical non-LLM component in the pipeline — all RERA, portal, kaveri, developer, and news data flows through it. It currently has zero test coverage. One bad change here corrupts the data layer silently.

## Steps

1. Create `tests/test_db_organizer.py`.

2. Use the real PostgreSQL test DB (DATABASE_URL from env, same as other integration tests). All three tests require the DB to be up — skip gracefully if `DATABASE_URL` is not set:
   ```python
   import pytest, os
   pytestmark = pytest.mark.skipif(
       not os.environ.get("DATABASE_URL"), reason="requires live DB"
   )
   ```

3. **Test 1 — insert then update:**
   - Build 2 valid RERA project dicts with unique `rera_number` values (use `RERA-TEST-001`, `RERA-TEST-002`). Market = `Yelahanka` (already seeded in micro_markets).
   - Call `DBOrganizer().run("Yelahanka", [r1, r2])`.
   - Assert `stats["inserted"] == 2`, `stats["failed"] == 0`.
   - Call `run()` again with identical records.
   - Assert `stats["updated"] == 2`, `stats["inserted"] == 0`.

4. **Test 2 — missing required field is skipped:**
   - Build a record with no `project_name` key.
   - Assert `stats["failed"] == 1` and no exception raised.

5. **Test 3 — SAVEPOINT rollback: bad record doesn't block good ones:**
   - Batch of 3: record 1 valid, record 2 has a malformed `rera_number` that violates the UNIQUE constraint (insert it twice in the batch), record 3 valid.
   - Assert `stats["inserted"] >= 2` (records 1 and 3 inserted), `stats["failed"] >= 1`.

6. **Cleanup:** each test must clean up inserted rows:
   ```python
   conn.execute(text("DELETE FROM rera_projects WHERE rera_number LIKE 'RERA-TEST-%'"))
   ```
   Use a pytest fixture with `yield` + cleanup.

7. Run: `pytest tests/test_db_organizer.py -v`

## Done When

- [ ] `pytest tests/test_db_organizer.py` passes (3 tests, no errors)
- [ ] Test file correctly skips when DATABASE_URL is not set (CI-safe)
- [ ] Coverage report shows `utils/db_organizer.py` coverage improved
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-315 — Board Room: Stuck Session Recovery

**Assigned:** Kilo Code | **Priority:** P1

## Why

`run_board_session()` starts a daemon thread to run dept-head agents. If the gunicorn worker is restarted mid-run (OOM, timeout, deploy), the thread dies but the DB row stays at `status = 'active'` forever. There is no recovery. Sessions pile up as false-actives, confusing the dashboard.

## Steps

1. Open `config/scheduler.py`. Add a new APScheduler job that runs every hour:
   ```python
   def recover_stuck_board_sessions():
       """Set board sessions stuck at 'active' for >30 minutes to 'failed'."""
   ```

2. Inside the function:
   - Get a DB connection via `create_engine(DATABASE_URL).connect()`
   - Execute:
     ```sql
     UPDATE board_sessions
     SET status = 'failed',
         completed_at = NOW()
     WHERE status = 'active'
       AND created_at < NOW() - INTERVAL '30 minutes'
     ```
   - Log: `logger.info(f"[Scheduler] Recovered {rowcount} stuck board sessions")`
   - Close connection.

3. Register the job in the scheduler startup block:
   ```python
   scheduler.add_job(
       recover_stuck_board_sessions,
       "interval", hours=1,
       id="recover_board_sessions",
       replace_existing=True,
   )
   ```

4. Wrap the entire function body in `try/except Exception as e: logger.warning(...)` — this job must be non-fatal.

5. Verify the job appears in `scheduler.get_jobs()` output at startup.

## Done When

- [ ] `config/scheduler.py` has the new job registered
- [ ] Scheduler starts without error (`docker compose up scheduler` logs show the job ID)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-316 — Dockerfile: Remove Duplicate Chromium Install

**Assigned:** Kilo Code | **Priority:** P1

## Why

`Dockerfile` installs Chromium twice: once via `apt-get install chromium chromium-driver` (~200MB) and once via `playwright install chromium` (Playwright-managed binary at `/ms-playwright`). The scrapers use Playwright's binary exclusively — the apt install is dead weight that inflates every image build and every container pull.

## Steps

1. Open `Dockerfile`.

2. Remove `chromium` and `chromium-driver` from the `apt-get install` line. Keep `gcc`, `libpq-dev`, `curl`.

3. `CHROME_BIN` and `CHROMEDRIVER_PATH` env vars point to the apt paths. Remove both env vars — Playwright does not need them and they would point to non-existent binaries after the removal.

4. Verify the build compiles:
   ```bash
   docker build . --tag re_os:test --no-cache
   ```
   The build must succeed. Playwright's own Chromium install (`playwright install chromium`) remains and is the active browser.

5. Verify scrapers still work by running a quick standalone scrape:
   ```bash
   docker compose run --rm agents python scrapers/rera_karnataka.py --market Devanahalli
   ```
   Devanahalli has live RERA data — expect 317 projects or similar.

## Done When

- [ ] `docker build` succeeds without errors
- [ ] `chromium` and `chromium-driver` no longer appear in `apt-get install`
- [ ] `CHROME_BIN` and `CHROMEDRIVER_PATH` removed from Dockerfile
- [ ] Devanahalli scrape returns live projects (not 0 or error)
- [ ] CHANGELOG.md entry written with image size before/after (run `docker images re_os:test` to get size)

---

---

# T-317 — Dashboard: Delete Deprecated `/api/intel` Endpoint

**Assigned:** Cline | **Priority:** P1

## Why

`GET /api/intel` reads intel report files from disk and returns up to 500 chars of content. `GET /api/intel/cards` does the same job properly via a DB query with richer output. The file-read endpoint is slower, redundant, and the dashboard JS now uses `/api/intel/cards` exclusively. Dead endpoints are security surface area.

## Steps

1. Open `dashboard/app.py`.

2. Confirm the dashboard UI (`dashboard/templates/index.html`) does not call `/api/intel` anywhere:
   ```bash
   grep -n "api/intel\"" dashboard/templates/index.html
   ```
   Expected: only `/api/intel/cards` and `/api/intel/download` — no bare `/api/intel`.

3. Delete the `get_intel()` function and its `@app.route("/api/intel")` decorator entirely from `app.py`.

4. Verify the app starts: `python -m py_compile dashboard/app.py` → exit 0.

5. Verify the remaining intel routes still work:
   - `GET /api/intel/cards` — still present
   - `GET /api/intel/download` — still present
   - `GET /api/intel` — should now return 404

## Done When

- [ ] `get_intel()` function deleted from `dashboard/app.py`
- [ ] `GET /api/intel` returns 404
- [ ] `GET /api/intel/cards` and `/api/intel/download` return 200
- [ ] No references to `/api/intel` remain in `index.html` (grep confirms)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-318 — Board Room Engine Pool: Increase to pool_size=5

**Assigned:** Cline | **Priority:** P1

## Why

`crews/board_room.py` `_get_engine()` creates the SQLAlchemy engine with `pool_size=2, max_overflow=0`. A board session runs 4 concurrent dept-head threads plus the main thread — all may need DB connections simultaneously. Pool exhaustion causes `TimeoutError` and a failed session under any real load.

## Steps

1. Open `crews/board_room.py`.

2. Find `_get_engine()`. Change the `create_engine` call:
   ```python
   # Before
   _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=0)
   # After
   _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=2)
   ```

3. That is the entire change. Do not touch anything else in this function.

4. Verify syntax: `python -m py_compile crews/board_room.py` → exit 0.

## Done When

- [ ] `pool_size=5, max_overflow=2` in `_get_engine()`
- [ ] `python -m py_compile crews/board_room.py` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-319 — Dashboard: CORS Headers with Origin Allowlist

**Assigned:** Kilo Code | **Priority:** P2

## Why

The Flask dashboard has no CORS configuration. Any attempt to access it from a different origin (nginx reverse proxy, different port, Obsidian web view) will be silently blocked by the browser. This becomes a blocker the moment anything other than the direct container port is used.

## Steps

1. Add `flask-cors>=4.0.0` to `requirements.txt` under the Dashboard section.

2. Open `dashboard/app.py`. After the `app = Flask(...)` line, add:
   ```python
   from flask_cors import CORS
   _ALLOWED_ORIGINS = [
       o.strip()
       for o in os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "http://localhost:8050").split(",")
       if o.strip()
   ]
   CORS(app, origins=_ALLOWED_ORIGINS)
   ```

3. Add `DASHBOARD_ALLOWED_ORIGINS` to the agents service env block in `docker-compose.yml`:
   ```yaml
   DASHBOARD_ALLOWED_ORIGINS: ${DASHBOARD_ALLOWED_ORIGINS:-http://localhost:8050}
   ```

4. Add `DASHBOARD_ALLOWED_ORIGINS=http://localhost:8050` to `.env.example` with a comment explaining it accepts comma-separated origins.

5. Verify the app starts: `python -m py_compile dashboard/app.py` → exit 0.

## Done When

- [ ] `flask-cors` in `requirements.txt`
- [ ] CORS applied in `app.py` using env-var allowlist
- [ ] `DASHBOARD_ALLOWED_ORIGINS` in docker-compose.yml agents env + `.env.example`
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-320 — `_log_event`: Structured JSON Serialisation

**Assigned:** Kilo Code | **Priority:** P2

## Why

`_log_event()` in `crews/market_intel_crew.py` calls `logger.info(payload)` where `payload` is a Python dict. The loguru text sink stringifies it as `{'key': 'val'}` — not valid JSON, not grep-friendly. Every pipeline event is unreadable in log analysis.

## Steps

1. Open `crews/market_intel_crew.py`. Find `_log_event()`.

2. Change the last line from:
   ```python
   logger.info(payload)
   ```
   to:
   ```python
   logger.info("pipeline_event | {}", json.dumps(payload))
   ```

3. `json` is already imported at module level — no new import needed.

4. Verify: `python -m py_compile crews/market_intel_crew.py` → exit 0.

## Done When

- [ ] `logger.info(payload)` replaced with `logger.info("pipeline_event | {}", json.dumps(payload))`
- [ ] `python -m py_compile crews/market_intel_crew.py` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-321 — Replace `_daily_counts` Direct Import

**Assigned:** Cline | **Priority:** P2

## Why

`crews/market_intel_crew.py` imports `_daily_counts` directly from `config.llm_router`:
```python
from config.llm_router import _exclude, _clear_excluded, _is_excluded, _daily_counts
```
`_daily_counts` is a live mutable dict. Iterating it (`logger.info(f"... {_daily_counts}")`) while another thread is writing to it can raise `RuntimeError: dictionary changed size during iteration`.

The correct approach is to call `get_router_status()` which returns a safe snapshot.

## Steps

1. Open `crews/market_intel_crew.py`.

2. Remove `_daily_counts` from the import line:
   ```python
   # Before
   from config.llm_router import _exclude, _clear_excluded, _is_excluded, _daily_counts
   # After
   from config.llm_router import _exclude, _clear_excluded, _is_excluded, get_router_status
   ```

3. Find the two places in the file where `_daily_counts` is logged:
   ```python
   logger.info(f"[Router] Daily counts: {_daily_counts}")
   ```
   Replace both with:
   ```python
   logger.info("[Router] Daily counts: {}", get_router_status().get("excluded", "n/a"))
   ```

4. Verify: `python -m py_compile crews/market_intel_crew.py` → exit 0.

## Done When

- [ ] `_daily_counts` removed from import
- [ ] Both log call sites updated to use `get_router_status()`
- [ ] `python -m py_compile crews/market_intel_crew.py` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-322 — Remove Unused `superseded_by` FK from `agent_memories`

**Assigned:** Cline | **Priority:** P2

## Why

`agent_memories.superseded_by UUID REFERENCES agent_memories(memory_id)` exists in `schema.sql` and in the Alembic migration but is never set by any code path. It is dead schema — it adds FK overhead, confuses future readers, and implies a feature that does not exist.

## Steps

1. **Alembic migration (new file):** Create `alembic/versions/0005_drop_superseded_by.py`:
   ```python
   """drop unused superseded_by column from agent_memories"""
   revision = "0005_drop_superseded_by"
   down_revision = "0004_..."  # check latest revision in alembic/versions/
   
   from alembic import op
   
   def upgrade():
       op.drop_column("agent_memories", "superseded_by")
   
   def downgrade():
       op.add_column(
           "agent_memories",
           sa.Column("superseded_by", sa.UUID(), nullable=True),
       )
   ```
   Fill in `down_revision` by checking what the current head migration ID is in `alembic/versions/`.

2. **Remove from `schema.sql`**: Delete the `superseded_by UUID REFERENCES agent_memories(memory_id),` line from the `CREATE TABLE IF NOT EXISTS agent_memories` block.

3. **Remove from `models.py`** if present: delete the `superseded_by` column definition from the `AgentMemory` ORM model.

4. Do NOT apply the migration to the live DB — that is done via `alembic upgrade head` on next restart (T-324 handles this).

5. Verify: `python -m py_compile alembic/versions/0005_drop_superseded_by.py` → exit 0.

## Done When

- [ ] Migration file created with correct `down_revision`
- [ ] `superseded_by` removed from `schema.sql`
- [ ] `superseded_by` removed from `models.py` (if present)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-323 — `v_developer_scorecard`: Deterministic `STRING_AGG`

**Assigned:** Kilo Code | **Priority:** P2

## Why

`v_developer_scorecard` uses `STRING_AGG(DISTINCT mm.name, ', ')` with no `ORDER BY` clause. PostgreSQL does not guarantee ordering for `DISTINCT` aggregates without an explicit `ORDER BY`. Output varies across query plans and PostgreSQL versions — makes test assertions on this field brittle.

## Steps

1. Open `database/schema.sql`. Find `v_developer_scorecard`.

2. Change:
   ```sql
   STRING_AGG(DISTINCT mm.name, ', ') AS markets_active_in
   ```
   to:
   ```sql
   STRING_AGG(DISTINCT mm.name, ', ' ORDER BY mm.name) AS markets_active_in
   ```

3. Apply the same fix to any Alembic migration that recreates this view. Search:
   ```bash
   grep -r "STRING_AGG" alembic/
   ```
   Update any matches.

4. The view is `CREATE VIEW` not `CREATE TABLE` — no migration needed for the schema change itself (views are recreated on DB init). But if a migration creates or replaces the view, update it there too.

## Done When

- [ ] `ORDER BY mm.name` added inside `STRING_AGG(DISTINCT ...)` in `schema.sql`
- [ ] All Alembic migration copies of this view updated (if any)
- [ ] `ruff check .` passes (SQL files are not checked by ruff, but Python migration files are)
- [ ] CHANGELOG.md entry written

---

---

# T-324 — Alembic Upgrade on Container Startup

**Assigned:** Kilo Code | **Priority:** P2

## Why

`schema.sql` initialises a fresh DB but Alembic migrations (T-322's new `0005_drop_superseded_by` and others) are never applied automatically. Each time a new migration is added, it only runs if someone manually runs `alembic upgrade head`. This is a production reliability gap — deploys silently run on stale schema.

## Steps

1. Open `docker-compose.yml`. Find the `agents` service `command` block:
   ```yaml
   command: >
     gunicorn dashboard.app:app ...
   ```

2. Change it to run alembic first, then gunicorn:
   ```yaml
   command: >
     sh -c "alembic upgrade head &&
            gunicorn dashboard.app:app
            --bind 0.0.0.0:8050
            --workers 1
            --threads 8
            --timeout 120
            --access-logfile -
            --error-logfile -"
   ```

3. `alembic` is already in `requirements.txt`. The `alembic.ini` and `env.py` exist and read `DATABASE_URL` from the environment.

4. **Critical:** `alembic upgrade head` must complete before gunicorn starts. The `sh -c "... && ..."` pattern enforces this — if alembic fails, gunicorn does not start (fail fast).

5. Verify the change parses correctly:
   ```bash
   docker compose config --quiet
   ```

6. Do NOT change the scheduler command — it does not serve the DB-backed API.

## Done When

- [ ] `alembic upgrade head` runs before gunicorn in agents service command
- [ ] `docker compose config --quiet` passes (no YAML parse error)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written
- [ ] Note: full verification (container start + alembic log output) happens on next `docker compose up`

---

---

# T-325 — CI: Add pip-audit for CVE Scanning

**Assigned:** Kilo Code | **Priority:** P1 | **Gate:** GATE-8

## Why

The CI pipeline (`.github/workflows/ci.yml`) runs py_compile, ruff, and pytest but has no CVE scan. Any dependency with a known vulnerability ships silently. pip-audit checks installed packages against PyPI advisory database in seconds — it's a pure CI addition with zero runtime footprint.

## Steps

1. Open `.github/workflows/ci.yml`. Find the `steps:` block in the main job.

2. After the `pip install -r requirements.txt` step and before the `ruff check .` step, add:
   ```yaml
   - name: pip-audit (CVE scan)
     run: pip install pip-audit && pip-audit --requirement requirements.txt --ignore-vuln PYSEC-2022-42969
   ```
   The `--ignore-vuln` flag is a safety valve for known false-positives. Start without it — only add it if a specific advisory fires that is documented as a false positive.

3. Simpler version if the above is too verbose for the workflow style — just add `pip-audit` to the install step and run it:
   ```yaml
   - name: pip-audit (CVE scan)
     run: pip-audit -r requirements.txt
   ```

4. Verify the YAML parses cleanly — copy the CI file to a temp location and run:
   ```bash
   python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
   ```

5. Do NOT add pip-audit to `requirements.txt` — it is a dev/CI-only tool, not a runtime dependency. Install it inline in the workflow step only.

## Done When

- [ ] `pip-audit -r requirements.txt` step present in `.github/workflows/ci.yml`
- [ ] YAML parses without error (`python -c "import yaml..."`)
- [ ] `ruff check .` passes (Python files, not YAML)
- [ ] CHANGELOG.md entry written

---

---

# T-326 — Makefile: Add `make ci` Target

**Assigned:** Kilo Code | **Priority:** P2 | **Gate:** GATE-8

## Why

`make format` exists but there is no `make ci` — the only way to replicate CI locally is to manually run three commands in sequence. Every developer touching this project pays this tax. A `make ci` target that mirrors the CI steps exactly eliminates the gap and removes the excuse not to run checks before pushing.

## Steps

1. Open `Makefile` (project root). Find the existing `format` and any other targets.

2. Add the following targets below the existing ones:

   ```makefile
   .PHONY: ci lint test

   lint:
   	ruff check .
   	ruff format --check .

   test:
   	pytest tests/ -q

   ci: lint test
   	@echo "CI checks passed"
   ```

3. The `ci` target chains `lint` then `test`. If either fails, `make ci` exits non-zero — same semantics as the GitHub Actions workflow.

4. Do NOT add `pip-audit` to this target — pip-audit is CI-only (not installed locally unless explicitly set up). Keeping `make ci` to ruff + pytest makes it zero-friction for local use.

5. Verify the Makefile parses:
   ```bash
   make ci --dry-run
   ```
   Expected: prints the commands it would run, exits 0.

## Done When

- [ ] `make ci` runs `ruff check . && ruff format --check . && pytest tests/ -q`
- [ ] `make lint` and `make test` exist as standalone targets
- [ ] `make ci --dry-run` exits 0
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-327 — Fix SQLAlchemy Pool Size in agent_memory.py + market_intel_crew.py

**Assigned:** Kilo Code | **Priority:** P2

## Why

Three files create SQLAlchemy engines. `db_organizer.py` was fixed to `pool_size=5, max_overflow=2` (R21). The other two were not:

- `utils/agent_memory.py` line ~34: `pool_size=2, max_overflow=0`
- `crews/market_intel_crew.py` line ~114: `pool_size=2, max_overflow=0`

`market_intel_crew.py` runs the 3-stage pipeline. During Stage 3, the CEO agent, Analyst agent, and the organizer engine all compete for DB connections. Pool of 2 with no overflow means the third concurrent access blocks until one releases — adds latency and risks TimeoutError on slow DB operations. `agent_memory` is read + written during every scraper iteration — pool of 2 is a bottleneck under parallel market runs.

## Steps

1. Open `utils/agent_memory.py`. Find the line:
   ```python
   _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=0)
   ```
   Change to:
   ```python
   _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=2)
   ```

2. Open `crews/market_intel_crew.py`. Find the equivalent `create_engine` call (around line 114). Apply the same change: `pool_size=5, max_overflow=2`.

3. Verify both files compile:
   ```bash
   python -m py_compile utils/agent_memory.py
   python -m py_compile crews/market_intel_crew.py
   ```

4. Run tests to confirm nothing broke:
   ```bash
   pytest tests/ -q
   ```

## Done When

- [ ] `utils/agent_memory.py` has `pool_size=5, max_overflow=2`
- [ ] `crews/market_intel_crew.py` has `pool_size=5, max_overflow=2`
- [ ] Both `py_compile` checks pass
- [ ] `pytest tests/ -q` exits 0
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written (one entry, both files)

---

---

# T-328 — Dashboard Route Tests: Smoke Coverage for 5 Key Endpoints

**Assigned:** Cline | **Priority:** P1 | **Gate:** GATE-8

## Why

The auth fix (before_request) and rate limiting added in R21 have zero test coverage. A regression that re-opens the pipeline trigger to unauthenticated requests would ship silently. This is the "security fix untested" finding from the May-19 audit.

## Steps

1. Create `tests/test_dashboard_routes.py`.

2. Use Flask's test client — no real DB or Docker needed:
   ```python
   import pytest
   import sys, os
   sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

   @pytest.fixture
   def client():
       from dashboard.app import app
       app.config["TESTING"] = True
       with app.test_client() as c:
           yield c
   ```

3. **Test 1 — /api/health returns 200 without auth key:**
   ```python
   def test_health_no_auth(client):
       r = client.get("/api/health")
       assert r.status_code == 200
   ```

4. **Test 2 — /api/run/<market> returns 401 without key when DASHBOARD_API_KEY is set:**
   ```python
   def test_run_trigger_requires_auth(client, monkeypatch):
       monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
       r = client.post("/api/run/yelahanka")
       assert r.status_code == 401
   ```

5. **Test 3 — /api/run/<market> returns 200-level (not 401) with correct key:**
   ```python
   def test_run_trigger_with_auth(client, monkeypatch):
       monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
       r = client.post("/api/run/yelahanka", headers={"X-API-Key": "secret"})
       assert r.status_code in (200, 202, 409)  # running/accepted/already running
   ```

6. **Test 4 — /api/db/state returns 200 without auth (read-only):**
   ```python
   def test_db_state_no_auth(client):
       r = client.get("/api/db/state")
       assert r.status_code in (200, 500)  # 500 ok if DB not running in CI
   ```

7. **Test 5 — /api/run with invalid market returns 400:**
   ```python
   def test_run_invalid_market(client, monkeypatch):
       monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
       r = client.post("/api/run/fakecity", headers={"X-API-Key": "secret"})
       assert r.status_code == 400
   ```

8. Run: `pytest tests/test_dashboard_routes.py -v`

**Note:** Tests 3 and 5 may start a subprocess — confirm the route's MARKET_CANONICAL check fires before any Popen call. If it does (it should), no real pipeline runs in tests.

## Done When

- [ ] `pytest tests/test_dashboard_routes.py` passes all 5 tests
- [ ] Test 2 confirms 401 when key is set but not provided
- [ ] Test 3 confirms auth gates pass correctly
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-329 — db_organizer: Validate data_source Against Allowed Values

**Assigned:** Cline | **Priority:** P2

## Why

The `rera_projects` table has a `data_source` CHECK constraint allowing only `{'portal_scraped', 'seed_estimated', 'api_fetched'}`. The organizer writes this field from scraper output without validating it first. A scraper returning an unexpected string (e.g. `"playwright_timeout"` or `"unknown"`) causes a silent SAVEPOINT rollback — the record is dropped with no error propagation to the operator.

## Steps

1. Open `utils/db_organizer.py`. Find `_upsert_rera_project()` (or equivalent upsert method for RERA records).

2. At the top of the method, before the INSERT, add validation:
   ```python
   VALID_DATA_SOURCES = {"portal_scraped", "seed_estimated", "api_fetched"}
   data_source = record.get("data_source", "seed_estimated")
   if data_source not in VALID_DATA_SOURCES:
       logger.warning(
           f"[Organizer] Invalid data_source '{data_source}' — defaulting to 'seed_estimated'"
       )
       data_source = "seed_estimated"
   ```

3. Use the validated `data_source` local variable (not `record["data_source"]`) in the INSERT statement.

4. Add a corresponding test case in `tests/test_db_organizer.py` (which T-302 creates):
   - Build a record with `data_source = "playwright_timeout"` — an invalid value.
   - After `DBOrganizer().run(...)`, the record should be inserted with `data_source = 'seed_estimated'`.
   - Query the row to confirm.

   If T-302 is not yet done, add a standalone test function in a new file `tests/test_db_organizer_validation.py` with the same DB-skip guard.

5. Run: `pytest tests/ -q`

## Done When

- [ ] `data_source` validated against `VALID_DATA_SOURCES` before INSERT
- [ ] Invalid values log a warning and fall back to `seed_estimated`
- [ ] Test confirms fallback behaviour
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-330 — Remove Dead sys.path.append() Calls Across All Modules

**Assigned:** Kilo Code | **Priority:** P1

## Why

`PYTHONPATH: /app` was added to both `agents` and `scheduler` services in docker-compose.yml (R21). Every `sys.path.append(os.path.dirname(...))` call in the codebase is now dead code that silently does nothing inside containers. It adds noise, misleads readers into thinking path manipulation is needed, and remains as a landmine if PYTHONPATH is ever mis-set.

Affected files (13):
- `crews/market_intel_crew.py`
- `config/llm_router.py`
- `config/scheduler.py`
- `config/run_logger.py`
- `scrapers/kaveri_karnataka.py`
- `scrapers/rera_karnataka.py`
- `scrapers/developer_scout.py`
- `scrapers/rera_detail_scout.py`
- `scrapers/portal_scout.py`
- `scrapers/news_scout.py`
- `scrapers/listings_scraper.py`
- `agents/scraper_agent.py`
- `agents/analyst_agent.py`
- `agents/parser_agent.py`
- `agents/ceo_agent.py`
- `utils/db_organizer.py`

## Steps

1. Grep to confirm the full list of affected files:
   ```bash
   grep -rn "sys.path.append" . --include="*.py" | grep -v "__pycache__"
   ```

2. For each file: remove the `import sys`, `import os` (only if they are used solely for the path append — check other uses first), and the `sys.path.append(...)` line.

   **Critical:** `import os` and `import sys` are often used elsewhere in the same file. Only remove the import if the ENTIRE file has no other use of `sys` or `os`. If in doubt, keep the import and only remove the `sys.path.append(...)` call.

3. For standalone scripts (files with `if __name__ == "__main__":` blocks that run directly outside Docker), keep the sys.path.append — those scripts may be run from host without PYTHONPATH set. Check each file's `__main__` block.

   Rule: if the file is **only** run inside the container (crews, agents, scrapers invoked via `docker compose exec`), remove. If it has a standalone run mode used from the host, keep with a comment explaining why.

4. After all removals, run:
   ```bash
   python -m py_compile crews/market_intel_crew.py
   python -m py_compile config/llm_router.py
   python -m py_compile config/scheduler.py
   ```
   And for each modified file.

5. Run the test suite:
   ```bash
   pytest tests/ -q
   ```

## Done When

- [ ] All `sys.path.append(os.path.dirname(...))` calls removed from container-only files
- [ ] `import sys` / `import os` removed only where they had no other use
- [ ] All modified files pass `py_compile`
- [ ] `pytest tests/ -q` exits 0
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written listing the files changed

---

---

# T-331 — Fix Scheduler Engine Leak: Module-Level Singleton for DB Connections

**Assigned:** Kilo Code | **Priority:** P1

## Why

`config/scheduler.py` creates a **fresh `create_engine()` call inside each job function** — `run_market_snapshot()` at line ~104 and `recover_stuck_board_sessions()` at line ~164. Each job fires on a schedule: market snapshots daily, board session recovery every hour. Every call creates a new SQLAlchemy engine with its own connection pool, uses it once, and **never disposes it**. Connection pools accumulate in memory for the lifetime of the scheduler process — this is a classic resource leak.

Pattern in scheduler today:
```python
def run_market_snapshot():
    engine = create_engine(DATABASE_URL)  # new pool every call
    with engine.begin() as conn:
        ...  # engine never disposed
```

## Steps

1. Open `config/scheduler.py`. Add a module-level engine singleton after the imports:
   ```python
   from sqlalchemy import create_engine, text
   from config.settings import DATABASE_URL

   _scheduler_engine = None
   _scheduler_engine_lock = __import__("threading").Lock()

   def _get_scheduler_engine():
       global _scheduler_engine
       if _scheduler_engine is None:
           with _scheduler_engine_lock:
               if _scheduler_engine is None:
                   _scheduler_engine = create_engine(
                       DATABASE_URL,
                       pool_pre_ping=True,
                       pool_size=3,
                       max_overflow=1,
                   )
       return _scheduler_engine
   ```

2. Remove the inline `create_engine` calls from `run_market_snapshot()` and `recover_stuck_board_sessions()`. Replace with:
   ```python
   engine = _get_scheduler_engine()
   ```

3. The `with engine.begin() as conn:` pattern remains unchanged — it handles connection acquire/release. Only the engine creation changes.

4. Remove the local `from sqlalchemy import create_engine, text` inside the job functions — move them to the module-level import block if not already there.

5. Verify: `python -m py_compile config/scheduler.py` → exit 0.

## Done When

- [ ] Module-level `_get_scheduler_engine()` singleton added
- [ ] `run_market_snapshot()` uses `_get_scheduler_engine()` — no inline `create_engine`
- [ ] `recover_stuck_board_sessions()` uses `_get_scheduler_engine()` — no inline `create_engine`
- [ ] `ruff check .` passes
- [ ] `python -m py_compile config/scheduler.py` passes
- [ ] CHANGELOG.md entry written

---

---

# T-332 — Gunicorn: Add --max-requests Flags to Prevent Memory Bloat

**Assigned:** Kilo Code | **Priority:** P2

## Why

The agents container runs gunicorn with `--workers 1 --threads 8`. A single long-running worker process accumulates memory over time — each request imports, caches, and allocates objects that are never freed (Python's GC is generational, not real-time). Without `--max-requests`, the worker runs forever and memory grows unbounded. `--max-requests 500` restarts the worker after 500 requests; `--max-requests-jitter 50` adds randomness so restarts don't all hit at once during traffic spikes. The restart is graceful — in-flight requests finish before the worker cycles.

## Steps

1. Open `docker-compose.yml`. Find the agents service `command` block (which after T-324 starts with `alembic upgrade head &&`).

2. Add `--max-requests 500` and `--max-requests-jitter 50` to the gunicorn flags:
   ```yaml
   command: >
     sh -c "alembic upgrade head &&
            gunicorn dashboard.app:app
            --bind 0.0.0.0:8050
            --workers 1
            --threads 8
            --timeout 120
            --max-requests 500
            --max-requests-jitter 50
            --access-logfile -
            --error-logfile -"
   ```

   If T-324 is not yet done (alembic prefix not present), add to the existing gunicorn command line without the `sh -c` wrapper.

3. Verify YAML parses:
   ```bash
   docker compose config --quiet
   ```

## Done When

- [ ] `--max-requests 500 --max-requests-jitter 50` present in agents gunicorn command
- [ ] `docker compose config --quiet` passes
- [ ] CHANGELOG.md entry written

---

---

# T-333 — Flask after_request: Add HTTP Security Headers

**Assigned:** Kilo Code | **Priority:** P2

## Why

The dashboard exposes a Flask API at port 8050. Without security headers, browsers have no instructions on how to handle the response — content sniffing is enabled, the page can be framed by any origin, and referrer information leaks to third-party resources. These are OWASP-standard headers that take one `after_request` block to add and immediately improve the Security audit score.

## Steps

1. Open `dashboard/app.py`. After the `limiter = Limiter(...)` block, add:
   ```python
   @app.after_request
   def _add_security_headers(response):
       response.headers["X-Content-Type-Options"] = "nosniff"
       response.headers["X-Frame-Options"] = "DENY"
       response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
       response.headers["X-XSS-Protection"] = "0"  # modern browsers: disable legacy XSS filter
       return response
   ```

   Place this **before** the `before_request` function so it's easy to find alongside other request lifecycle hooks.

2. `X-XSS-Protection: 0` is intentional — the legacy XSS filter in old browsers can be exploited; modern security guidance is to disable it and rely on CSP instead.

3. Verify syntax: `python -m py_compile dashboard/app.py` → exit 0.

4. Quick smoke test — start the app locally or in Docker and check a response header:
   ```bash
   curl -I http://localhost:8050/api/health
   ```
   Expect `X-Content-Type-Options: nosniff` in the output.

## Done When

- [ ] `_add_security_headers` after_request hook added to `dashboard/app.py`
- [ ] All four headers present: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `X-XSS-Protection`
- [ ] `python -m py_compile dashboard/app.py` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-334 — Update .env.example with Keys Added Since Last Review

**Assigned:** Kilo Code | **Priority:** P2

## Why

`.env.example` is the deployment contract — a new operator copies it to `.env` and fills in keys. Two keys have been added since the last review that are missing from `.env.example`:
1. `DASHBOARD_ALLOWED_ORIGINS` — added by T-319 (Flask-CORS allowlist)
2. `DASHBOARD_API_KEY_PREV` — used in zero-downtime key rotation (T-250), already in docker-compose but not in `.env.example`

A missing key in `.env.example` means the first time anyone deploys, CORS silently fails or key rotation is undocumented.

## Steps

1. Open `.env.example`. Find the `DASHBOARD_API_KEY` line.

2. Add below it:
   ```bash
   # Zero-downtime key rotation: set OLD_KEY here while rotating to new DASHBOARD_API_KEY.
   # Both keys will be accepted simultaneously. Remove PREV once clients have migrated.
   DASHBOARD_API_KEY_PREV=

   # CORS allowlist for dashboard JS clients. Comma-separated origins.
   # Accepts: http://localhost:8050 (default), or your nginx/proxy origin.
   DASHBOARD_ALLOWED_ORIGINS=http://localhost:8050
   ```

3. Scan for any other env vars referenced in docker-compose.yml that are not in `.env.example`:
   ```bash
   grep -o '\${[A-Z_]*' docker-compose.yml | tr -d '${' | sort -u
   ```
   Cross-check against `.env.example` keys. Add any missing ones with a comment.

4. Verify `.env.example` is committed and `.env` is in `.gitignore`:
   ```bash
   grep "^\.env$" .gitignore
   ```

## Done When

- [ ] `DASHBOARD_API_KEY_PREV` added to `.env.example` with rotation instructions
- [ ] `DASHBOARD_ALLOWED_ORIGINS` added to `.env.example` with comment
- [ ] All docker-compose `${VAR}` references covered in `.env.example`
- [ ] `.env` confirmed in `.gitignore`
- [ ] CHANGELOG.md entry written

---

---

# T-335 — GitHub PR Template

**Assigned:** Kilo Code | **Priority:** P3

## Why

Every PR merged into this repo right now requires the author to manually decide what context to provide. A PR template takes 10 minutes to write and enforces: what changed, why, how it was tested, and whether CHANGELOG.md was updated. It reduces review time and prevents "fixed thing" PRs from being merged with no audit trail.

## Steps

1. Create `.github/pull_request_template.md`:
   ```markdown
   ## What changed
   <!-- One paragraph. What does this PR do? -->

   ## Why
   <!-- What problem does it solve? Link to task ID (e.g. T-281). -->

   ## How tested
   <!-- What commands did you run? What did you verify? -->
   - [ ] `ruff check .` passes
   - [ ] `pytest tests/ -q` passes
   - [ ] CHANGELOG.md entry written

   ## Score impact
   <!-- Which audit dimension does this improve? Repo Health / Security / Prod Readiness / Scalability / Maintainability / GitHub -->
   ```

2. Commit the file. GitHub automatically picks up `.github/pull_request_template.md` — no config needed.

3. Verify the file is valid markdown: `python -c "open('.github/pull_request_template.md').read()"` → no error.

## Done When

- [ ] `.github/pull_request_template.md` created
- [ ] Checklist includes ruff, pytest, CHANGELOG
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-336 — Add detect-secrets Baseline to CI

**Assigned:** Kilo Code | **Priority:** P3

## Why

There is no CI check for accidentally committed secrets. A developer editing `.env.example`, a scraper, or a config file could introduce a real API key. `detect-secrets` is lightweight, runs in CI, and maintains a `.secrets.baseline` file that explicitly marks false positives — so it fails only on genuinely new secrets.

## Steps

1. Add to `.github/workflows/ci.yml`, before the ruff step:
   ```yaml
   - name: detect-secrets scan
     run: |
       pip install detect-secrets
       detect-secrets scan --baseline .secrets.baseline
       detect-secrets audit .secrets.baseline --report --fail-on-unaudited
   ```

2. Generate the initial baseline on the current codebase:
   ```bash
   pip install detect-secrets
   detect-secrets scan > .secrets.baseline
   ```
   Then review the baseline: `detect-secrets audit .secrets.baseline` — mark any false positives (like `.env.example` placeholder values) as not-a-secret.

3. Commit `.secrets.baseline` — this is the approved set of "known patterns that look like secrets but aren't."

4. The CI step will fail if any new secret pattern is found that isn't in the baseline. Developers add new false positives with `detect-secrets scan --baseline .secrets.baseline` and re-commit.

## Done When

- [ ] `.secrets.baseline` generated and committed
- [ ] `detect-secrets scan` step added to CI workflow
- [ ] YAML parses cleanly
- [ ] CHANGELOG.md entry written

---

---

# T-337 — Extract Shared DB Engine Factory to utils/db.py

**Assigned:** Cline | **Priority:** P1

## Why

`create_engine(DATABASE_URL, ...)` is called in at least 8 files with inconsistent pool settings:
- `crews/board_room.py` — `pool_size=2, max_overflow=0` (wrong, needs T-318 fix)
- `utils/agent_memory.py` — `pool_size=2, max_overflow=0` (wrong, needs T-327 fix)
- `crews/market_intel_crew.py` — `pool_size=2, max_overflow=0` (wrong, needs T-327 fix)
- `agents/analyst_agent.py` — NO pool settings at all (SQLAlchemy defaults — unpredictable)
- `config/scheduler.py` — `create_engine(DATABASE_URL)` inline per job call (needs T-331 fix)
- `scrapers/kaveri_transaction_scout.py` — no pool settings
- `alembic/env.py` — `NullPool` (correct for migrations — do NOT change this one)

The fix for each file is the same: `pool_pre_ping=True, pool_size=5, max_overflow=2`. This should be a single function.

## Steps

1. Create `utils/db.py`:
   ```python
   """Shared SQLAlchemy engine factory for RE_OS."""
   import threading
   from sqlalchemy import create_engine
   from config.settings import DATABASE_URL

   _engine = None
   _lock = threading.Lock()


   def get_engine(pool_size: int = 5, max_overflow: int = 2):
       """Return the shared SQLAlchemy engine. Thread-safe singleton."""
       global _engine
       if _engine is None:
           with _lock:
               if _engine is None:
                   _engine = create_engine(
                       DATABASE_URL,
                       pool_pre_ping=True,
                       pool_size=pool_size,
                       max_overflow=max_overflow,
                   )
       return _engine
   ```

2. Replace `create_engine(...)` in the following files with `from utils.db import get_engine` + `get_engine()`:
   - `agents/analyst_agent.py` — `return create_engine(DATABASE_URL)` → `return get_engine()`
   - `scrapers/kaveri_transaction_scout.py` — inline `create_engine` → `get_engine()`

   **Do NOT replace in:**
   - `alembic/env.py` — NullPool is correct for Alembic (single-use migration connection, no pool)
   - `utils/agent_memory.py` — already has its own singleton; T-327 fixes pool size; leave for now unless combining cleanly
   - `crews/board_room.py` — same; T-318 fixes it; has own singleton; leave
   - `config/scheduler.py` — T-331 adds its own singleton with pool_size=3 (scheduler jobs need fewer connections)

3. The two immediate replacements (analyst + kaveri) are the safest — they have no existing singleton and use wrong pool config.

4. Add `utils/db.py` to the test suite — minimal test: `from utils.db import get_engine; e = get_engine(); assert e is not None`.

5. Run: `pytest tests/ -q` and `ruff check .`

## Done When

- [ ] `utils/db.py` created with `get_engine()` singleton
- [ ] `analyst_agent.py` uses `get_engine()`
- [ ] `kaveri_transaction_scout.py` uses `get_engine()`
- [ ] `alembic/env.py` unchanged (NullPool stays)
- [ ] `pytest tests/ -q` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-338 — Add pytest Markers: unit vs integration

**Assigned:** Cline | **Priority:** P1

## Why

All current tests hit the live PostgreSQL DB — `pytest tests/ -q` fails in CI when `DATABASE_URL` is not set. This means the full test suite can only run in Docker or with a local Postgres instance. Pure logic tests (validator, checkpointer, llm_router routing, crew helper functions) do not need a DB — they should run in every environment including a plain `pip install` without Docker.

Adding `unit` / `integration` markers allows:
- `pytest -m unit` — runs in seconds, no DB, works in any CI environment
- `pytest -m integration` — requires live DB, run in Docker only

## Steps

1. Open `pytest.ini` (or `pyproject.toml` `[tool.pytest.ini_options]`). Add:
   ```ini
   [pytest]
   markers =
       unit: pure Python, no DB, no network
       integration: requires live PostgreSQL DB (DATABASE_URL must be set)
   ```

2. Add `@pytest.mark.unit` to tests that need no DB:
   - `tests/test_validator.py` — all tests
   - `tests/test_checkpointer.py` — all tests
   - `tests/test_llm_router.py` — all tests
   - `tests/test_crew_helpers.py` — all tests
   - `tests/test_intel_output.py` — all tests

3. Add `@pytest.mark.integration` to tests that require a live DB:
   - `tests/test_db_organizer.py` (when T-302 is done)
   - `tests/test_board_room.py` — if any tests hit the DB (check and mark those individually)
   - `tests/test_dashboard_routes.py` (when T-328 is done) — routes that call DB paths

4. Update `.github/workflows/ci.yml`: change the pytest step to run only unit tests (no DB available in CI):
   ```yaml
   - name: pytest (unit tests only)
     run: pytest tests/ -q -m unit
   ```

5. Keep the full `pytest tests/ -q` command in `TASK_BRIEFS.md` "done when" sections — that's the Docker-local verification command.

## Done When

- [ ] `pytest.ini` (or pyproject.toml) has `unit` and `integration` markers defined
- [ ] All DB-free test files marked `@pytest.mark.unit`
- [ ] All DB-dependent test files marked `@pytest.mark.integration`
- [ ] `.github/workflows/ci.yml` runs `pytest -m unit` (no DB in CI)
- [ ] `pytest -m unit` passes with zero warnings about unknown markers
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-339 — Fix analyst_agent.py Engine: Missing Pool Settings

**Assigned:** Cline | **Priority:** P2

## Why

`agents/analyst_agent.py` has:
```python
return create_engine(DATABASE_URL)
```
No `pool_pre_ping`, no `pool_size`, no `max_overflow`. SQLAlchemy defaults give `pool_size=5` but no pre-ping — meaning stale connections from the pool silently fail on first use after a DB restart, and the agent throws an `OperationalError` mid-analysis. This task is separate from T-337 (which introduces the shared factory) because the analyst agent may need to stay at its own pool for isolation during concurrent board room sessions.

## Steps

1. Open `agents/analyst_agent.py`. Find the `create_engine(DATABASE_URL)` call (around line 22).

2. If T-337 is already done and `utils/db.py` exists:
   ```python
   from utils.db import get_engine
   # Replace the function return:
   return get_engine()
   ```

3. If T-337 is NOT done yet, apply the settings directly:
   ```python
   return create_engine(
       DATABASE_URL,
       pool_pre_ping=True,
       pool_size=5,
       max_overflow=2,
   )
   ```

4. Verify: `python -m py_compile agents/analyst_agent.py` → exit 0.

5. Run: `pytest tests/ -q`

## Done When

- [ ] `analyst_agent.py` engine has `pool_pre_ping=True, pool_size=5, max_overflow=2`
- [ ] `py_compile` passes
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-340 — Add last_scraped_at to micro_markets + Wire into db_organizer

**Assigned:** Cline | **Priority:** P2

## Why

There is no way to know how fresh the data is for any market. A user looking at 317 Devanahalli projects has no idea if that data is from today or 3 weeks ago. `last_scraped_at TIMESTAMPTZ` on `micro_markets` is a single field that answers "when did we last successfully scrape this market?" — and feeds into a future "data freshness" warning in the dashboard and CEO brief.

## Steps

1. **Alembic migration:** Create `alembic/versions/0006_add_last_scraped_at.py`:
   ```python
   """add last_scraped_at to micro_markets"""
   revision = "0006_add_last_scraped_at"
   down_revision = "0005_drop_superseded_by"  # or current head — check alembic/versions/

   from alembic import op
   import sqlalchemy as sa

   def upgrade():
       op.add_column(
           "micro_markets",
           sa.Column("last_scraped_at", sa.TIMESTAMP(timezone=True), nullable=True),
       )

   def downgrade():
       op.drop_column("micro_markets", "last_scraped_at")
   ```
   Fill in the correct `down_revision` by checking the current head in `alembic/versions/`.

2. **schema.sql:** Add `last_scraped_at TIMESTAMPTZ` to the `micro_markets` table definition (after the last existing column, before the closing `)`).

3. **db_organizer.py:** At the end of a successful RERA or portal upsert batch for a market, update `last_scraped_at`:
   ```python
   conn.execute(
       text("""
       UPDATE micro_markets
       SET last_scraped_at = NOW()
       WHERE name ILIKE :market
       """),
       {"market": market}
   )
   ```
   Place this inside the existing transaction block — after the batch upsert, within the same commit.

4. **models.py** (if it exists and has a `MicroMarket` ORM model): add `last_scraped_at = Column(TIMESTAMP(timezone=True))`.

5. Run: `pytest tests/ -q` — confirm no test regression.

## Done When

- [ ] Alembic migration `0006_add_last_scraped_at.py` created with correct `down_revision`
- [ ] `schema.sql` updated with `last_scraped_at TIMESTAMPTZ`
- [ ] `db_organizer.py` updates `last_scraped_at` after each successful market scrape
- [ ] `models.py` updated (if it has a MicroMarket model)
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

---

# T-341 — v_active_projects: NULLIF Guard on absorption_pct Division

**Assigned:** Cline | **Priority:** P2

## Why

`v_active_projects` and `v_market_brief` compute absorption rates involving division. If `total_units = 0` (a project row with no unit count — possible from partial RERA data), PostgreSQL raises `division by zero` and the entire view query fails. This crashes `GET /api/db/state` and `GET /api/intel/cards` silently.

## Steps

1. Open `database/schema.sql`. Find the `absorption_pct` calculation in `v_active_projects` and `v_market_brief`.

2. Wrap the divisor in `NULLIF(..., 0)`:
   ```sql
   -- Before
   ROUND((sold_units::float / total_units) * 100, 1) AS absorption_pct

   -- After
   ROUND((sold_units::float / NULLIF(total_units, 0)) * 100, 1) AS absorption_pct
   ```
   `NULLIF(x, 0)` returns NULL when `total_units = 0` — the entire expression evaluates to NULL instead of raising an exception. The dashboard handles NULL gracefully (shows "—").

3. Apply the same fix to any Alembic migration that recreates these views:
   ```bash
   grep -rn "absorption_pct" alembic/
   ```
   Update any matches.

4. Check `agents/analyst_agent.py` for any Python-side division on `total_units` or `absorption_pct` raw values — apply the same guard (`or 1` for Python arithmetic):
   ```python
   absorption_pct = sold / max(total, 1) * 100
   ```

## Done When

- [ ] `NULLIF(total_units, 0)` applied in all `absorption_pct` divisions in `schema.sql`
- [ ] Alembic migrations updated (if any recreate the views)
- [ ] Python-side divisions in `analyst_agent.py` use `max(total, 1)` guard
- [ ] `ruff check .` passes
- [ ] CHANGELOG.md entry written

---

*End of Task Briefs — Stage 3*
