# RE_OS — Task Queue
**Stage 3 start · 2026-05-29**
**Next task ID: T-342**

Completed work lives in `CHANGELOG.md` only — this file tracks what is still open.

---

## ⚠ LOCK PROTOCOL — Read This First

**Before touching any code or reading any brief:**

1. Scan the Task Registry below for your brain name.
2. Find the first task assigned to you with status `PENDING`.
3. **Edit this file immediately — change that task's status from `PENDING` to `IN_PROGRESS`.**
4. Save the file.
5. Only then open `TASK_BRIEFS.md` and start work.

**Why:** Two windows of the same brain can open simultaneously. The first write to this file wins. If you open the file and see your intended task is already `IN_PROGRESS`, skip it — pick the next `PENDING` task assigned to you.

**Never** start work on a task still showing `PENDING`. Write the lock first.

---

## Rules for Both Brains

1. **Read `CLAUDE.md` and `TASK_BRIEFS.md` before touching code.**
2. **One task at a time per brain.** If you already have a task `IN_PROGRESS`, finish it before picking another.
3. **Never start a task assigned to the other brain** unless this queue shows it explicitly reassigned.
4. **After every task:** write one CHANGELOG.md entry (format: `TYPE | file | what changed | who | date`), then update status here to `DONE`.
5. **Ruff must pass** after every change: `ruff check .` and `ruff format --check .`. Fix violations before marking done.
6. **Tests must not regress.** Run `pytest tests/ -q` before marking done. If new tests are required by the brief, they must be included.
7. **If blocked:** write one line in the NOTES column, set status to `BLOCKED`, and stop. Do not guess. Do not work around blockers silently.
8. **No new dependencies** without a justification comment in `requirements.txt`.

---

## Status Key

| Symbol | Meaning |
|--------|---------|
| `PENDING` | Not started — available to pick up |
| `IN_PROGRESS` | Claimed — do not touch, another window is working on it |
| `DONE` | All done-when checks passed, CHANGELOG written |
| `BLOCKED` | Waiting on external factor — see Notes column |

---

## Task Registry

| ID | One-Line Description | Brain | Priority | Status | Notes |
|----|----------------------|-------|----------|--------|-------|
| T-281 | Fix RERA scraper locality selector for Yelahanka + Hebbal | Kilo | P0 | BLOCKED | File scrapers/rera_karnataka.py is banned for Kilo Code (Claude Code only per KILO_BRIEF.md) |
| T-302 | Add pytest coverage for DBOrganizer (insert / update / SAVEPOINT rollback) | Cline | P1 | DONE | Mock-based tests + data_source validation test added (182 pass) |
| T-315 | Scheduler job to recover stuck "active" board sessions after 30 min | Kilo | P1 | DONE | Implemented in scheduler.py — verified in code 2026-05-29 |
| T-316 | Dockerfile: remove duplicate apt Chromium install (~200MB saving) | Kilo | P1 | PENDING | |
| T-317 | Delete deprecated `GET /api/intel` file-read endpoint from dashboard | Cline | P1 | DONE | |
| T-318 | Board Room SQLAlchemy engine pool: increase to pool_size=5 max_overflow=2 | Cline | P1 | DONE | |
| T-319 | Add Flask-CORS to dashboard with env-var origin allowlist | Kilo | P2 | PENDING | |
| T-320 | Replace `logger.info(dict)` in `_log_event` with `json.dumps` serialisation | Kilo | P2 | DONE | Already applied in Round 21 |
| T-321 | Replace `_daily_counts` direct import with `get_router_status()` call | Cline | P2 | DONE | |
| T-322 | Remove unused `superseded_by` FK column from `agent_memories` | Cline | P2 | DONE | Alembic 0005 + schema.sql |
| T-323 | Add `ORDER BY` to `STRING_AGG` in `v_developer_scorecard` view | Kilo | P2 | PENDING | |
| T-324 | Run `alembic upgrade head` before gunicorn starts (docker-compose) | Kilo | P2 | PENDING | |
| T-325 | Add pip-audit step to CI workflow for CVE scanning | Kilo | P1 | PENDING | |
| T-326 | Add `make ci` target to Makefile (mirrors CI: py_compile + ruff + pytest) | Kilo | P2 | PENDING | |
| T-327 | Bump pool_size=5 max_overflow=2 in agent_memory.py + market_intel_crew.py | Kilo | P2 | PENDING | |
| T-328 | Dashboard route tests: health, db/state, agents, run trigger, 401 gate | Cline | P1 | DONE | tests/test_dashboard_routes.py — 5 tests pass |
| T-329 | Validate data_source field in db_organizer against DB CHECK constraint | Cline | P2 | DONE | VALID_DATA_SOURCES guard in _upsert_project |
| T-330 | Remove all sys.path.append() calls — PYTHONPATH=/app makes them dead code | Kilo | P1 | DONE | 14 edited, 2 banned (skipped) |
| T-331 | Fix scheduler engine leak — run_market_snapshot + recover_stuck create fresh engine per call | Kilo | P1 | PENDING | |
| T-332 | Gunicorn --max-requests 500 --max-requests-jitter 50 to prevent worker memory bloat | Kilo | P2 | PENDING | |
| T-333 | Flask after_request: add X-Content-Type-Options, X-Frame-Options, Referrer-Policy headers | Kilo | P2 | PENDING | |
| T-334 | Update .env.example with DASHBOARD_ALLOWED_ORIGINS key (added by T-319) | Kilo | P2 | PENDING | |
| T-335 | GitHub PR template at .github/pull_request_template.md | Kilo | P3 | PENDING | |
| T-336 | Add detect-secrets baseline to CI — prevent credential commits | Kilo | P3 | PENDING | |
| T-337 | Extract shared DB engine factory to utils/db.py — 8 files duplicate create_engine | Cline | P1 | DONE | utils/db.py + analyst_agent + kaveri_transaction_scout |
| T-338 | Add pytest markers unit/integration — allow CI to run unit tests without live DB | Cline | P1 | DONE | pytest.ini + all test files marked + CI updated |
| T-339 | Fix analyst_agent.py engine: missing pool_pre_ping + pool settings | Cline | P2 | DONE | uses get_engine() from utils/db.py |
| T-340 | Add last_scraped_at TIMESTAMPTZ to micro_markets + Alembic migration + db_organizer update | Cline | P2 | DONE | Alembic 0006 + schema.sql + db_organizer.run() |
| T-341 | v_active_projects: add NULLIF guard on absorption_pct division to prevent divide-by-zero | Cline | P2 | DONE | NULLIF in GENERATED ALWAYS column; views use stored value |

---

## GATE STATUS

| Gate | Unlocked By | Status |
|------|-------------|--------|
| GATE-4 | T-281 ≥50 live RERA projects for Yelahanka or Hebbal | PENDING |
| GATE-7 | T-302 passes + test coverage ≥55% | PENDING |
| GATE-8 | T-317 + T-325 + T-328 done — Security score ≥80 | PENDING |
| GATE-9 | T-319 + T-324 done — Prod Readiness score ≥75 | PENDING |
