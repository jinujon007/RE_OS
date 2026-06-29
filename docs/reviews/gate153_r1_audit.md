# GATE-153 Round 1 Audit — Deed Throughput Acceleration

**Date:** 2026-06-29  
**Reviewer:** Kilo Code (Engineering Lead)  
**Scope:** T-1451 → T-1455 (Alembic 0074, get_priority_villages, download-guide endpoint, reminder extension, test_gate153.py)

---

## Finding Summary

| Severity | Count |
|----------|-------|
| 🔴 CRITICAL | 2 |
| 🟠 HIGH | 4 |
| 🟡 MEDIUM | 4 |
| 🔵 LOW | 5 |
| **Total** | **15** |

---

## 🔴 CRITICAL

### C1. Auth bypass — download-guide route requires write role for read-only GET

**File:** `dashboard/state.py`  
**Issue:** `GET /api/v1/deeds/download-guide` is not in `_READ_ONLY_PATHS` and doesn't match any `_READ_ONLY_PREFIXES`. The auth middleware fallback (line 264) treats it as a write endpoint, requiring ≥ write role. A user with only a read-only API key will get a 403.

**Impact:** Jinu or any view-only stakeholder cannot access the download guide without a write/admin key. This breaks the intended UX where the Monday reminder links to this endpoint.

**Fix:** Add `/api/v1/deeds/download-guide` and `/api/deeds/download-guide` to `_READ_ONLY_PATHS` in `dashboard/state.py`.

---

### C2. A3 test asserts `True` unconditionally — no behavioral verification

**File:** `tests/test_gate153.py:143`  
**Issue:** `test_gate153_a3_reminder_includes_priority_villages` computes `has_village` but **never asserts it**. The final line is `assert True`. This means the test always passes regardless of whether the priority villages are actually included in the Telegram message.

**Impact:** Zero coverage of the core T-1454 behavioral requirement. A regression could silently delete the priority villages section and this test would still pass.

**Fix:** Assert `has_village` is `True`. Also restructure the mock to reliably exercise the priority villages code path rather than falling through to generic reminder.

---

## 🟠 HIGH

### H1. SQL injection surface via f-string interpolation in get_priority_villages

**File:** `utils/deed_progress.py:198`  
**Issue:** The WHERE clause is interpolated via f-string: `text(f"""... {where} ...""")`. Currently the `where` variable is hardcoded to either `"WHERE 1=1"` or `"WHERE asm.market ILIKE :market"`, so this is safe **today**. But the pattern is fragile — any future change adding user-controlled string interpolation will create a SQL injection vector. This is a well-known antipattern in SQLAlchemy.

**Impact:** Latent security debt. Violates defense-in-depth principle — the codebase convention should prevent injection by design, not by luck.

**Fix:** Use two separate static queries or build the WHERE clause with SQLAlchemy's `and_()` / `or_()` composable operators. Alternatively, keep the f-string but add a guard clause and inline comment marking the exact two allowed values.

---

### H2. `last_deed_ingested` type unsafety in row parsing

**File:** `utils/deed_progress.py:220`  
**Issue:** `row[4].isoformat()` assumes `row[4]` is a `datetime` object. PostgreSQL returns `timestamp` as `datetime` and `date` as `date` (both have `.isoformat()`), and `None` is handled via the `if row[4] else None` guard. However, if the view ever returns a string (e.g., due to a cast or materialization), `.isoformat()` will raise `AttributeError`.

**Impact:** Brittle. A schema change or view materialization could silently break the endpoint at runtime.

**Fix:** Add a type check: if `row[4]` is a string, return it directly; if `datetime`/`date`, call `.isoformat()`; else `None`.

---

### H3. No edge case coverage for boundary values in test suite

**File:** `tests/test_gate153.py`  
**Issue:** Missing tests for: (1) `market=None` — returns all villages across markets; (2) `top_n=0` — should clamp to 1 (or return empty); (3) `top_n` exceeding `max 10` — the API has `le=10` but the underlying function doesn't; (4) unknown market — returns empty list gracefully; (5) unauthenticated access — returns 401.

**Impact:** Production edge cases untested. Any of these scenarios can cause unhandled exceptions in production.

**Fix:** Add at least 4 additional edge case tests covering these scenarios.

---

### H4. Priority villages silently fail in reminder job

**File:** `config/scheduler/deed_jobs.py:468`  
**Issue:** The `except Exception: pass` block (line 468-469) swallows all errors from `get_priority_villages` without logging. If this function raises due to a view migration issue, the silent failure means the reminder still sends — but without the priority section. Jinu won't know the intelligence layer is degraded.

**Impact:** Silent degradation. Undermines system observability.

**Fix:** Replace `pass` with `logger.warning("[DeedJobs] Failed to fetch priority villages: {}", exc)`.

---

## 🟡 MEDIUM

### M1. Inconsistent Unicode in reminder message

**File:** `config/scheduler/deed_jobs.py:467`  
**Issue:** The priority section uses `→` (U+2192, rightwards arrow) while the existing code uses `→` (same character). Verified they're the same in the current commit. However, the message prepend re-orders the header — "Kaveri Form 17 Download Due" appears **after** the priority villages section, which is confusing.

**Impact:** UX degradation. The user expects the header first, then supplementary info.

**Fix:** Keep priority villages as a sub-section after the header, not before it.

---

### M2. Missing `__init__.py` re-export for `get_priority_villages`

**File:** `utils/__init__.py`  
**Issue:** If `utils/__init__.py` exists and has an `__all__`, `from utils import get_priority_villages` may fail. The reminder job uses a direct import (`from utils.deed_progress import get_priority_villages`) which works, but the pattern is inconsistent with other utils.

**Impact:** Minor import inconsistency. Won't cause runtime failure but violates team conventions.

**Fix:** Add re-export to `utils/__init__.py` if it exists.

---

### M3. View SQL uses `NOW()` — timezone-unaware

**File:** `alembic/versions/0074_deed_village_priority.py:24`  
**Issue:** `EXTRACT(EPOCH FROM (NOW() - MAX(rt.created_at)))` uses `NOW()` which returns the **current transaction time** in the server's timezone. If `rt.created_at` is stored with timezone (TIMESTAMPTZ) and the server timezone changes, the computation will drift.

**Impact:** Low — PostgreSQL `NOW()` is consistent within a single transaction. But `created_at` columns in this project are typically `TIMESTAMP WITH TIME ZONE`, so the subtraction works correctly regardless of server timezone. However, `priority_score` values will shift slightly if the view is queried at different times of day.

**Fix:** Acceptable as-is. Document that `priority_score` is time-dependent and monotonically decreases as `last_deed_ingested` ages.

---

### M4. No `generated_at` timezone indicator in response

**File:** `dashboard/routers/data.py:2089`  
**Issue:** `datetime.now(timezone.utc).isoformat()` returns `2026-06-29T12:00:00+00:00` — correct and timezone-aware. No issue here. (Dismissal — this is actually done correctly.)

---

## 🔵 LOW

### L1. Docstring inaccuracies

- `utils/deed_progress.py:182`: Docstring says "market: Optional market filter (Yelahanka / Devanahalli / Hebbal)" but the function uses ILIKE with wildcards, so partial matches work too. Should document that it's a case-insensitive substring match.
- `dashboard/routers/data.py:2071-2078`: Route summary is good but missing the response schema description.

---

### L2. `market` param inconsistent casing in the view

**File:** `alembic/versions/0074_deed_village_priority.py:25`  
The view projects `asm.market` as-is, which may contain mixed-case values. The `get_priority_villages` function uses `ILIKE` so this works, but standardizing to `LOWER(asm.market)` in the view would be cleaner.

---

### L3. Missing Prometheus metrics

**File:** `dashboard/routers/data.py`  
The download-guide endpoint has no request counter or latency histogram, unlike most other data endpoints (e.g., `_investor_brief_requests_total`, `_investor_brief_duration_seconds`). This makes it invisible in monitoring dashboards.

---

### L4. Duplicate `now` variable in `run_kaveri_download_reminder`

**File:** `config/scheduler/deed_jobs.py:375-377`  
`from datetime import datetime, timezone` is imported inside the function body, and `now = datetime.now(timezone.utc)` is assigned but never used in the priority villages section. This is a pre-existing minor dead code pattern.

---

### L5. `row` indexing ambiguity

**File:** `utils/deed_progress.py:214-221`  
Column access via `row[0]`, `row[1]`, etc. is fragile if the view column order changes. Should use `row._mapping` or `row.tuple()` for named access.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Auth 403 on download-guide | High | Medium — Jinu gets 403 from dashboard links | Fix in R2 |
| A3 test false positive | High | High — regression undetected | Fix in R2 |
| Silent failure in reminder | Medium | Low — message still sends without priority | Fix in R2 |
| SQL injection via f-string | Low | Critical — only if code is modified | Fix in R2 with guard |
| Type error on date field | Low | Medium — 500 on endpoint | Fix in R2 |
| Missing edge cases | Medium | Medium — unexpected 500s in prod | Fix in R2 |

---

## Round 1 Close

15 findings documented. R1 audit written to `docs/reviews/gate153_r1_audit.md`.  
Proceeding to R2 — implement all fixes.
