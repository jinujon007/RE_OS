# GATE-115 — 3-Round Iterative Review
**Sprint 115 — Redis Resilience (T-1261→T-1265)**
**Date: 2026-06-18 | Auditor: Kilo Code**

---

## Round 1 — Full Audit

### Scope
7 files audited: `dashboard/state.py`, `dashboard/redis_health.py`, `dashboard/app_fastapi.py`, `utils/db.py`, `tests/test_redis_resilience.py`, `tests/test_pool_exhaustion.py`, `tests/test_gate115.py`, `docs/operations.md`

### Findings

| ID | Sev | File | Description | Status |
|----|-----|------|-------------|--------|
| R1.1 | CRIT | state.py | Double-checked locking in `_get_redis_client()` — outer cooldown gate redundant under lock, caused cognitive overhead | ✅ FIXED |
| R1.2 | MED | redis_health.py | Health loop dies silently on exception — no top-level try/except | ✅ FIXED |
| R1.3 | MED | redis_health.py | `was_down` race between read and `_get_redis_client()` call | ✅ FIXED |
| R1.4 | LOW | redis_health.py | Duplicate import of `_attempt_redis_connect` | ✅ FIXED |
| R1.5 | LOW | app_fastapi.py | No try/except around health thread start in lifespan | ✅ FIXED |
| R1.6 | MED | app_fastapi.py | Lifespan thread not named — hard to debug in thread dumps | ✅ FIXED |
| R1.7 | MED | db.py | `_check_pool_exhaustion` ran suppression check on every checkout even when suppressed | ✅ FIXED |
| R1.8 | MED | db.py | `_pool_exhaustion_alert_suppressed_until` had no thread-safety lock | ✅ FIXED |
| R1.9 | MED | db.py | Custom suppression timer instead of existing `AlertSuppressor` — inconsistent with rest of codebase | ✅ FIXED |
| R1.10 | MED | tests | Thread-based tests with `time.sleep(0.05)` are flaky on slow CI | ✅ FIXED |
| R1.11 | LOW | tests | Redundant/confusing variable assignments in test setup | ✅ FIXED |
| R1.12 | LOW | tests | Missing positive test: existing valid client returned unchanged | ✅ FIXED |
| R1.13 | LOW | tests | `time.time()` dependency in suppression test | ✅ FIXED |
| R1.14 | LOW | gate | Gate test duplicated unit test logic instead of being a lightweight verifier | ✅ FIXED |
| R1.15 | LOW | state.py | `_last_redis_attempt=0.0` sentinel undocumented | ✅ FIXED |
| R1.16 | MED | metrics | No `redis_connected` Prometheus gauge — Redis state invisible in Grafana | ✅ FIXED |
| R1.17 | LOW | docs | No cross-reference to Prometheus/Grafana for Redis alert monitoring | ✅ FIXED |

### Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| RR1 | `_redis_health_loop` exception kills thread | Low | MED — Redis stays unreachable until container restart | R1.2: try/except in loop body |
| RR2 | Pool exhaustion alert storms | High | LOW — Discord rate-limit | R1.7/R1.8/R1.9: Boolean gate + AlertSuppressor + lock |
| RR3 | TestClient doesn't clean up health thread | Low | LOW — daemon thread exits with process | Named thread for debugging; daemon=true |
| RR4 | Lifespan crash prevents app start | Low | CRIT — server 500s | R1.5: try/except around thread start |
| RR5 | Redis unreachable silently degrades workers | Med | MED — pipeline state may diverge | R1.16: redis_connected Prometheus gauge + Prometheus alert |

---

## Round 2 — Fixes Applied

### R1.1: Simplified locking in `_get_redis_client`
- **Before**: Two-step cooldown check (outside lock + inside lock) — redundant
- **After**: Single lock-only cooldown gating with `_REDIS_RECONNECT_COOLDOWN` constant
- **Rationale**: The lock is the serialization primitive; the outer check added no thread-safety benefit but created a second code path to audit

### R1.2/R1.3/R1.4: Health loop hardening
- **R1.2**: Wrapped `_run_health_check()` call in try/except with `logger.exception()`
- **R1.3**: Replaced `was_down = _state._REDIS_CLIENT_INSTANCE is False` before `_get_redis_client()` call with logic that checks `was_down` from the state *before* the call but only applies it inside the `ping()` success path — eliminates the race where `_get_redis_client` modifies the sentinel
- **R1.4**: Removed `from dashboard.state import _attempt_redis_connect` — use `_state._attempt_redis_connect` instead

### R1.5: Lifespan exception guard
- Wrapped `_health_thread.start()` in try/except. Added named thread `"redis-health"` (R3.2).

### R1.7/R1.8/R1.9: Pool exhaustion rewrite
- **Before**: `_pool_exhaustion_alert_suppressed_until` float timer, no lock, checked on every checkout
- **After**: `_pool_is_exhausted` boolean flag + `_pool_exhaustion_lock` + `AlertSuppressor.suppress("db_pool_exhausted", cooldown_hours=4)`
- Boolean flag is reset when `checkedout < max_connections`, preventing redundant work
- Consistent with all other alerts in codebase (backup, data floor, kill criteria)
- Lock prevents concurrent `_pool_is_exhausted` transitions

### R1.10: Replace flaky thread tests with direct calls
- **Before**: `TestRedisHealthLoop` started real daemon threads with `time.sleep(0.05)`
- **After**: `TestRedisHealthCheck` calls `_run_health_check()` directly — deterministic, 0.5s → 0.05s per test

### R1.11: Clean test setup
- Added `_reset_state()` helper to centralize `_REDIS_CLIENT_INSTANCE = None` + `_last_redis_attempt = 0.0`
- Removed redundant manual sets after patches

### R1.12: Added positive test
- `test_redis_returns_existing_client_when_connected` — verifies that a valid client is returned unchanged without calling `_attempt_redis_connect`

### R1.13: Removed time dependency in pool exhaustion test
- **Before**: `patch("utils.db._pool_exhaustion_alert_suppressed_until", time.time() + 300)` — fragile under clock skew
- **After**: `patch("utils.db._pool_is_exhausted", True)` — deterministic boolean

### R1.14: Gate test lightweighted
- `test_gate115.py` now only checks importability + callability, not internal logic
- Unit tests cover the logic; gate tests verify wiring

### R1.15: Documented sentinel
- Added `_REDIS_RECONNECT_COOLDOWN = 30` constant
- Comment: `# sentinel: 0.0 always triggers first attempt (monotonic clock floor)`

### R1.16: Added `redis_connected` Prometheus gauge
- Defined in `config/metrics.py` as `redis_connected` gauge
- Updated by `_set_redis_gauge()` in `redis_health.py` on every health check iteration
- Module-level import (R3.1) avoids repeated lazy lookups

### R1.17: Updated operations docs
- Added `redis_connected` Prometheus gauge reference + Grafana dashboard cross-ref
- Documented Discord `db_pool_exhausted` alert and suppression window

---

## Round 3 — Elite Polish

### R3.1: Module-level gauge import
- Moved `from config.metrics import redis_connected` from inside `_set_redis_gauge()` to module-level (with try/except fallback to `None`)
- Eliminates repeated lazy import on every 15s health check

### R3.2/R3.4: Named health thread
- `name="redis-health"` in `threading.Thread()` — visible in thread dumps and debug logs

### R3.3: Prometheus alert for Redis unavailability
- New alert `RedisUnreachable` in `prometheus/alerts.yml`:
  - Expression: `redis_connected == 0`
  - For: 1m (avoids flapping on transient ping failures)
  - Severity: warning
  - Includes runbook URL and action steps

### R3.5: Grafana Redis Connectivity stat panel
- Added `Redis Connectivity` stat panel to `system_health.json`
- Type: `stat` with value mapping (1 → "Connected" green, 0 → "Disconnected" red)
- Threshold at 1 — shows red/green at a glance

---

## Final Validation

| Check | Result |
|-------|--------|
| py_compile (all touched .py) | ✅ Clean |
| ruff (all touched .py) | ✅ All checks passed |
| Unit tests (22 tests) | ✅ 22/22 passed (0 failures, 0 errors) |
| Gate tests (4 assertions) | ✅ 4/4 passed |

### Files Changed (Sprint 115 — all rounds)

| File | R1 | R2 | R3 |
|------|----|----|----|
| `dashboard/state.py` | — | ✓ | — |
| `dashboard/redis_health.py` | — | ✓ | ✓ |
| `dashboard/app_fastapi.py` | — | ✓ | ✓ |
| `utils/db.py` | — | ✓ | — |
| `config/metrics.py` | — | ✓ | — |
| `prometheus/alerts.yml` | — | — | ✓ |
| `config/grafana/.../system_health.json` | — | — | ✓ |
| `docs/operations.md` | — | ✓ | — |
| `tests/test_redis_resilience.py` | — | ✓ | ✓ |
| `tests/test_pool_exhaustion.py` | — | ✓ | — |
| `tests/test_gate115.py` | — | ✓ | — |

### Remaining Risks

1. **TestClient lifespan**: FastAPI `TestClient` may not run lifespan in all versions. The daemon thread is safe (exits with process). Verified: all 22 unit tests pass with `TestClient`-based tests in existing suite using `REDIS_URL=memory://`.
2. **No integration test**: Real Redis connectivity is not tested in CI (no Redis service in CI workflow). Verified in-memory fallback path only. Add Redis service to CI if integration testing becomes critical.
3. **AlertSuppressor DB dependency**: `_check_pool_exhaustion` calls `AlertSuppressor.suppress()` which queries the `alerts` table. If the DB itself is exhausted, this will fail silently (caught by try/except). The `_pool_is_exhausted` flag prevents repeated attempts.
4. **AlertSuppressor fallback**: `AlertSuppressor.suppress()` falls back to in-memory dict if DB is unavailable. Under pool exhaustion, the DB is likely also highly loaded — the in-memory fallback works correctly.
