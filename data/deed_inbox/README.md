# RE_OS — Deed Inbox

Place **Form17 Index II** and **EC (Encumbrance Certificate)** PDFs here for automatic ingestion into `registered_transactions`.

---

## Where to download

### Form17 Index II (Bhoomi/RTC portal — bulk deed extract)
- URL: https://landrecords.karnataka.gov.in/
- Search by: SRO → Taluk → Hobli → Village
- Select any date range (system aggregates)
- **₹50 per report** — paid download, PDF delivered immediately
- File naming: any `.pdf` extension works

### EC (Encumbrance Certificate — Kaveri Online Services)
- URL: https://kaverionline.karnataka.gov.in/
- Requires citizen login (OTP)
- Search by property / survey number
- **₹50 per EC (Form 15)** — paid download
- File naming: any `.pdf` extension works

---

## Processing schedule

- **Automatic**: Monday 05:00 IST (`kaveri_weekly_orchestration` job in scheduler)
- **Immediate (Form17 only)**: `docker compose exec agents python scripts/process_deed_inbox.py --form17 --max-files 50`
- **Immediate (all types)**: `docker compose exec agents python scripts/process_deed_inbox.py --form17 --ec --max-files 50`

---

## Dedup behavior

Every PDF is watermarked by **SHA-256 hash** of its content. Processing the same file twice has no effect — the pipeline logs `already processed` and skips it.

---

## File integrity

- Only well-formed PDF files are accepted — corrupted or truncated files are skipped with a WARNING log entry
- **Max file size**: 50 MB per PDF (larger files rejected with a clear error)
- **Max batch**: 200 files per run (override with `--max-files N`)
- Non-PDF files in the directory are silently ignored

---

## If something fails

1. Check the pipeline logs: `docker compose exec agents python -c "from utils.db import get_engine; from sqlalchemy import text; e=get_engine(); print(e.execute(text(\"SELECT event_type, status, message FROM agent_runs WHERE agent_id='form17_inbox_scan' ORDER BY started_at DESC LIMIT 5\")).fetchall())"`
2. Verify PDF is valid (open in any PDF reader)
3. Check Discord `#re-os-health` for pipeline alerts
4. If all else fails, post in the project channel with the output from step 1

---

## Notes

- Files placed here are **not committed to git** (`data/deed_inbox/*.pdf` is gitignored)
- Only `.pdf` files are scanned — subdirectories are ignored
- The `process_deed_inbox.py` script can also process `--ec` (Encumbrance Certificate) files alongside Form17
