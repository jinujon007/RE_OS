# Sprint 91 — R1 Audit (T-1135 → T-1140)
**Reviewer:** Kilo Code | **Date:** 2026-06-12
**Scope:** Complete code + test + docs output for Kaveri Deed Truth sprint

---

## Critical Findings (must fix)

### MIG-1: Migration missing SRO+district+taluk query index
`0053_registered_transactions.py` defines indexes for `(village, reg_date)` and `(survey_no)` but NOT for `(sro, district, taluk)`. The `compute_psf_spread` query in `psf_truth.py` uses `village ILIKE` (which IS indexed), but the UNIQUE key on `(sro, doc_no, reg_date)` has no supporting index for lookups by `sro` alone. At Karnataka scale (millions of deeds), SRO-based queries without a dedicated index will seq-scan. **Fix:** Add index on `(sro, reg_date)`.

### MIG-2: No `updated_at` column
`registered_transactions` has `created_at` but no `updated_at`. The writer upserts with `ON CONFLICT DO UPDATE SET ...` but nothing tracks when a row was last modified. **Fix:** Add `updated_at TIMESTAMPTZ DEFAULT NOW()` with auto-update trigger or application-level update.

### SCOUT-1: `_parse_pdf_text` does not handle multi-deed EC PDFs
The docstring claims the function handles "multiple deeds" but the implementation only extracts a single set of fields from the full text. A real Kaveri EC PDF can contain 5-15 deeds. **Fix:** Split text on "Document No" boundaries and process each section independently.

### SCOUT-2: `_SURVEY_NO_DIRECT_RE` false-positive on addresses
The fallback regex `(?<!\w)(\d{1,4}/(?:[\dA-Za-z]{1,3}(?:[-/][\dA-Za-z]{1,3})*))(?:\s|,|;|\.|$)` can match pincodes (560/102), dates (15/05/2026), and fractions in area descriptions. **Fix:** Narrow the fallback context: only search within property-description section, add negative lookahead for year-like patterns.

### PLUGIN-1: No ingest_log integration
The spec says "Rows logged to `ingest_log`" but the plugin does NOT write to `ingest_log`. The writer handles upserts but the plugin never logs the fact that a run occurred. **Fix:** Insert ingest_log row after processing checkpoint.

### PLUGIN-2: `extraction_confidence` overwrite in psf_truth
`compute_psf_spread` only filters `extraction_confidence != 'low'` for registered_transactions but the buyer_type and PSF logic in the plugin does not propagate confidence degradation through the data pipeline. Low-confidence deeds quietly appear in the spread calculation with partial data. **Fix:** Add confidence filtering in spread computation.

### ENDPOINT-1: Missing Pydantic response model
All other production endpoints use Pydantic `BaseModel` for response serialization (pattern established in GATE-90, T-1130). The spread endpoint returns a raw dict from `SpreadResult.to_dict()`. **Fix:** Define `SpreadResponse` Pydantic model.

### ENDPOINT-2: No auth on read-only endpoint
The new `/api/market/spread/{market}` endpoint falls under the `/api/market/` prefix in `_READ_ONLY_PREFIXES` so it bypasses auth. This is correct for read-only but there's no rate-limit error handling or fallback when the user exceeds `60/hour`. **Fix:** Add `RateLimitExceeded` handler scope visibility (minor).

### DIET-1: `run_kaveri_deeds_weekly` does not log to `agent_runs`
All other scheduler jobs have agent_runs integration. The new deed job is a ghost — no visibility in the scheduler dashboard or agent_runs table. **Fix:** Add agent_runs INSERT.

### DIET-2: Frozen jobs still appear in start-up log
The `logger.info` lines at scheduler startup still unconditionally log PR brief, process audit, and CEO letter as scheduled jobs regardless of `SCHEDULER_ENABLE_ORG_SIM`. **Fix:** Conditionally log these lines.

---

## Medium Findings (should fix)

### MED-1: SRO regex fragile
`_SRO_RE` uses `(.+?)(?:\n|$)` which captures only until newline. Multi-line SRO names (e.g., "Sub Registrar\nYelahanka") will truncate. **Fix:** Broad capture to next labeled field.

### MED-2: `_read_checkpoint` sorts by filename — wrong for multi-run
`_read_checkpoint` sorts checkpoint files alphabetically. With `kaveri_deeds_inbox_20260612_093000.json` and `_20260612_100000.json`, alphabetical sort works, but if the timestamp format changes or old files remain, wrong checkpoint may load. **Fix:** Parse timestamp from filename and sort by actual creation order.

### MED-3: `_CONSIDERATION_RE` regex misses "Rupees" prefix
The regex accepts `Rs.`/`INR`/`₹`/`Consideration`/`Amount` but NOT the word "Rupees". Many Indian documents use "Rupees 85,00,000". **Fix:** Add `Rupees` to prefix alternatives.

### MED-4: Test coverage gap — no PDF fixture
All 50 tests use `.txt` fixture files. The PDF parsing path (via `extract_pdf`) has zero test coverage. If `pdfplumber` ever fails or returns unexpected structure, the pipeline breaks silently. **Fix:** Add a unit test that at minimum validates the file-type branching in `parse_inbox_file`.

### MED-5: `main()` runs argparse but module-level unused imports
`random` and `time` imported at module top but never used (the live mode stub doesn't use them). **Fix:** Remove unused imports.

### MED-6: No test for edge case — empty strings in required fields
`_build_record` converts `doc_no` to `str(raw.get("doc_no") or "")` which treats empty string as falsy. But what if `doc_no` is `"0"` (falsy in Python)? **Fix:** Explicit `is None` checks for numeric-like fields.

### MED-7: `SpreadResult.one_line_summary` uses `direction` logic missing zero case
When `spread_pct = 0` (identical medians), the result says "0.0% wider" — semantically incorrect (it means no spread, not wider). **Fix:** Add `no_spread` direction for 0% difference.

### MED-8: Test `test_no_duplicate_job_ids` is flaky
The regex `r'id="([^"]+)"'` matches ALL double-quoted strings after `id=`, including in comments or docstrings. A false positive could hide a real duplicate. **Fix:** Only match `id=` within `add_job(` context.

---

## Minor Findings (nice to have)

### MIN-1: Docstring in `_parse_pdf_text` claims multi-deed support but doesn't deliver
The docstring says "A single EC PDF may contain multiple deeds. This function splits on document boundaries" — but the code doesn't split. Misleading docstring.

### MIN-2: `_parse_pdf_text` extracts `lines` variable that's never used
`lines = pdf_text.split("\n")` on line 199 is dead code — not used anywhere in the function.

### MIN-3: `test_migration_0053.py` line 33 assertion too loose
`assert "create_table" in content` matches the literal word in a comment or column definition — not ideal.

### MIN-4: Deed pipeline log has `≥20 records` in spec but test asserts `≥3`
The GATE-91 spec says "≥20 records from J-12 samples" but the test asserts `≥3` from 3 fixture files. While appropriate for unit testing, the doc should note the difference.

### MIN-5: No `.gitignore` for inbox/checkpoint files
`data/kaveri_deeds/inbox/` and `data/kaveri_deeds/checkpoints/` may contain data files that shouldn't be committed. No `.gitignore` entry exists.

### MIN-6: `_READ_ONLY_PREFIXES` comment should mention spread endpoint
The comment in `app_fastapi.py` says `/api/market/` prefix covers market endpoints — explicitly listing the spread endpoint would help future maintainers.

---

## Summary

| Severity | Count | IDs |
|----------|-------|-----|
| CRITICAL | 10 | MIG-1, MIG-2, SCOUT-1, SCOUT-2, PLUGIN-1, PLUGIN-2, ENDPOINT-1, DIET-1, DIET-2, DIET-2 |
| MEDIUM | 8 | MED-1 through MED-8 |
| MINOR | 6 | MIN-1 through MIN-6 |
| **Total** | **24** | |
