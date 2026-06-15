# Sprint 93 R1 Audit Findings: T-1146 → T-1151
**Date: 2026-06-13 | Reviewer: Kilo Code (3-round review)**

## Summary
- **CRITICAL (2):** #6 resolve_verdicts placeholder, #17 govt_policy_events dedup
- **HIGH (6):** #1 push_to_remote race, #9 per-survey DB call, #12 fragile parser, #18 Kannada villages, #20 scheduler test, #22 .env.example
- **MEDIUM (9):** #2 checksum verify, #5 retry push, #11 market resolution, #15 Cr/L values, #16 keyword matching, #19 parcel linking, #24 CLAUDE.md, #7 indexes, #8 UUID types
- **LOW (4):** #3 encryption doc, #4 timestamp format, #10 hardcoded confidence, #14 pagination
- **CROSS (5):** #23 scheduler logs, #21 integration tests

---

## CRITICAL

### #6 — resolve_verdicts always marks "unverifiable"
**File:** `utils/prediction_ledger.py:93-126`
**Impact:** The spec requires resolve to "compute actuals & set verdict for all pending claims". Current impl marks everything unverifiable — this is a placeholder that defeats the purpose of the prediction ledger.
**Fix:** Add PSF actual-value check from `registered_transactions` table for psf_forecast claims.

### #17 — govt_policy_events may lack source_id UNIQUE constraint
**File:** `scrapers/la_gazette_parser.py:362-415`
**Impact:** The `ON CONFLICT (source_id)` will raise a runtime error if the column has no unique constraint. Migration 0038 created the table without source_id entirely.
**Fix:** Check schema and use headline-based dedup if source_id constraint doesn't exist.

## HIGH

### #1 — push_to_remote races with local backup
**File:** `utils/backup.py:288-325`
**Impact:** Sunday overlap between daily backup (04:00 IST) and offsite push (05:00 IST) may push a stale/incomplete dump.
**Fix:** Share the existing `_backup_lock` with push_to_remote.

### #9 — Per-survey DB call in _market_name_from_id
**File:** `intelligence/opportunity_engine.py:534`
**Impact:** Each high-scoring survey triggers a separate SQL query. With 20+ surveys, this is O(n) in a serial block.
**Fix:** Batch resolve market IDs before the prediction_ledger write loop.

### #12 — HTML regex parsing fragile for tender portal
**File:** `ingest/plugins/tender_plugin.py:107-150`
**Impact:** The eProcurement portal may return JSON or XML. Pure regex HTML parsing misses structured formats.
**Fix:** Add JSON/XML response detection and parsing.

### #18 — Village regex misses Kannada names
**File:** `scrapers/la_gazette_parser.py:313-317`
**Impact:** Real gazettes use Kannada script for village names. The regex `[A-Z][a-z]+` only matches English.
**Fix:** Add broader Unicode matching and a fallback Kannada village list.

### #20 — _build_scheduler() doesn't exist
**File:** `tests/test_gate93.py:21`
**Impact:** `config.scheduler._build_scheduler()` is not a defined function. The scheduler is built inline.
**Fix:** Use static text analysis instead.

### #22 — No .env.example entries for new env vars
**Impact:** `BACKUP_REMOTE`, `LA_GAZETTE_SOURCES` are undocumented.
**Fix:** Add to `.env.example`.

## MEDIUM

### #2 — Full-download verify is wasteful
**File:** `utils/backup.py:328-402`
**Fix:** Use rclone checksum before resorting to full download.

### #5 — No retry for remote push
**File:** `utils/backup.py:304-309`
**Fix:** Add 2-retry exponential backoff.

### #11 — market="unknown" in assembly detector
**File:** `utils/assembly_detector.py:246`
**Fix:** Resolve market from village name.

### #15 — Cr/L suffixes unhandled
**File:** `ingest/plugins/tender_plugin.py:203-209`
**Fix:** Parse "50 Cr" → 500000000.

### #16 — Keyword matching could miss combined forms
**File:** `ingest/plugins/tender_plugin.py:70-76`
**Fix:** Add token-boundary aware matching.

### #19 — No parcel linking
**File:** `scrapers/la_gazette_parser.py:332-350`
**Fix:** Call parcel_linker after upsert for survey_nos.

### #24 — CLAUDE.md not updated
**Fix:** Add GATE-93 status.

## LOW

### #3 — No encryption docs
**File:** `utils/backup.py`
**Fix:** Add docstring noting rclone crypt.

### #4 — Timestamp format fragility
**File:** `utils/backup.py:437`
**Fix:** Handle multiple timestamp formats.

### #10 — Hardcoded confidence 0.6
**File:** `intelligence/opportunity_engine.py:549`
**Fix:** Derive from score delta to threshold.

### #14 — No pagination
**File:** `ingest/plugins/tender_plugin.py`
**Fix:** Document as known limitation.

## CROSS-CUTTING

### #21 — No integration tests for rclone
**Fix:** Add fixture-based integration test.

### #23 — No scheduler log lines for new jobs
**File:** `config/scheduler.py` info block
**Fix:** Add 4 new job logs.
