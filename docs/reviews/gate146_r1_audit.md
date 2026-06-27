# GATE-146 Round 1 — Full Audit

**Date:** 2026-06-27  
**Auditor:** Kilo Code  
**Scope:** T-1416→T-1420 (Assembly Intelligence Production)

---

## CRITICAL

| # | Finding | File(s) | Impact | Fix |
|---|---------|---------|--------|-----|
| C1 | `send("bd-intel", ...)` uses invalid Discord channel `bd-intel`. Valid channels are `bd_opportunities`, `competitor`, `gcc_intel`, `govt_policy_scout`, `health`, `intel`, `intel_reports`, `price`, `rera_*`, `system`. Alerts silently fail to deliver in production. | `config/scheduler/deed_jobs.py:307,343` | Production alerts not delivered | Change `"bd-intel"` → `"intel"` or `"competitor"` |
| C2 | `write_assembly_signal()` calls `_write_md()` (disk write) as side effect inside a **GET** endpoint (`/intel/assembly/{id}/obsidian-export`). GET endpoints should be idempotent/read-only. | `utils/obsidian_sync.py:501-506`, `dashboard/routers/data.py:2402-2419` | Side-effect in GET; doubles disk writes | Make disk write conditional on seeing the env var check (mirror `write_investor_brief` pattern) |

## HIGH

| # | Finding | File(s) | Impact | Fix |
|---|---------|---------|--------|-----|
| H1 | `write_assembly_signal` not in `__all__` export list of `utils/obsidian_sync.py` | `utils/obsidian_sync.py:42-48` | Module contract broken; consumers must import by qualified name | Add to `__all__` |
| H2 | `_get_tier()` re-imports `ASSEMBLY_ALERT_THRESHOLDS` on every call (per cluster) | `config/scheduler/deed_jobs.py:258` | Unnecessary import overhead in hot loop | Move import outside function |
| H3 | `run_assembly_detection()` shadows module-level `send` import with a local import | `config/scheduler/deed_jobs.py:275` | Confusing; module-level `send` already imported at line 24 | Remove local import, use module-level |
| H4 | `_build_assembly_context` WHERE clause `(resolved_at IS NULL OR status = 'open')` allows impossible combos | `crews/board_room.py:232` | Could return rows that are partially resolved | Change to `resolved_at IS NULL AND status = 'open'` |

## MEDIUM

| # | Finding | File(s) | Impact | Fix |
|---|---------|---------|--------|-----|
| M1 | PSF Context in Obsidian export is a static link, not computed data | `utils/obsidian_sync.py:487-488` | File not self-contained; needs network to be useful | Remove section or add computed PSF data |
| M2 | No tests for invalid UUID format on resolve endpoint | `tests/test_assembly_drilldown.py` | Missing 400 validation coverage | Add test: invalid UUID → 400 |
| M3 | No tests for non-existent signal_id on obsidian-export | Tests | Missing 404 coverage | Add test |
| M4 | No tests for all-None cluster fields in `write_assembly_signal` | `tests/test_assembly_obsidian.py` | Edge-case coverage gap | Add test with empty dict |
| M5 | Duplicate `_MockRow` class in `test_gate146.py` and `test_assembly_board_context.py` | Both test files | Code duplication | Extract shared helper or reuse |
| M6 | `test_resolve_updates_db` asserts `conn.execute` was called but not the SQL content | `tests/test_assembly_drilldown.py:17-30` | Weak assertion; doesn't verify correct SQL | Remove or make assertion specific |
| M7 | `assembly_resolve` uses inline `JSONResponse` for auth failure instead of `_err_resp` | `dashboard/routers/data.py:2376-2378` | Inconsistent error format | Use `_err_resp` pattern |

## LOW

| # | Finding | File(s) | Impact | Fix |
|---|---------|---------|--------|-----|
| L1 | `TestAssemblyBoardContext.test_wired_into_board_room` reads source file instead of testing behavioral contract | `tests/test_assembly_board_context.py:42-46` | Brittle; breaks on reformatting | Remove; already verified by injection at line 753 |
| L2 | No `ruff` ignores or docstring on `__all__` missing `write_assembly_signal` | `utils/obsidian_sync.py` | Linter cannot detect | Add to `__all__` |
| L3 | `test_resolve_endpoint_requires_write_role` just checks route registration, doesn't assert auth behavior | `tests/test_assembly_drilldown.py:46-52` | Misleading test name | Rename to match what it tests |
