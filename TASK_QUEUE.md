# TASK_QUEUE.md — RE_OS Atomic Task Queue
**Last updated: 2026-05-15 | Maintained by: Claude Code**

This is the single source of truth for all pending work. Every brain reads this before doing anything.

**How to use:**
1. Scan the INDEX below — find the first `READY` row with your brain name
2. Jump to that task's DETAIL SPEC (search for `## T-XXX`)
3. Read the full spec. Execute exactly as written.
4. Mark DONE in this index. Write one line to CHANGELOG.md.
5. Return to step 1.

---

## TASK INDEX

| ID | Title | Brain | Status | Phase | Blocked By |
|----|-------|-------|--------|-------|------------|
| T-001 | Test news_scout.py standalone | Cline | READY | P1 | — |
| T-002 | Test portal_scout.py standalone | Cline | READY | P1 | — |
| T-003 | Test developer_scout.py standalone | Cline | READY | P1 | — |
| T-004 | Test rera_detail_scout.py standalone | Cline | READY | P1 | — |
| T-005 | Audit scout_memory.py dedup logic | Cline | READY | P1 | — |
| T-006 | Schema audit — verify scout output tables | Cline | READY | P1 | — |
| T-007 | Add httpx + price-parser + dateparser to requirements.txt | Cline | READY | P1 | — |
| T-008 | Wire CEO output to file (intel_report_{ts}.txt) | Cline | READY | P1 | — |
| T-009 | Fix DB upsert — micro_market_id not set in upsert_project | Cline | READY | P0 | — |
| T-010 | Wire sentinel_agent into docker-compose healthcheck | Cline | READY | P1 | — |
| T-011 | Fix errors found in news_scout (from T-001) | Cline | BLOCKED | P1 | T-001 |
| T-012 | Fix errors found in portal_scout (from T-002) | Cline | BLOCKED | P1 | T-002 |
| T-013 | Fix errors found in developer_scout (from T-003) | Cline | BLOCKED | P1 | T-003 |
| T-014 | Fix errors found in rera_detail_scout (from T-004) | Cline | BLOCKED | P1 | T-004 |
| T-015 | Rebuild agents container after requirements change | Cline | BLOCKED | P1 | T-007 |
| T-016 | Wire 4 scouts as tools in scraper_agent.py | Claude | BLOCKED | P1 | T-001,T-002,T-003,T-004 |
| T-017 | Wire scout tools into crew Stage 1 (market_intel_crew.py) | Claude | BLOCKED | P1 | T-016 |
| T-018 | Wire scout outputs into db_organizer.py | Cline | BLOCKED | P1 | T-016 |
| T-019 | Fix analyst LLM loop — calls market_summary_query 4x | Claude | BLOCKED | P2 | T-015 |
| T-020 | CEO report upgrade — 6-section structured brief | Claude | BLOCKED | P1 | T-019 |
| T-021 | Analyst upgrade — 6 signals (velocity, momentum, etc.) | Claude | BLOCKED | P1 | T-020 |
| T-022 | Full integration test — all scouts for Yelahanka | Cline | BLOCKED | P1 | T-017,T-018 |
| T-023 | Expand markets to Devanahalli + Hebbal | Cline | BLOCKED | P2 | T-022 |
| T-024 | DB upsert portal_scout + developer_scout → listings table | Cline | BLOCKED | P2 | T-018 |
| T-025 | Dashboard: wire to PostgreSQL (agent_runs, views) | Claude | BLOCKED | P2 | T-022 |
| T-026 | Dashboard: /api/agents endpoint | Cline | BLOCKED | P2 | T-025 |
| T-027 | Dashboard: /api/tasks endpoint | Cline | BLOCKED | P2 | T-025 |
| T-028 | Dashboard: /api/intel endpoint | Cline | BLOCKED | P2 | T-025 |
| T-029 | Dashboard: /logs/stream SSE endpoint | Cline | BLOCKED | P2 | T-025 |
| T-030 | Dashboard: expose port 8050 in docker-compose.yml | Cline | BLOCKED | P2 | T-025 |
| T-031 | Dashboard: org chart UI component | Claude | BLOCKED | P2 | T-026 |
| T-032 | Dashboard: task board Kanban panel | Cline | BLOCKED | P2 | T-027 |
| T-033 | Dashboard: log stream panel | Cline | BLOCKED | P2 | T-029 |
| T-034 | Scout discoveries dashboard widget | Cline | BLOCKED | P2 | T-022 |
| T-035 | Fix delay_months generated column in schema.sql | Cline | READY | P2 | — |
| T-036 | Kaveri portal — diagnose unreachable URL | Cline | READY | P1 | — |
| T-037 | Agent registry: create agents/registry/ + YAML schema | Claude | BLOCKED | P8 | T-022 |

---

## DETAIL SPECS

---

## T-001 | Test news_scout.py standalone
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH

**What to do:**
1. Run the following command inside the agents container:
   `docker compose exec agents python scrapers/news_scout.py --market Yelahanka`
2. Wait for it to complete (allow up to 3 minutes)
3. Check if an output file was created: look in `outputs/Yelahanka/` for any `news_scout_*.json` or `news_scout_*.jsonl` file
4. If you see a Python traceback or ImportError, copy the full error text into your changelog entry
5. If it runs but returns 0 articles, note that as a partial failure
6. Do NOT attempt to fix any errors found — just document them

**Files to touch:** READ ONLY — `scrapers/news_scout.py`
**Success check:** Command completes without Python traceback AND at least 1 article found in output
**If it fails:** Log the full error type and first line of traceback. Mark T-001 DONE, mark T-011 as READY.
**If it passes:** Mark T-001 DONE. T-011 stays BLOCKED (no fix needed).

**Changelog entry format:**
`T-001 | news_scout standalone test | PASS/FAIL | [0 articles / 5 articles / ImportError xyz] | Cline | YYYY-MM-DD HH:MM`

---

## T-002 | Test portal_scout.py standalone
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH

**What to do:**
1. Run: `docker compose exec agents python scrapers/portal_scout.py --market Yelahanka`
2. Wait up to 5 minutes (Playwright is slow)
3. Check `outputs/Yelahanka/` for portal_scout output file
4. Note: portal_scout scrapes 99acres, MagicBricks, Housing.com — if all 3 return 0 results, that is a selector failure
5. Do NOT fix — document only

**Files to touch:** READ ONLY — `scrapers/portal_scout.py`
**Success check:** Runs without traceback AND at least 1 listing found
**If it fails:** Log error. Mark T-002 DONE, mark T-012 READY.

**Changelog entry format:**
`T-002 | portal_scout standalone test | PASS/FAIL | [N listings found / error summary] | Cline | YYYY-MM-DD HH:MM`

---

## T-003 | Test developer_scout.py standalone
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH

**What to do:**
1. Run: `docker compose exec agents python scrapers/developer_scout.py --developer "Brigade,Prestige" --market Yelahanka`
2. Wait up to 5 minutes
3. Check `outputs/Yelahanka/` for developer_scout output
4. Note: this scrapes Brigade and Prestige developer sites directly
5. Do NOT fix — document only

**Files to touch:** READ ONLY — `scrapers/developer_scout.py`
**Success check:** Runs without traceback AND finds at least 1 project for Brigade or Prestige
**If it fails:** Log error. Mark T-003 DONE, mark T-013 READY.

**Changelog entry format:**
`T-003 | developer_scout standalone test | PASS/FAIL | [N projects found / error summary] | Cline | YYYY-MM-DD HH:MM`

---

## T-004 | Test rera_detail_scout.py standalone
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH

**What to do:**
1. Run: `docker compose exec agents python scrapers/rera_detail_scout.py --market Yelahanka`
2. Wait up to 5 minutes
3. Check `outputs/Yelahanka/` for rera_detail output
4. RERA detail scout enriches existing RERA project records with additional fields
5. Do NOT fix — document only

**Files to touch:** READ ONLY — `scrapers/rera_detail_scout.py`
**Success check:** Runs without traceback AND produces output with at least 1 enriched record
**If it fails:** Log error. Mark T-004 DONE, mark T-014 READY.

**Changelog entry format:**
`T-004 | rera_detail_scout standalone test | PASS/FAIL | [N records enriched / error summary] | Cline | YYYY-MM-DD HH:MM`

---

## T-005 | Audit scout_memory.py dedup logic
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** MEDIUM

**What to do:**
1. Read `scrapers/scout_memory.py` in full
2. Answer these specific questions (write answers in changelog):
   - What is the canonical ID scheme? (e.g., `{source}:{sha16(url)}`)
   - Does it use PostgreSQL or a flat file for dedup storage?
   - Which function checks for duplicates before insertion?
   - Are all 5 scout types (news, portal, developer, rera, kaveri) handled, or only some?
   - Is there any obvious bug (e.g., SHA collision, missing import, wrong table name)?
3. Do NOT edit the file — audit only

**Files to touch:** READ ONLY — `scrapers/scout_memory.py`
**Success check:** You have answered all 5 questions above
**If any question cannot be answered:** Note "UNCLEAR: [question]" in changelog

**Changelog entry format:**
`T-005 | scout_memory audit | DONE | ID={canonical_id_scheme}, storage={postgres/file}, dedup_fn={fn_name}, scouts_covered={list}, bugs={none/description} | Cline | YYYY-MM-DD HH:MM`

---

## T-006 | Schema audit — verify scout output tables
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** MEDIUM

**What to do:**
1. Read `database/schema.sql` in full
2. Check which of these tables exist (exact names matter):
   - `news_articles` or equivalent for news_scout output
   - `portal_listings` or `listings` for portal_scout output
   - `developer_projects` or equivalent for developer_scout output
   - `rera_project_details` or equivalent for rera_detail_scout output
   - `scout_memory` or `dedup_log` for scout_memory.py
3. For each table: note exact name if found, or "MISSING" if not found
4. Do NOT edit anything

**Files to touch:** READ ONLY — `database/schema.sql`
**Success check:** You have checked all 5 table types and logged findings
**If tables are missing:** Mark T-006 DONE. Claude will add missing tables in next review cycle.

**Changelog entry format:**
`T-006 | schema audit | DONE | news={found/MISSING}, portal={found/MISSING}, developer={found/MISSING}, rera_detail={found/MISSING}, scout_memory={found/MISSING} | Cline | YYYY-MM-DD HH:MM`

---

## T-007 | Add httpx + price-parser + dateparser to requirements.txt
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** MEDIUM

**What to do:**
1. Read `requirements.txt` in full first
2. Check if these packages already exist (any version): `httpx`, `price-parser`, `dateparser`
3. For any that are MISSING, add them on a new line at the bottom of requirements.txt:
   ```
   httpx>=0.27.0
   price-parser>=0.3.4
   dateparser>=1.2.0
   ```
4. If a package already exists at a lower version, update it to the minimum above
5. Save the file. Do NOT rebuild the container yet — T-015 does that.

**Files to touch:** READ+WRITE — `requirements.txt`
**Success check:** All 3 packages present in requirements.txt at correct minimum versions
**If any already exists at correct version:** Note "already present" — do not duplicate

**Changelog entry format:**
`T-007 | requirements.txt | added httpx/price-parser/dateparser (or noted existing) | Cline | YYYY-MM-DD HH:MM`

---

## T-008 | Wire CEO output to file (intel_report_{ts}.txt)
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** MEDIUM

**What to do:**
1. Read `crews/market_intel_crew.py` in full first
2. Find where the CEO agent's final output/result is printed to terminal (look for `print(result)` or similar)
3. Immediately after that print statement, add code to write the same output to a file:
   ```python
   from pathlib import Path
   from datetime import datetime
   output_dir = Path(f"outputs/{market}")
   output_dir.mkdir(parents=True, exist_ok=True)
   ts = datetime.now().strftime("%Y%m%d_%H%M%S")
   report_path = output_dir / f"intel_report_{ts}.txt"
   report_path.write_text(str(result), encoding="utf-8")
   print(f"[CEO] Report saved to {report_path}")
   ```
4. The `market` variable should already exist in scope — use it. If not, use the `--market` CLI argument value.
5. Do not change any other logic.

**Files to touch:** READ+WRITE — `crews/market_intel_crew.py`
**Success check:** Code compiles (no syntax errors) and writes to `outputs/{market}/intel_report_{ts}.txt`
**If `market` variable scope is unclear:** Log "SCOPE UNCLEAR: [what you saw]" and mark NEEDS-CLARIFICATION

**Changelog entry format:**
`T-008 | crews/market_intel_crew.py | wired CEO output to outputs/{market}/intel_report_{ts}.txt | Cline | YYYY-MM-DD HH:MM`

---

## T-009 | Fix DB upsert — micro_market_id not set in upsert_project
**Status:** READY
**Brain:** Cline
**Phase:** P0
**Blocked by:** —
**Priority:** HIGH

**What to do:**
1. Read `utils/db_organizer.py` in full first
2. Find the `_upsert_project` function (or whichever function handles `ON CONFLICT DO UPDATE` for rera_projects)
3. Look at the `ON CONFLICT DO UPDATE SET` clause — check if `micro_market_id` is in the SET list
4. If `micro_market_id` is missing from the SET clause, add it: `micro_market_id = EXCLUDED.micro_market_id`
5. Save. Do not change any other logic.

**Files to touch:** READ+WRITE — `utils/db_organizer.py`
**Success check:** `micro_market_id = EXCLUDED.micro_market_id` is present in the ON CONFLICT SET clause
**If the function doesn't exist or the structure is different:** Log what you found, mark NEEDS-CLARIFICATION

**Changelog entry format:**
`T-009 | utils/db_organizer.py | added micro_market_id to ON CONFLICT SET clause | Cline | YYYY-MM-DD HH:MM`

---

## T-010 | Wire sentinel_agent into docker-compose healthcheck
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** LOW

**What to do:**
1. Read `docker-compose.yml` in full first
2. Read `agents/sentinel_agent.py` — find its main entry point (what runs when called as a script)
3. In `docker-compose.yml`, find the `agents` service
4. Add or update a `healthcheck` block to the `agents` service:
   ```yaml
   healthcheck:
     test: ["CMD", "python", "/app/agents/sentinel_agent.py"]
     interval: 60s
     timeout: 30s
     retries: 3
     start_period: 30s
   ```
5. If sentinel_agent.py does not have a `if __name__ == "__main__":` block that exits 0 on success and 1 on failure, note this — the healthcheck will not work correctly.

**Files to touch:** READ+WRITE — `docker-compose.yml` | READ ONLY — `agents/sentinel_agent.py`
**Success check:** `docker compose ps` shows the agents container health check defined (after `docker compose up -d`)
**If sentinel_agent has no main block:** Log "sentinel_agent.py has no health-check-compatible main block — T-010 BLOCKED" and mark NEEDS-CLARIFICATION

**Changelog entry format:**
`T-010 | docker-compose.yml | added sentinel healthcheck to agents service | Cline | YYYY-MM-DD HH:MM`

---

## T-011 | Fix errors found in news_scout (from T-001)
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P1
**Blocked by:** T-001
**Priority:** HIGH

**What to do:**
This task is created after T-001 fails. When T-001 is marked DONE with status FAIL:
1. Read T-001's changelog entry to get the exact error
2. Read `scrapers/news_scout.py` in full
3. Fix the specific error reported — ONLY that error, nothing else
4. Common errors to expect:
   - `ImportError: No module named 'httpx'` → add to requirements.txt (T-007 should handle this)
   - `KeyError: 'GEMINI_API_KEY'` → key not in .env — check `.env` file, report to Jinu
   - Playwright browser not found → run `docker compose exec agents playwright install chromium`
   - RSS feed URL changed → update the hardcoded URL in news_scout.py
5. After fix: re-run T-001's command and check if it now passes

**Files to touch:** READ+WRITE — `scrapers/news_scout.py` (only the specific error fix)
**Success check:** Same command from T-001 now runs without the reported error
**If error requires architecture change:** Mark NEEDS-CLARIFICATION for Claude review

**Changelog entry format:**
`T-011 | scrapers/news_scout.py | fixed [error type]: [one-line description] | Cline | YYYY-MM-DD HH:MM`

---

## T-012 | Fix errors found in portal_scout (from T-002)
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P1
**Blocked by:** T-002
**Priority:** HIGH

**What to do:**
Same pattern as T-011 but for `scrapers/portal_scout.py`.
1. Read T-002's changelog entry to get the exact error
2. Read `scrapers/portal_scout.py` in full
3. Fix the specific error only
4. Common portal scout errors:
   - Playwright selector `[data-type="listing"]` → inspect real 99acres DOM and update selector
   - Rate limiting → add a `time.sleep(2)` between requests
   - No results (0 listings) → verify the search URL format for Yelahanka is correct
5. Re-run T-002's command to verify fix

**Files to touch:** READ+WRITE — `scrapers/portal_scout.py`
**Success check:** Portal scout runs without traceback AND returns at least 1 listing
**Changelog entry format:**
`T-012 | scrapers/portal_scout.py | fixed [error type]: [one-line description] | Cline | YYYY-MM-DD HH:MM`

---

## T-013 | Fix errors found in developer_scout (from T-003)
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P1
**Blocked by:** T-003
**Priority:** HIGH

Same pattern as T-011 but for `scrapers/developer_scout.py`. Read T-003 log, fix that specific error only, verify with same command.

**Changelog entry format:**
`T-013 | scrapers/developer_scout.py | fixed [error type]: [one-line description] | Cline | YYYY-MM-DD HH:MM`

---

## T-014 | Fix errors found in rera_detail_scout (from T-004)
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P1
**Blocked by:** T-004
**Priority:** HIGH

Same pattern as T-011 but for `scrapers/rera_detail_scout.py`. Read T-004 log, fix that specific error only.

**Changelog entry format:**
`T-014 | scrapers/rera_detail_scout.py | fixed [error type]: [one-line description] | Cline | YYYY-MM-DD HH:MM`

---

## T-015 | Rebuild agents container after requirements change
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P1
**Blocked by:** T-007
**Priority:** MEDIUM

**What to do:**
1. Verify T-007 is marked DONE before running this
2. Run: `docker compose build agents`
3. Wait for build to complete (can take 5–10 minutes)
4. Run: `docker compose up -d agents`
5. Verify container is running: `docker compose ps`
6. Quick smoke test: `docker compose exec agents python -c "import httpx, price_parser, dateparser; print('OK')"`
   - If prints OK: success
   - If ImportError: the build did not include the new requirements — note which package failed

**Files to touch:** None (command only)
**Success check:** `docker compose exec agents python -c "import httpx, price_parser, dateparser; print('OK')"` prints OK
**If build fails:** Log the build error line, mark NEEDS-FIX

**Changelog entry format:**
`T-015 | container rebuild | PASS/FAIL | [build duration or error] | Cline | YYYY-MM-DD HH:MM`

---

## T-016 | Wire 4 scouts as tools in scraper_agent.py
**Status:** BLOCKED
**Brain:** Claude
**Phase:** P1
**Blocked by:** T-001, T-002, T-003, T-004
**Priority:** HIGH

This is a Claude task. Triggered during review cycle after all 4 scout tests pass.
Claude reads the 4 scout files, understands their interfaces, and adds them as CrewAI tools to `agents/scraper_agent.py`.

---

## T-017 | Wire scout tools into crew Stage 1 (market_intel_crew.py)
**Status:** BLOCKED
**Brain:** Claude
**Phase:** P1
**Blocked by:** T-016
**Priority:** HIGH

Claude task. After T-016, wire the new scraper_agent tools into the Stage 1 task definitions in `crews/market_intel_crew.py`.

---

## T-018 | Wire scout outputs into db_organizer.py
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P1
**Blocked by:** T-016
**Priority:** HIGH

**What to do:** (Full spec to be written by Claude after T-016 is complete — Cline should check back after T-016 is DONE)

---

## T-019 | Fix analyst LLM loop — calls market_summary_query 4x
**Status:** BLOCKED
**Brain:** Claude
**Phase:** P2
**Blocked by:** T-015
**Priority:** MEDIUM

Claude task. Prompt tightening in `agents/analyst_agent.py` to prevent repeated tool calls.

---

## T-020 | CEO report upgrade — 6-section structured brief
**Status:** BLOCKED
**Brain:** Claude
**Phase:** P1
**Blocked by:** T-019
**Priority:** HIGH

Claude task. Upgrade CEO output format. See `plans/MASTER_PLAN.md` Phase 1 for section spec.

---

## T-021 | Analyst upgrade — 6 signals
**Status:** BLOCKED
**Brain:** Claude
**Phase:** P1
**Blocked by:** T-020
**Priority:** HIGH

Claude task. Add 6 signal calculations to analyst: velocity, momentum, delivery score, supply pressure, GV gap, launch lag. See `plans/MASTER_PLAN.md`.

---

## T-022 | Full integration test — all scouts for Yelahanka
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P1
**Blocked by:** T-017, T-018
**Priority:** HIGH

**What to do:**
1. Run: `docker compose exec agents python crews/market_intel_crew.py --market Yelahanka`
2. Watch `logs/crew.log` for errors: `Get-Content logs/crew.log -Wait -Tail 50`
3. After completion, check: `outputs/Yelahanka/intel_report_*.txt` exists AND has content
4. Check DB: `docker compose exec re_os_db psql -U re_os_user -d re_os -c "SELECT COUNT(*) FROM rera_projects;"`
5. Log: run duration, record counts, any errors seen in log

**Files to touch:** None (command only)
**Success check:** Full pipeline runs without fatal error AND intel_report file exists AND DB has >0 rera_projects

**Changelog entry format:**
`T-022 | full integration test Yelahanka | PASS/FAIL | [duration, record counts, errors] | Cline | YYYY-MM-DD HH:MM`

---

## T-023 | Expand markets to Devanahalli + Hebbal
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-022
**Priority:** MEDIUM

**What to do:**
1. Verify T-022 passed for Yelahanka
2. Run: `docker compose exec agents python crews/market_intel_crew.py --market Devanahalli`
3. Wait for completion. Check output.
4. Run: `docker compose exec agents python crews/market_intel_crew.py --market Hebbal`
5. Log results for both

**Changelog entry format:**
`T-023 | market expansion | Devanahalli=PASS/FAIL, Hebbal=PASS/FAIL | [errors if any] | Cline | YYYY-MM-DD HH:MM`

---

## T-024 | DB upsert portal_scout + developer_scout → listings table
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-018
**Priority:** MEDIUM

Full spec to be written by Claude after T-018 is complete.

---

## T-025 | Dashboard: wire to PostgreSQL (agent_runs, views)
**Status:** BLOCKED
**Brain:** Claude
**Phase:** P2
**Blocked by:** T-022
**Priority:** HIGH

Claude task. Wire `dashboard/app.py` to live DB. Read `agent_runs`, `v_market_brief`, `v_active_projects`.

---

## T-026 | Dashboard: /api/agents endpoint
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-025
**Priority:** HIGH

Full spec to be written by Claude after T-025.

---

## T-027 | Dashboard: /api/tasks endpoint
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-025
**Priority:** HIGH

Full spec to be written by Claude after T-025.

---

## T-028 | Dashboard: /api/intel endpoint
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-025
**Priority:** HIGH

Full spec to be written by Claude after T-025.

---

## T-029 | Dashboard: /logs/stream SSE endpoint
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-025
**Priority:** MEDIUM

Full spec to be written by Claude after T-025.

---

## T-030 | Dashboard: expose port 8050 in docker-compose.yml
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-025
**Priority:** MEDIUM

**What to do (spec is complete — unblock when T-025 is DONE):**
1. Read `docker-compose.yml`
2. Find the `agents` service
3. Add port mapping if not present: `"8050:8050"` under `ports:`
4. Read `dashboard/app.py` — confirm it runs on port 8050 (`app.run(host='0.0.0.0', port=8050)`)
5. If app.py uses a different port, update both to match: 8050

**Changelog entry format:**
`T-030 | docker-compose.yml | exposed port 8050 for dashboard | Cline | YYYY-MM-DD HH:MM`

---

## T-031 | Dashboard: org chart UI component
**Status:** BLOCKED
**Brain:** Claude
**Phase:** P2
**Blocked by:** T-026
**Priority:** HIGH

Claude task. Build org chart HTML/CSS/JS component driven by `/api/agents` endpoint.

---

## T-032 | Dashboard: task board Kanban panel
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-027
**Priority:** MEDIUM

Full spec to be written by Claude after T-027.

---

## T-033 | Dashboard: log stream panel
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-029
**Priority:** MEDIUM

Full spec to be written by Claude after T-029.

---

## T-034 | Scout discoveries dashboard widget
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-022
**Priority:** LOW

Full spec to be written by Claude after T-022.

---

## T-035 | Fix delay_months generated column in schema.sql
**Status:** READY
**Brain:** Cline
**Phase:** P2
**Blocked by:** —
**Priority:** LOW

**What to do:**
1. Read `database/schema.sql` — find the `delay_months` column definition (~line 134)
2. Check if it is defined as a GENERATED ALWAYS AS column
3. If yes: note the formula being used
4. DO NOT change it yet — this only fails on DB wipe. Just verify current state and log.
5. If the DB is currently healthy (no wipe since last run), mark as VERIFIED-OK

**Files to touch:** READ ONLY — `database/schema.sql`
**Success check:** You have confirmed whether the column is GENERATED or computed elsewhere

**Changelog entry format:**
`T-035 | schema.sql delay_months | VERIFIED-OK/FOUND-ISSUE: [description] | Cline | YYYY-MM-DD HH:MM`

---

## T-036 | Kaveri portal — diagnose unreachable URL
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** LOW

**What to do:**
1. Read `scrapers/kaveri_karnataka.py` — find the URL it tries to reach
2. Run: `docker compose exec agents python -c "import requests; r=requests.get('[URL_FROM_FILE]', timeout=10); print(r.status_code)"`
   (replace [URL_FROM_FILE] with the actual URL)
3. If you get a connection error or non-200, try the URL in a browser and note what happens
4. Log: the URL being used, the HTTP status or error, and whether the portal exists at a different URL
5. DO NOT attempt to fix — diagnose only

**Files to touch:** READ ONLY — `scrapers/kaveri_karnataka.py`
**Success check:** You have the URL, the HTTP response status, and a note on whether the portal is reachable

**Changelog entry format:**
`T-036 | kaveri portal diagnosis | URL=[url], status=[http_status or error], reachable=[yes/no] | Cline | YYYY-MM-DD HH:MM`

---

## T-037 | Agent registry: create agents/registry/ + YAML schema
**Status:** BLOCKED
**Brain:** Claude
**Phase:** P8
**Blocked by:** T-022
**Priority:** MEDIUM

Claude task. Create the agent registry folder, YAML schema, and `agents/agent_factory.py`. Full spec in VISION.md Phase 8.

---

## ADDING NEW TASKS

When a review cycle reveals new work, Claude adds tasks here following the spec format above.
Claude assigns the next available T-XXX number and inserts the row in the INDEX + writes the DETAIL SPEC.

**Current last task ID: T-037**
**Next task ID to use: T-038**

---

*This file is the ground truth for all pending work. VISION.md has the strategic picture. AGENTS.md has the protocol. TASK_QUEUE.md has the jobs.*
