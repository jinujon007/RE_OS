# TASK_QUEUE.md — RE_OS Atomic Task Queue
**Last updated: 2026-05-15 | Maintained by: Claude Code**

This is the single source of truth for all pending work. Every brain reads this before doing anything.

**How to use:**
1. Scan the INDEX below — find the first `READY` row with your brain name
2. Jump to that task's DETAIL SPEC (search for `## T-XXX`)
3. Read the full spec. Note the **Recommended Model** line — set that model in Cline before starting.
4. Mark DONE in this index. Write one line to CHANGELOG.md.
5. Return to step 1.

---

## MODEL ROUTING — Which model for which task

Never let Cline ask you to switch to Sonnet. Every task here is sized for a free model.
**If Cline suggests Sonnet:** stop, check the task tier below, switch to the right free model first.
**If Cline throws a tool-call error:** switch to Groq `llama-3.3-70b-versatile` — it handles tool calls most reliably of all free models.

**How Cline model switching works:**
Cline has two separate modes — Plan mode (thinks through the task) and Act mode (executes tool calls). You can set a different model for each. Every task spec has a `Plan:` and `Act:` line. You switch them manually in Cline before saying go.

**Your available providers:**
| Provider | What it routes to | Cost |
|----------|------------------|------|
| **Ollama** | Local models on your machine | Free, unlimited, slower |
| **OpenRouter** | DeepSeek, Llama, Gemini Flash, etc. | Free tier |
| **NinRouter** | NVIDIA models + Ollama + OpenRouter + OpenAI Codex | Codex = paid, rest free |
| **Hugging Face** | HF-hosted models | Coming soon |

**Model routing per task tier:**

| Tier | What it involves | Plan Mode | Act Mode |
|------|-----------------|-----------|----------|
| **T0 — Read-only** | Read file, audit, no edits | Ollama (any local model) | Ollama (same) |
| **T1 — Tiny edit** | 1–10 line change, exact spec given | OpenRouter free | OpenRouter free |
| **T2 — Commands** | Docker exec, run script, verify | OpenRouter free | OpenRouter free |
| **T3 — Code edit** | 10–50 lines, logic change, single file | NinRouter → Codex | OpenRouter free |
| **T4 — Scraper/debug** | Fix scraper, HTML, multi-step debug | NinRouter → Codex | NinRouter → Codex |
| **T5 — Architecture** | Multi-file, new feature | → Claude Code | Not a Cline task |

**Why Plan ≠ Act for T3/T4:**
Plan mode needs Codex to *understand* the codebase pattern and reason about the right fix. Act mode just needs to reliably write the file — OpenRouter free models handle that without burning Codex tokens.

**Fallback:**
- Ollama unavailable → OpenRouter free (T0)
- OpenRouter rate-limited → Ollama local (T1/T2)
- Codex quota → OpenRouter `deepseek/deepseek-v3:free` for Plan, OpenRouter free for Act

**Kilo Code:** Uses its built-in free default for both modes. No switching needed. T0 tasks only.
**If Cline suggests Sonnet:** wrong model set. Switch Plan → NinRouter Codex (T3/T4) or OpenRouter (T1/T2). Switch Act → OpenRouter free. Never need Sonnet.

---

## TASK INDEX

| ID | Title | Brain | Status | Phase | Blocked By |
|----|-------|-------|--------|-------|------------|
| T-001 | Test news_scout.py standalone | Cline | DONE | P1 | — |
| T-002 | Test portal_scout.py standalone | Cline | DONE | P1 | — |
| T-003 | Test developer_scout.py standalone | Cline | DONE | P1 | — |
| T-004 | Test rera_detail_scout.py standalone | Cline | DONE | P1 | — |
| T-005 | Audit scout_memory.py dedup logic | Cline | DONE | P1 | — |
| T-006 | Schema audit — verify scout output tables | Cline | DONE | P1 | — |
| T-007 | Add httpx + price-parser + dateparser to requirements.txt | Cline | DONE | P1 | — |
| T-008 | Wire CEO output to file (intel_report_{ts}.txt) | Cline | DONE | P1 | — |
| T-009 | Fix DB upsert — micro_market_id not set in upsert_project | Cline | DONE | P0 | — |
| T-010 | Wire sentinel_agent into docker-compose healthcheck | Cline | BLOCKED | P1 | sentinel_agent.py healthcheck entrypoint |
| T-011 | Fix news_scout empty results | Cline | SKIP | P1 | Superseded by T-041 |
| T-012 | Fix errors found in portal_scout (from T-002) | Cline | SKIP | P1 | T-002 passed — no fix needed |
| T-013 | Fix developer_scout Playwright 0 projects | Claude | SKIP | P1 | Superseded by T-042 |
| T-014 | Fix rera_detail_scout — no checkpoint data | Claude | BLOCKED | P1 | T-040 |
| T-015 | Rebuild agents container after requirements change | Cline | READY | P1 | — |
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
| T-038 | Diagnose news_scout.py — root cause for 0 articles | Kilo Code | DONE | P1 | — |
| T-039 | Diagnose developer_scout.py — root cause for 0 projects | Kilo Code | DONE | P1 | — |
| T-040 | Diagnose rera_detail_scout.py — checkpoint prerequisite | Kilo Code | READY | P1 | — |
| T-041 | Fix news_scout empty results (after T-038 diagnosis) | Cline | DONE | P1 | — |
| T-042 | Fix developer_scout Playwright failure (after T-039) | Claude | READY | P1 | — |

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
**Status:** DONE ✅
**Brain:** Cline (fixed by Roo Code 2026-05-14 00:20 IST)
**Phase:** P0
**Blocked by:** —
**Priority:** HIGH

**Resolution:** Fixed in CHANGELOG session 2026-05-14. `micro_market_id = EXCLUDED.micro_market_id` confirmed present in `utils/db_organizer.py` `_upsert_project` function. No action needed.

---

## T-010 | Wire sentinel_agent into docker-compose healthcheck
**Status:** BLOCKED (NEEDS-CLARIFICATION)
**Brain:** Cline
**Phase:** P1
**Blocked by:** sentinel_agent.py lacks health-check-compatible `__main__` entrypoint
**Priority:** LOW
**Task Tier:** T1 — Tiny edit (add healthcheck block to docker-compose.yml)
**Plan mode:** OpenRouter → any free model (e.g., `deepseek/deepseek-chat-v3-0324:free`)
**Act mode:** OpenRouter → same free model

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

**Current state (2026-05-15):** healthcheck block added to `docker-compose.yml` agents service. `sentinel_agent.py` has no `if __name__ == "__main__":` block with exit-code behavior, so Docker healthcheck command is not yet valid for PASS/FAIL signaling.

---

## T-011 | Fix news_scout empty results
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P1
**Blocked by:** T-038 (diagnosis required before fix)
**Priority:** HIGH
**Task Tier:** T3 — Code edit (update URL or query params in news_scout.py)
**Recommended Model:** OpenRouter `deepseek/deepseek-chat-v3-0324:free`

**Context:** T-001 ran successfully (no traceback) but returned 0 articles. Google News RSS and ET Realty both returned empty. T-038 will diagnose the exact URL/query issue. Once T-038 is DONE, read its CHANGELOG entry and apply the specific fix it identifies.

**What to do (after T-038 is DONE):**
1. Read T-038's CHANGELOG entry to get the exact diagnosis
2. Read `scrapers/news_scout.py` — find the RSS URL and ET Realty URL/query
3. Apply only the fix described in T-038 findings (likely: update URL, fix market keyword substitution, or add search fallback)
4. Re-run: `docker compose exec agents python scrapers/news_scout.py --market Yelahanka`
5. Verify: at least 1 article returned

**Files to touch:** READ+WRITE — `scrapers/news_scout.py`
**Success check:** Command returns at least 1 article with no traceback
**If fix requires architecture change:** Mark NEEDS-CLARIFICATION for Claude review

**Changelog entry format:**
`T-011 | scrapers/news_scout.py | fixed [description of what was changed] | Cline | YYYY-MM-DD HH:MM`

---

## T-012 | Fix errors found in portal_scout (from T-002)
**Status:** SKIP — not needed
**Brain:** Cline
**Phase:** P1
**Blocked by:** T-002 passed — no fix required
**Priority:** N/A

**Resolution:** T-002 PASSED (Kilo Code 2026-05-15 16:22). 4 listings found. 99acres returned 403 and PropTiger 404 are portal-side blocks, not code bugs. No fix needed. MagicBricks + NoBroker are working sources.

---

## T-013 | Fix developer_scout Playwright 0 projects
**Status:** BLOCKED
**Brain:** Claude (reassigned from Cline — requires scraper architecture knowledge)
**Phase:** P1
**Blocked by:** T-039
**Priority:** HIGH

**Context:** T-003 returned 0 projects from Brigade/Prestige. Playwright found pages but the North Bengaluru keyword filter eliminated all results. This is either: wrong keywords, wrong Playwright selector, or the developer site structure changed. T-039 will diagnose. Claude reads T-039 findings and fixes.

**What Claude does (after T-039 is DONE):**
1. Read T-039 CHANGELOG entry (keyword list, selectors, URLs found)
2. Read `scrapers/developer_scout.py` in full
3. Likely fixes:
   - Update North Bengaluru keyword list (e.g., "Yelahanka" not matching "North Bengaluru")
   - Update Playwright selector if site DOM changed
   - Add `--with-deps` Playwright step if browser is failing silently
4. Re-run: `docker compose exec agents python scrapers/developer_scout.py --developer "Brigade,Prestige" --market Yelahanka`
5. Verify: at least 1 project found

**Changelog entry format:**
`T-013 | scrapers/developer_scout.py | fixed [description] | Claude | YYYY-MM-DD HH:MM`

---

## T-014 | Fix rera_detail_scout — no checkpoint data
**Status:** BLOCKED
**Brain:** Claude (reassigned from Cline — dependency issue, not a code bug)
**Phase:** P1
**Blocked by:** T-040
**Priority:** HIGH

**Context:** T-004 returned 0 enriched records. Root cause: rera_detail_scout reads a checkpoint file from the main RERA scraper to get `detail_url` per project. That checkpoint didn't exist or had no `detail_url` field. This is a pipeline dependency issue, not a bug in rera_detail_scout itself. T-040 will confirm the exact checkpoint format. Claude then decides: seed the checkpoint, or restructure rera_detail_scout to read from DB instead.

**What Claude does (after T-040 is DONE):**
1. Read T-040 CHANGELOG entry (checkpoint path, format, and what produces it)
2. Read `scrapers/rera_detail_scout.py` in full
3. Decide fix approach:
   - **Option A:** Ensure main RERA scraper runs first and produces checkpoint with `detail_url` — update pipeline Stage 1 order
   - **Option B:** Modify rera_detail_scout to query `rera_projects.detail_url` from DB instead of checkpoint
4. Implement chosen approach. Re-run T-004's command to verify.

**Changelog entry format:**
`T-014 | scrapers/rera_detail_scout.py | fixed checkpoint dependency: [description] | Claude | YYYY-MM-DD HH:MM`

---

## T-015 | Rebuild agents container after requirements change
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** — (T-007 completed by Kilo Code 2026-05-15)
**Priority:** MEDIUM
**Task Tier:** T2 — Docker commands (build + verify imports)
**Plan mode:** OpenRouter → any free model
**Act mode:** OpenRouter → same free model (reliable for terminal commands)

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
**Task Tier:** T0 — Read-only (verify current state, no edit needed yet)
**Plan mode:** Ollama (any local model)
**Act mode:** Ollama (same)

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
**Task Tier:** T0 — Read-only + one command
**Plan mode:** Ollama (any local model)
**Act mode:** Ollama (same)

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

---

## T-038 | Diagnose news_scout.py — root cause for 0 articles
**Status:** DONE ✅ — diagnosed 2026-05-15 16:46 by Kilo Code. Root cause: days_back=14 cutoff eliminates all articles (newest=2026-04-03, 32d old). ET Realty returns 404. Both sources silent-fail. Fix applied in T-041 by Claude 2026-05-15.
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T0 — Read-only (audit only, no edits)
**Recommended Model:** Free default (Kilo Code built-in)

**Context:** T-001 (run by Kilo Code 2026-05-15) returned 0 articles with no traceback. Google News RSS and ET Realty both returned empty. Need to understand WHY before Cline can fix in T-011.

**What to do:**
1. Read `scrapers/news_scout.py` — if file is >300 lines, note "FILE TOO LONG" and mark NEEDS-FIX
2. Find and record:
   - The exact RSS URL used (e.g., `https://news.google.com/rss/search?q=...`)
   - How the market name (`Yelahanka`) is substituted into the URL or query
   - The ET Realty URL/search endpoint used
   - Whether there is any try/except that silently swallows errors (returns empty list instead of raising)
   - Whether any function returns `[]` early if an API key is missing
3. Do NOT fix anything — diagnose only

**Files to touch:** READ ONLY — `scrapers/news_scout.py`
**Success check:** You have answered all 5 questions above
**If file is too long (>300 lines):** Stop. Write escalation note to `kilo_logs/CHANGELOG.md`. Change Brain → Cline, Status → READY in TASK_QUEUE.md.

**Log findings to:** `kilo_logs/CHANGELOG.md` ONLY. Do NOT write to root `CHANGELOG.md`.
**Log format:** `## T-038 | news_scout.py diagnosis | DONE | YYYY-MM-DD HH:MM` then bullet findings.

---

## T-039 | Diagnose developer_scout.py — root cause for 0 projects
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T0 — Read-only (audit only, no edits)
**Recommended Model:** Free default (Kilo Code built-in)

**Context:** T-003 returned 0 projects from Brigade/Prestige. Playwright ran successfully (no traceback) but North Bengaluru keyword filter eliminated all results. Need keyword list and selectors before Claude can fix in T-042.

**What to do:**
1. Read `scrapers/developer_scout.py` — if file is >300 lines, note "FILE TOO LONG" and mark NEEDS-FIX
2. Find and record:
   - The exact list of North Bengaluru keywords used to filter results (the keyword filter function/list)
   - The Brigade website URL being scraped (exact URL)
   - The Prestige website URL being scraped (exact URL)
   - The Playwright CSS selector used to find project cards on these pages
   - Whether there is a minimum match threshold (e.g., "must match 2 keywords") that is too strict
3. Do NOT fix anything — diagnose only

**Files to touch:** READ ONLY — `scrapers/developer_scout.py`
**Success check:** You have found and logged all 5 items above
**If file is too long (>300 lines):** Stop. Write escalation note to `kilo_logs/CHANGELOG.md`. Change Brain → Cline, Status → READY in TASK_QUEUE.md.

**Log findings to:** `kilo_logs/CHANGELOG.md` ONLY. Do NOT write to root `CHANGELOG.md`.
**Log format:** `## T-039 | developer_scout.py diagnosis | DONE | YYYY-MM-DD HH:MM` then bullet findings.

---

## T-040 | Diagnose rera_detail_scout.py — checkpoint prerequisite
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T0 — Read-only (audit only, no edits)
**Recommended Model:** Free default (Kilo Code built-in)

**Context:** T-004 returned 0 enriched records. CHANGELOG entry: "no RERA projects with detail_url in checkpoint". Need to understand what checkpoint rera_detail_scout reads, what format it expects, and what produces that checkpoint.

**What to do:**
1. Read `scrapers/rera_detail_scout.py` — if file is >300 lines, note "FILE TOO LONG" and mark NEEDS-FIX
2. Find and record:
   - The exact checkpoint file path it reads (e.g., `outputs/Yelahanka/rera_checkpoint.json`)
   - What field name it looks for in each record (e.g., `detail_url`, `project_url`)
   - Which scraper produces that checkpoint file (search for the same filename being written)
   - Whether it can also read from the DB (does it import `psycopg2` or query `rera_projects`?)
   - What it does when the checkpoint file is missing — does it error or silently return 0?
3. Do NOT fix anything — diagnose only

**Files to touch:** READ ONLY — `scrapers/rera_detail_scout.py`
**Success check:** You have answered all 5 questions above
**If file is too long (>300 lines):** Stop. Write escalation note to `kilo_logs/CHANGELOG.md`. Change Brain → Cline, Status → READY in TASK_QUEUE.md.

**Log findings to:** `kilo_logs/CHANGELOG.md` ONLY. Do NOT write to root `CHANGELOG.md`.
**Log format:** `## T-040 | rera_detail_scout.py diagnosis | DONE | YYYY-MM-DD HH:MM` then bullet findings.

---

## T-041 | Fix news_scout empty results
**Status:** DONE ✅ — fixed 2026-05-15 by Claude. Changes: days_back default 14→60 in _fetch_google_news_rss(), scout(), scout_news(), argparse; added filtered-count logging; added ET Realty non-200 log; NEWS_QUERIES years 2025→2026.
**Brain:** Claude (fix applied during review, not Cline)
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T3 — Code edit (update URL or query params in news_scout.py)
**Plan mode:** NinRouter → Codex (to reason about the right fix from T-038 diagnosis)
**Act mode:** OpenRouter → free model (to write the file edit)

**What to do (after T-038 is DONE):**
1. Read T-038's CHANGELOG entry to get the exact diagnosis
2. Read `scrapers/news_scout.py` — find the specific URL/query section identified in T-038
3. Apply the targeted fix:
   - If RSS URL is wrong: update the URL with correct Google News RSS format for Indian RE news
   - If market name not substituting: fix the string format/substitution
   - If silent fail swallowing error: add a `print(f"[news_scout] error: {e}")` before `return []`
   - If API key causing early exit: add a fallback path that doesn't need the key
4. Re-run: `docker compose exec agents python scrapers/news_scout.py --market Yelahanka`
5. Verify: at least 1 article returned

**Files to touch:** READ+WRITE — `scrapers/news_scout.py` (targeted fix only)
**Success check:** Command returns ≥1 article with no traceback
**If fix requires architecture change:** Mark NEEDS-CLARIFICATION for Claude

**Changelog entry format:**
`T-041 | scrapers/news_scout.py | fixed [what was changed]: [one line] | Cline | YYYY-MM-DD HH:MM`

---

## T-042 | Fix developer_scout Playwright failure
**Status:** BLOCKED
**Brain:** Claude
**Phase:** P1
**Blocked by:** T-039
**Priority:** HIGH

Claude task. After T-039 diagnosis: read T-039 CHANGELOG, read `scrapers/developer_scout.py` in full, fix the keyword filter or Playwright selector causing 0 results. Most likely: keyword list doesn't include "Yelahanka" / "yelahanka" case-insensitive, or selector is stale. Verify with: `docker compose exec agents python scrapers/developer_scout.py --developer "Brigade,Prestige" --market Yelahanka`

**Changelog entry format:**
`T-042 | scrapers/developer_scout.py | fixed [description] | Claude | YYYY-MM-DD HH:MM`

---

## ADDING NEW TASKS

When a review cycle reveals new work, Claude adds tasks here following the spec format above.
Claude assigns the next available T-XXX number and inserts the row in the INDEX + writes the DETAIL SPEC.

**Current last task ID: T-042**
**Next task ID to use: T-043**

---

*This file is the ground truth for all pending work. VISION.md has the strategic picture. AGENTS.md has the protocol. TASK_QUEUE.md has the jobs.*
