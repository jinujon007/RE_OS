# RE_OS — Task Queue
**Stage 3 · 2026-05-29 | Single-brain: Kilo Code**
**Next task ID: T-342**

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

## Task Registry

| ID | Description | Priority | Status | Notes |
|----|-------------|----------|--------|-------|
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
| GATE-4 | T-281 ≥50 live RERA projects for Yelahanka or Hebbal | VERIFY — run scraper after deploy |
| GATE-7 | T-302 test coverage ≥55% | PASSED |
| GATE-8 | T-317 + T-325 + T-328 done | PASSED |
| GATE-9 | T-319 + T-324 done | PASSED |
