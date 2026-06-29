# GATE-152 Round 1 Audit — Corridor Backtest Accuracy
**Date:** 2026-06-27
**Auditor:** Kilo Code (Review Protocol)

---

## Executive Summary

20 findings across 5 deliverables: **2 CRITICAL**, **6 HIGH**, **7 MEDIUM**, **5 LOW**.

**Critical** findings must ship-block. HIGH findings create runtime risk or data correctness issues. MEDIUM = observability, maintainability, or test gaps. LOW = style/comment nits.

---

## FINDINGS

### CRITICAL

| ID | File | Line(s) | Finding | Risk |
|----|------|---------|---------|------|
| C-1 | `utils/corridor_scorer.py` | 763-770 | **Wrong DB table + wrong columns.** `project_snapshots` has NO `psf`, `market`, or `scrape_date` columns. Schema: `price_min_psf`, `price_max_psf`, `snapshot_date`, `rera_project_id`. Query would raise `psycopg2.errors.UndefinedColumn` at runtime. Must use `registered_transactions` (has `psf`, `village`, `reg_date`) matching all other queries in this class. | **Runtime crash** on first production call |
| C-2 | `tests/test_gate152.py` | 199-217 | **A4 test is a static source-code grep, not a behavioral test.** `inspect.getsource()` + `"Corridor accuracy" in source` only proves the string was typed into the file, not that the context-building logic actually runs or produces correct output. Does not mock `CorridorScorer.backtest`, does not call the function under test. | **False confidence** — gate assertion passes regardless of broken logic |

### HIGH

| ID | File | Line(s) | Finding | Risk |
|----|------|---------|---------|------|
| H-1 | `utils/corridor_scorer.py` | 751-776 | **N+1 query pattern.** 3 queries per corridor (t24/t12/now) × N corridors = 3N connections. Should batch all windows per corridor into a single query or use a single query for all corridors. | Performance: O(N) round trips per call |
| H-2 | `utils/corridor_scorer.py` | 760-772 | **`_avg_psf_for_window` closure redefined inside loop.** Each iteration rebinds the closure. No correctness bug but wastes CPU and defies reader expectations. | Readability, minor perf |
| H-3 | `utils/corridor_scorer.py` | 753-756 | **30-day-month approximation.** `lookback_months * 30` is off by ~10 days at 24 months (720 vs 730 actual). Real PSF data drifts with exact dates. | Data accuracy erosion at longer lookbacks |
| H-4 | `dashboard/routers/data.py` | 1920-1941 | **`best`/`worst` corridor logic is fragile.** Uses `-float("inf")`/`float("inf")` sentinels with `max`/`min` over `range(len(results))`. Fails if all `actual_change_pct` are `None` (the try/except outer handler catches this, but it should be explicit). | Silent misreporting on edge cases |
| H-5 | `dashboard/routers/data.py` | 1878-1954 | **No Prometheus metrics.** Every other endpoint in `data.py` has request counter + duration histogram. Missing instrumentation means ops can't track usage. | Ops blindspot |
| H-6 | `dashboard/routers/data.py` | 1878-1954 | **No ETag caching.** Similar endpoints use `compute_etag`/`check_etag`. Without ETags, repeated identical requests hit the DB every time. | Unnecessary DB load on dashboard auto-refresh |

### MEDIUM

| ID | File | Line(s) | Finding |
|----|------|---------|---------|
| M-1 | `dashboard/routers/data.py` | 1881-1888 | **No `lookback_months` query param exposed.** Hardcoded 24. Callers can't adjust window without code change. |
| M-2 | `dashboard/routers/data.py` | 1943-1949 | **Missing `generated_at` field.** Other endpoints include `generated_at: ISO` timestamp for client-side staleness detection. |
| M-3 | `dashboard/routers/data.py` | 1943-1949 | **No `response_model` defined.** Returns raw dict instead of Pydantic model. Clients lose schema guarantees, OpenAPI docs lose this endpoint. |
| M-4 | `dashboard/routers/data.py` | 1899 | **No `lookback_months` in response.** Consumer can't tell what window generated the data. |
| M-5 | `tests/test_gate152.py` | 30-50 | **A1 mock is brittle.** Depends on exact ordering of `CORRIDOR_DEFINITIONS` and exact number of `fetchone` calls. Adding/removing a corridor breaks the test. |
| M-6 | `tests/test_gate152.py` | 201 | **Imports `_run_dept_heads` but never calls it.** Dead import. |
| M-7 | `utils/corridor_scorer.py` | 793-796 | **Sort key sentinel `-1` for None values.** `abs(r["actual_change_pct"]) if r["actual_change_pct"] is not None else -1` — with `reverse=True`, None items cluster at bottom, but intent is opaque. Should filter Nones before sort. |

### LOW

| ID | File | Line(s) | Finding |
|----|------|---------|---------|
| L-1 | `alembic/versions/0073_corridor_backtest.py` | 20-21 | `nullable=True` explicit on `id` and `created_at` — redundant, default is True |
| L-2 | `alembic/versions/0073_corridor_backtest.py` | 20-31 | No `sa.Comment(...)` on columns explaining business semantics |
| L-3 | `crews/board_room.py` | 767 | MAPE with single corridor is misleading (mean of one value = itself). Should require ≥2 data points. |
| L-4 | `tests/test_gate152.py` | 227 | Only tests generic `Exception`, not `OperationalError` or `ProgrammingError` which are the real failure modes |
| L-5 | `utils/corridor_scorer.py` | 742-743 | No `market` input validation — empty string passes through, silently returns `[]` |

---

## Severity Legend

| Level | Definition | Action required |
|-------|------------|----------------|
| **CRITICAL** | Causes runtime failure, data corruption, or can't-miss stakeholder requirement | Must fix before deployment |
| **HIGH** | Causes degraded output, performance bottleneck, observability hole, or unreliable test | Strongly recommended before deployment |
| **MEDIUM** | Suboptimal design pattern, missing but non-critical feature, test brittleness | Fix this round |
| **LOW** | Cosmetic, documentation, or negligible maintainability | Fix if time permits |
