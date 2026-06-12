# Kaveri Deed Pipeline Log
**Updated: 2026-06-12 | Sprint 91 (GATE-91)**

## Architecture

Two-path deed extraction pipeline:

```
Kaveri Online Services
     │
     ├── 📁 Inbox Mode (primary) ── Jinu manually exports EC search
     │   results → data/kaveri_deeds/inbox/
     │   │
     │   └── KaveriDeedScout (--mode inbox)
     │       → parses PDF/TXT/HTML files
     │       → writes JSON checkpoint
     │       → KaveriDeedsPlugin reads checkpoint
     │       → upserts registered_transactions
     │
     └── 🤖 Live Mode (secondary) ── Playwright automated extraction
         (stub — requires Playwright in agents container)
```

## Inbox Mode

| Step | File | Status |
|------|------|--------|
| Sample files placed by Jinu | `data/kaveri_deeds/samples/` | ✅ 3 EC PDFs (J-12) |
| Village list confirmed | `data/kaveri_deeds/yelahanka_hobli_villages.json` | ✅ 25 villages (J-13) |
| PDF/text parser | `scrapers/kaveri_deeds.py` | ✅ Built, 19 unit tests |
| Survey number extraction | Sprint 80 regex + variants | ✅ Tested on 3 fixture formats |
| Ingest plugin + writer | `ingest/plugins/kaveri_deeds_plugin.py` + writer mapping | ✅ Built, 13 unit tests |
| `registered_transactions` migration | `alembic/versions/0053_registered_transactions.py` | ✅ Built, 5 unit tests |

## Live Mode

| Step | Status | Notes |
|------|--------|-------|
| KaveriDeedScout live mode | 🟡 STUB | Requires Playwright in agents container |
| Session cookie handoff | 🟡 NOT YET | Sprint 77 pattern to be adapted |
| CAPTCHA detection | 🟡 NOT YET | Will fire KAVERI_BLOCKED Discord alert |

Live mode is deferred until the agents container has Playwright installed and
session-cookie infrastructure is adapted from Sprint 77's RERA pattern.

## Scheduler

| Job | Schedule | Status |
|-----|----------|--------|
| `kaveri_deeds_weekly` | Sunday 03:00 IST | ✅ Registered (runs inbox always, live attempt) |
| `weekly_pr_brief` | Monday 07:30 IST | 🧊 FROZEN (GATE-91 diet) |
| `weekly_process_audit` | Sunday 08:30 IST | 🧊 FROZEN (GATE-91 diet) |
| `monthly_ceo_letter` | 1st 09:30 IST | 🧊 FROZEN (GATE-91 diet) |

## Sprint 91 Audit Results (2026-06-12)

Three audit gaps found and fixed:

| Fix | File | Priority |
|-----|------|----------|
| `kaveri_deeds` missing from `PLUGIN_SCHEDULES` | `config/settings.py` | P0 — would have run every weekday |
| `district/taluk/hobli` always empty in plugin output | `ingest/plugins/kaveri_deeds_plugin.py` | P1 — jurisdiction enrichment from village lookup index |
| Missing Karnataka-scale composite index | `alembic/versions/0054_registered_transactions_karnataka_index.py` | P1 — `(sro, taluk, hobli, village, reg_date)` + `(district, reg_date)` |

Inbox files: 3 EC PDFs staged in `data/kaveri_deeds/inbox/` (copied from `samples/`).

## Pending Docker Commands (run when daemon is responsive)

```powershell
# 1. Apply both migrations
docker exec re_os_agents alembic upgrade head

# 2. Run inbox mode on 3 sample PDFs
docker exec re_os_agents python scrapers/kaveri_deeds.py --mode inbox

# 3. Check row count
docker exec re_os_db psql -U re_os_user -d re_os -c "SELECT COUNT(*) FROM registered_transactions;"

# 4. Run gate tests
docker exec re_os_agents pytest tests/test_gate91.py -v
```

## GATE-91 Status

| Assertion | Result |
|-----------|--------|
| (1) `registered_transactions` migration exists (0053) | ✅ |
| (1b) Karnataka composite index migration exists (0054) | ✅ |
| (2) KaveriDeedScout inbox mode parses fixtures → ≥3 records | ✅ |
| (3) `/api/market/spread/{market}` returns 200 | ✅ |
| (4) Org-sim jobs frozen by default | ✅ |
| (5) `kaveri_deeds_weekly` registered | ✅ |
| (6) `PLUGIN_SCHEDULES` includes `kaveri_deeds` | ✅ (P0 fix applied) |
| (7) Plugin enriches `district/taluk/hobli` from village lookup | ✅ (P1 fix applied) |
| Integration: ≥200 registered transactions live | 🟡 PENDING (Docker daemon unresponsive 2026-06-12; 3 PDFs in inbox, run commands above) |

**Gate declared: CONDITIONAL PASS (2026-06-12)**
- All 8 code assertions pass.
- Integration criterion blocked by Docker daemon issue, not implementation.
- Jinu sign-off required to fully close GATE-91.
- Full pass: run pending Docker commands above + place ≥200 rows worth of EC PDFs in inbox.

## 2026-06-12 Integration Run (first run against real PDFs)

Docker restored. All pending commands executed. Results:

| Step | Result |
|------|--------|
| `alembic upgrade head` | ✅ Head at 0056 (after fixing duplicate `idx_parcels_village` in 0055 — see incident postmortem) |
| Inbox parse (3 EC PDFs) | 🟡 3 records parsed (1/PDF), checkpoint written |
| Plugin → `registered_transactions` | ❌ **0 written, 3 failed `doc_no required`** |
| Row count | 0 |

**Root cause — parser does not match real EC Form 15 format.** The 19 unit tests used synthetic fixtures. Real format findings (from `samples/3.pdf`, which contains **2 transactions**, not 1):

1. EC is a 9-column table, one row per transaction; doc_no is column 9 (`BYP-1-14551-2022-23` pattern) — parser never extracts it → validation rejects every record.
2. Village/hobli are inside the property-description cell (`Index-II Village: Venkatala`), not the header (header fields blank, survey masked `3*XX`).
3. Rows span pages — continuation stitching required.
4. Kannada party names come out as `(cid:###)` garbage with raw text extraction.
5. **EC contains non-sale deeds** (Surrender of Lease @ ₹1, Discharge Deed @ ₹20L in 3.pdf). PSF/spread must filter to sale-type deeds — otherwise the spread metric is poisoned by ₹1 considerations.
6. Secondary defect: oversized fallback `source_id` (31K chars) overflows `ingest_log.source_id` varchar(100).

**Fix tasks:** T-1156 (parser rebuild vs real format, hard success criterion on 3.pdf), T-1157 (source_id truncation + SALE_DEED_TYPES filter) — TASK_QUEUE Sprint 91.5.

**GATE-91 remains CONDITIONAL.** The integration criterion did its job: code-level tests were green while the pipeline produced zero usable truth. Do not relax integration criteria on future gates.
