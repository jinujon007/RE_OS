# GATE-124 R1 Audit — Test Fixture Infrastructure Fixes
**Date: 2026-06-19 | Auditor: Kilo Code | Round: 1/3**

## Scope
T-1307→T-1311 — dashboard_client fixture, v2_readiness mock target, skip_no_redis mark, gate124 tests.

## Findings (12)

| ID | Severity | File | Line | Issue |
|----|----------|------|------|-------|
| CONF-1 | MEDIUM | tests/conftest.py | 41–44 | `redis_available` naming inverted: variable named `redis_available` but the `skipif` means "skip when redis is NOT available" — semantic mismatch. Confuses future readers. |
| CONF-2 | LOW | tests/conftest.py | — | Missing `skip_no_redis` alias. Task spec (T-1309) explicitly asked for this name. Future maintainers will search for `skip_no_redis` and find nothing. |
| V2R-1 | HIGH | tests/test_v2_readiness.py | 133–135 | `test_v2_panel_returns_200` hits `/ops/v2` but the legacy redirect only maps `/api/{path}` → `/api/v1/{path}`. `/ops/v2` is not prefixed with `/api/` so 404. Route lives at `/api/v1/ops/v2`. |
| V2R-2 | HIGH | tests/test_v2_readiness.py | 140–224 | `test_v2_declare_*` tests pass `_AUTH = {"X-API-Key": "test-key"}` but `DASHBOARD_API_KEY_ALLOW_EMPTY=true` means "any key is valid" — but only empty/no key maps to admin. Presenting a key that doesn't match `DASHBOARD_API_KEY` results in 401. These tests always fail outside Docker. |
| GATE-1 | MEDIUM | tests/test_gate124.py | 52–63 | A3 only checks `redis_available` but `skip_no_redis` was the spec'd name. Both should be checked for backward compat. |
| GATE-2 | LOW | tests/test_gate124.py | 79–108 | A5 uses `--collect-only` which doesn't verify actual execution. A test could collect fine but fail at fixture setup. Should also run execution for the previously-erroring tests. |
| CONF-3 | LOW | tests/conftest.py | 47–48 | Module-level `import` of `TestClient` and `app` causes eager loading — any app import failure kills the entire test suite. Should be deferred inside the fixture. |
| CONF-4 | LOW | tests/test_dashboard_routes.py | 4 | Redundant `os.environ.setdefault("REDIS_URL", "memory://")` — conftest.py line 24 already does this. Harmless but confusing. |
| CONF-5 | HIGH | tests/conftest.py | 41–44 | `redis_available` mark is defined but ZERO tests use it. The mark provides no value unused. At minimum the rate-limit integration tests should use it. |
| SEC-1 | MEDIUM | tests/test_v2_readiness.py | 10–13 | Module-level `client = TestClient(app)` can leak env state between tests. `_reset_api_keys()` is called in `test_dashboard_routes.py` but `test_v2_readiness.py` never clears the cached keys. |
| V2R-3 | LOW | tests/test_v2_readiness.py | 190–224 | `test_v2_declare_idempotent` checks both dates are non-None but never asserts `date1 == date2` — the core idempotency assertion is missing. |
| DOC-1 | LOW | — | — | No review audit trail file exists for GATE-124. The project convention (GATE-117 precedent) is `docs/reviews/gateNNN_r1_r2_r3.md`. |

## Risk Assessment

- **4 HIGH**: 2 tests always fail (V2R-1, V2R-2), 1 unused mark (CONF-5), 1 broken idempotency test (V2R-3)
- **3 MEDIUM**: naming confusion (CONF-1, GATE-1), env state leakage (SEC-1)
- **5 LOW**: missing alias (CONF-2), shallow assertion (GATE-2), eager import (CONF-3), redundancy (CONF-4), missing docs (DOC-1)

## Recommendations

1. Rename `redis_available` → `require_redis` + add `skip_no_redis` alias
2. Fix `test_v2_panel_returns_200` URL path
3. Fix `test_v2_declare_*` auth — use empty header when ALLOW_EMPTY is true
4. Add `assert date1 == date2` to idempotency test
5. Mark rate-limit integration tests with the redis mark
6. Defer imports in conftest fixture
7. Enrich A5 to execute previously-erroring tests (not just collect)
8. Create R2/R3 audit trail
