# Sprint 91 — R2 Review (T-1135 → T-1140)
**Reviewer:** Kilo Code | **Date:** 2026-06-12

---

## Fixes Applied in R2

| Finding | Severity | Fix |
|---------|----------|-----|
| MIG-1: Missing SRO index | CRITICAL | Added `idx_registered_transactions_sro_date` |
| MIG-2: No updated_at | CRITICAL | Added `updated_at` column + trigger, `updated_at` in plugin data |
| SCOUT-1: No multi-deed splitting | CRITICAL | Added `_split_deed_sections()` + `_parse_single_deed()` |
| SCOUT-2: False-positive survey_no | CRITICAL | Added false-positive filter regex, narrowed context |
| PLUGIN-1: No ingest_log/engine registration | CRITICAL | Registered in `__init__.py`, scheduler `all_plugins`, engine wiring |
| PLUGIN-2: Confidence propagation | CRITICAL | Already handled by `extraction_confidence != 'low'` in spread query |
| ENDPOINT-1: Missing Pydantic model | CRITICAL | Added `SpreadResponse` BaseModel with Field descriptions |
| DIET-1: No agent_runs in deed job | CRITICAL | Added `INSERT INTO agent_runs` in `run_kaveri_deeds_weekly` |
| DIET-2: Frozen jobs unconditional log | CRITICAL | Conditional `_frozen_tag` logging |
| MED-1: SRO regex multi-line fragile | MEDIUM | Changed to lookahead-based termination |
| MED-2: Checkpoint sort by filename | MEDIUM | Parse timestamp from filename, sort newest-first |
| MED-3: Missing "Rupees" prefix | MEDIUM | Added to `_CONSIDERATION_RE` |
| MED-4: No PDF fixture test | MEDIUM | Added `test_parse_pdf_branch` with mocked `extract_pdf` |
| MED-5: Unused imports | MEDIUM | Removed `random`, `time` |
| MED-6: Falsy-value in plugin fields | MEDIUM | Changed to explicit `is None` checks |
| MED-7: Zero-spread direction | MEDIUM | Added `identical` direction for `spread_pct=0` |
| MED-8: Flaky duplicate job ID test | MEDIUM | Narrowed regex to `add_job(` context only |

## Remaining Risk Register

1. **Live mode stub**: `--mode live` returns empty list. Blocked on Playwright container.
2. **Integration criterion**: `COUNT(*) ≥ 200` requires Jinu inbox data.
3. **Kannada digit extraction**: No Kannada OCR; flagged as `confidence='low'`.

## All Tests: 53 pass, 0 fail, ruff clean
