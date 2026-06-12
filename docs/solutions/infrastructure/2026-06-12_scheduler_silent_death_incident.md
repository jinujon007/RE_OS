---
module: config/scheduler.py, docker-compose.yml, alembic/versions/0055_parcels_table.py
tags: [incident, scheduler, redis, alembic, postmortem, silent-failure]
problem_type: production-outage
date: 2026-06-12
severity: P0
---

# Incident: Scheduler Silent Death + Redis Crash Loop + Broken Migration

## Impact

The APScheduler container was exiting cleanly (~every 68s, restart loop) — **zero scheduled jobs ran while it was down**: no scrapes, no Discord alerts, no digests, no nightly DB backups (last good dump 2026-06-08). Redis was in a separate fatal crash loop. The agents container then crash-looped after recreation due to a broken in-flight migration. Three independent failures, all discovered in one session because nobody was watching the scheduler — it had no liveness signal.

## Root causes (three separate bugs)

### 1. Orphaned `__main__` block (scheduler silent death)
Sprint 91 (T-1139) inserted `def run_kaveri_deeds_weekly():` at column 0 **in the middle of the `if __name__ == "__main__":` block**. Everything after it — `scheduler = BlockingScheduler(...)`, all 36 `add_job` calls, `scheduler.start()` (still indented 4 spaces) — became the tail of that function's body. The main block shrank to "make output dirs", so the script ran, logged 4 lines, and exited 0. Syntactically valid; `py_compile` green; all unit tests green (they import functions, never execute `__main__`). Exit code 0 meant even Docker considered it a clean exit.

**Fix:** moved the `__main__` block below all function defs, directly wrapping the scheduler setup + `start()` (config/scheduler.py).

### 2. Redis `requirepass` with empty value (fatal crash loop)
`docker-compose.yml` line 101: `command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD:-}` — but `REDIS_PASSWORD` was never added to `.env`. Empty interpolation renders a bare `--requirepass` → `FATAL CONFIG FILE ERROR ... wrong number of arguments` → infinite restart. The auth flag was added in a hardening sprint; the env var that powers it never shipped.

**Fix:** generated a strong password, added `REDIS_PASSWORD=...` to `.env`, recreated containers. `NOAUTH` on unauthenticated ping confirms auth is now actually enforced (it never was before).

### 3. Duplicate index creation in migration 0055 (agents crash loop)
`0055_parcels_table.py` created `idx_parcels_village` (and `idx_parcels_survey_no`) **twice** — a pasted block. Alembic runs the migration in a transaction: index duplicate → `DuplicateTable` → full rollback → `alembic_version` stays at 0054 → agents entrypoint (`alembic upgrade head`) fails on every container start.

**Fix:** removed the duplicated two lines; migrations 0055+0056 then applied cleanly (head `0056_assembly_signals`, `parcels` + `assembly_signals` live).

## Why the safety net missed all three

- CI runs `py_compile` + pytest — none of which **execute** `config/scheduler.py` as a script. A structurally dead `__main__` is invisible to both.
- The scheduler health endpoint (Sprint 88) reports job health *from inside a running scheduler* — it cannot report that the scheduler process itself is dead.
- Redis failure was masked because callers fall back (rate-limiter memory://, etc.) — the system degraded silently instead of failing loudly.
- Migration 0055 was Kilo work-in-progress (T-1141), never run before the container recreation forced it.

## Prevention (specced as T-1158, Sprint 91.5/93)

1. **CI dry-run:** `SCHEDULER_DRY_RUN=1 python config/scheduler.py` must register all jobs and exit 0 without `start()`; CI asserts job count ≥30. Catches orphaned-main and import/registration crashes at PR time.
2. **Heartbeat:** scheduler writes an `agent_runs` heartbeat row every 30 min; the existing data-floor check alerts Discord OPS when the last heartbeat is >2h old. Catches silent death at runtime.
3. **Process rule:** any edit to `config/scheduler.py` requires running the dry-run locally before commit (add to KILO_BRIEF.md checklist).
4. Migration files: `alembic upgrade head` against a scratch DB is part of the verify step for every migration task (was already the rule — re-stated; 0055 hadn't reached its verify step yet, but the duplicate would have been caught by it).

## Verified end state (2026-06-12)

- 5/5 containers Up; scheduler **healthy** with 36 active jobs (incl. kaveri_deeds_weekly, parcel_linker_nightly, assembly_detection)
- Redis Up with auth enforced
- Alembic head `0056_assembly_signals`; `parcels`/`assembly_signals` tables live
- Fresh verified backup `re_os_20260612_094607.dump` (460 objects)
