# TASK_QUEUE.md — RE_OS Atomic Task Queue
**Last updated: 2026-05-19 | Maintained by: Claude Code**

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
| T-014 | Fix rera_detail_scout — no checkpoint data | Claude | DONE | P1 | T-040 |
| T-015 | Rebuild agents container after requirements change | Cline | DONE | P1 | — |
| T-016 | Wire 4 scouts as tools in scraper_agent.py | Claude | DONE | P1 | — |
| T-017 | Wire scout tools into crew Stage 1 (market_intel_crew.py) | Claude | DONE | P1 | — |
| T-018 | Wire scout outputs into db_organizer.py | Cline | DONE | P1 | — |
| T-019 | Fix analyst LLM loop — calls market_summary_query 4x | Claude | DONE | P2 | T-015 |
| T-020 | CEO report upgrade — 6-section structured brief | Claude | DONE | P1 | T-019 |
| T-021 | Analyst upgrade — 6 signals (velocity, momentum, etc.) | Claude | DONE | P1 | T-020 |
| T-022 | Full integration test — all scouts for Yelahanka | Cline | DONE | P1 | T-017,T-018 |
| T-023 | Expand markets to Devanahalli + Hebbal | Cline | SKIP | P2 | T-022 |
| T-024 | DB upsert portal_scout + developer_scout → listings table | Cline | DONE | P2 | T-018 |
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
| T-035 | Fix delay_months generated column in schema.sql | Cline | DONE | P2 | — |
| T-036 | Kaveri portal — diagnose unreachable URL | Cline | DONE | P1 | — |
| T-037 | Agent registry: create agents/registry/ + YAML schema | Claude | BLOCKED | P8 | T-022 |
| T-038 | Diagnose news_scout.py — root cause for 0 articles | Kilo Code | DONE | P1 | — |
| T-039 | Diagnose developer_scout.py — root cause for 0 projects | Kilo Code | DONE | P1 | — |
| T-040 | Diagnose rera_detail_scout.py — checkpoint prerequisite | Kilo Code | DONE | P1 | — |
| T-041 | Fix news_scout empty results (after T-038 diagnosis) | Cline | DONE | P1 | — |
| T-042 | Fix developer_scout Playwright failure (after T-039) | Claude | SKIP | P1 | — |
| T-052 | Diagnose project_status varchar truncation | Kilo Code | DONE | P1 | — |
| T-053 | Diagnose Cerebras NameError — audit analyst_agent.py | Kilo Code | DONE | P1 | — |
| T-054 | Diagnose completed_at not set in agent_runs | Kilo Code | DONE | P1 | — |
| T-055 | Audit llm_router.py — get_analysis_llm full chain | Kilo Code | DONE | P1 | — |
| T-056 | Audit ceo_agent.py — system prompt + output format | Kilo Code | DONE | P2 | — |
| T-057 | Audit scraper_agent.py — tools + Cerebras class usage | Kilo Code | DONE | P1 | — |
| T-058 | Audit rera_karnataka.py — checkpoint file schema | Kilo Code | DONE | P1 | — |
| T-059 | Audit dashboard/app.py — routes + cabin inventory | Kilo Code | DONE | P2 | — |
| T-060 | Audit config/settings.py — market keyword lists | Kilo Code | DONE | P1 | — |
| T-061 | Draft spec for T-018 — wire scout outputs → db_organizer | Kilo Code | DONE | P1 | — |
| T-062 | Re-run T-046 integration test — all bugs now fixed | Claude | DONE ✅ | P1 | — |
| T-063 | Add Stage 2 upsert for rera_detail_scout enriched data | Cline | DONE | P1 | — |
| T-064 | Market expansion — Devanahalli + Hebbal | Cline | READY | P2 | — |
| T-065 | Dashboard: wire /api/agents endpoint to live DB | Cline | READY | P2 | — |
| T-066 | Dashboard: wire /api/intel endpoint — serve latest intel report | Cline | BLOCKED | P2 | T-065 |
| T-067 | Dashboard: expose port 8050 in docker-compose.yml | Cline | READY | P2 | — |
| T-068 | Dashboard: scout log patterns in monitor thread | Cline | READY | P2 | — |
| T-069 | Fix sentinel_agent __main__ block (T-010 enabler) | Cline | READY | P1 | — |
| T-070 | Audit portal_scout output — verify cid field in all records | Kilo Code | DONE | P1 | — |
| T-071 | Audit rera_detail_scout checkpoint — verify enriched fields | Kilo Code | DONE | P1 | — |
| T-072 | Audit market_intel_crew.py Stage 1 cache fix correctness | Kilo Code | DONE | P1 | — |
| T-073 | Draft spec for adding duration_seconds to kaveri + portal run logs | Kilo Code | DONE | P1 | — |
| T-074 | Audit dashboard/app.py /api/agents — what data it currently returns | Kilo Code | DONE | P2 | — |
| T-075 | Audit news_articles table — verify rows inserted after Stage 2 run | Kilo Code | DONE | P1 | T-062 |
| T-076 | Silent failure audit — scrapers/ directory (all .py files) | Kilo Code | DONE | P1 | — |
| T-077 | Audit developer_scout.py — verify T-042 sampling fix in file | Kilo Code | DONE | P1 | — |
| T-078 | Audit news_scout.py — verify T-041 days_back fix + NEWS_QUERIES years | Kilo Code | DONE | P1 | — |
| T-079 | Audit listings_scraper.py — is it superseded by portal_scout or still used? | Kilo Code | DONE | P1 | — |
| T-080 | Audit kaveri_karnataka.py — find all silent failure paths | Kilo Code | DONE | P1 | — |
| T-081 | Audit rera_karnataka.py — list all fallback triggers and conditions | Kilo Code | DONE | P1 | — |
| T-082 | Audit config/checkpointer.py — file format, TTL logic, edge cases | Kilo Code | DONE | P1 | — |
| T-083 | Audit config/run_logger.py — what it writes vs what agent_runs needs | Kilo Code | **DONE** | P1 | — |
| T-084 | Audit agents/analyst_agent.py — tool call count, prompt to prevent 4x loop | Kilo Code | **DONE** | P2 | — |
| T-085 | Audit agents/ceo_agent.py — verify 6-section prompt matches actual output | Kilo Code | **DONE** | P2 | — |
| T-086 | Audit utils/validator.py — list all validation rules + pass/fail criteria | Kilo Code | **DONE** | P1 | — |
| T-087 | Audit crews/market_intel_crew.py — list all _EXCLUDED.clear() call sites | Kilo Code | **DONE** | P1 | — |
| T-088 | DB: count rows in ALL 12 tables (full health snapshot) | Kilo Code | DONE | P1 | — |
| T-089 | DB: developer grade distribution query | Kilo Code | DONE | P1 | — |
| T-090 | DB: stale records — rera_projects not updated in 7 days | Kilo Code | **DONE** | P1 | — |
| T-091 | DB: market coverage — which micro_markets have rera_projects data? | Kilo Code | **DONE** | P1 | — |
| T-092 | DB: listings table structure — verify unique constraint (source, source_listing_id) | Kilo Code | **DONE** | P1 | — |
| T-093 | DB: agent_runs by status — completed vs failed count | Kilo Code | **DONE** | P1 | — |
| T-094 | DB: guidance_values table — populated or empty? | Kilo Code | **DONE** | P1 | — |
| T-095 | DB: kaveri_registrations table — populated or empty? | Kilo Code | **DONE** | P1 | — |
| T-096 | DB: project_snapshots table — populated or empty? | Kilo Code | **DONE** | P1 | — |
| T-097 | DB: overlay_constraints + regulatory_zones + infra_pipeline — all empty? | Kilo Code | **DONE** | P3 | — |
| T-098 | DB: top 10 developers by project count | Kilo Code | **DONE** | P1 | — |
| T-099 | DB: rera_projects with 0 total_units — count and sample | Kilo Code | **DONE** | P1 | — |
| T-100 | DB: rera_projects missing developer_id (orphaned records) | Kilo Code | **DONE** | P1 | — |
| T-101 | DB: rera_projects missing micro_market_id (unclassified records) | Kilo Code | **DONE** | P1 | — |
| T-102 | DB: possession_date distribution — how many overdue? | Kilo Code | **DONE** | P2 | — |
| T-103 | DB: v_market_brief view — run it and summarize output | Kilo Code | **DONE** | P2 | — |
| T-104 | DB: v_developer_scorecard view — run it and summarize | Kilo Code | **DONE** | P2 | — |
| T-105 | Inventory all intel_report_*.txt files — size, date, market | Kilo Code | **DONE** | P1 | — |
| T-106 | Read latest intel report — flag [FALLBACK SAMPLE] markers | Kilo Code | DONE | P1 | — |
| T-107 | Compare two intel reports for Yelahanka — PSF + absorption delta | Kilo Code | DONE | P2 | — |
| T-108 | Audit kilo_output/queue/ — list unactioned spec drafts | Kilo Code | DONE | P1 | — |
| T-109 | Audit kilo_output/drafts/ — list unread wiki drafts, summarize key claims | Kilo Code | DONE | P2 | — |
| T-110 | Silent failure audit — scrapers/ directory (all .py files) | Kilo Code | **DONE** | P1 | — |
| T-111 | Dead import finder — agents/ directory | Kilo Code | **DONE** | P1 | — |
| T-112 | Dead import finder — scrapers/ directory | Kilo Code | **DONE** | P1 | — |
| T-113 | TODO/FIXME tracker — full codebase scan | Kilo Code | **DONE** | P1 | — |
| T-114 | Function length audit — find all functions >50 lines in scrapers/ + crews/ | Kilo Code | **DONE** | P1 | — |
| T-115 | API key coverage check — all keys in settings.py, have defaults? | Kilo Code | **DONE** | P1 | — |
| T-116 | Docker service health check — all 5 containers status | Kilo Code | **DONE** | P1 | — |
| T-117 | Disk usage check — outputs/, logs/, kilo_output/ sizes | Kilo Code | **DONE** | P1 | — |
| T-118 | Scheduler next run check — cron expression + container running? | Kilo Code | **DONE** | P1 | — |
| T-119 | Scout memory dedup stats — entry count per scout type | Kilo Code | **DONE** | P1 | — |
| T-120 | Checkpoint freshness — all checkpoint files, flag >2 days old | Kilo Code | **DONE** | P1 | — |
| T-121 | Log file size monitor — crew.log size, needs rotation? | Kilo Code | **DONE** | P1 | — |
| T-122 | Cross-check AGENTS.md vs current tool stack — is it up to date? | Kilo Code | **DONE** | P1 | — |
| T-123 | Audit VISION.md — current phase vs DEVLOG.md phase count | Kilo Code | **DONE** | P2 | — |
| T-124 | Audit .gitignore — are outputs/, kilo_output/, logs/ excluded? | Kilo Code | **DONE** | P1 | — |
| T-125 | Draft LLS action brief from all intel reports — chronological reco index | Kilo Code | **DONE** | P2 | — |
| T-138 | Fix rera_detail_scout _build_detail_url() — wrong URL type, 0 enriched fields | Cline | DONE | P1 | — |
| T-139 | Fix news_scout Gemini 429 — add Cerebras/NVIDIA fallback on rate limit | Cline | DONE | P1 | — |
| T-140 | Fix agent_runs status casing — SQL migration + CHECK constraint | Cline | DONE | P2 | — |
| T-141 | Fix .gitignore — add kilo_output/ and kilo_logs/ | Cline | DONE | P1 | — |
| T-142 | EG-019: Guidance value freshness audit | Kilo Code | DONE | P2 | — |
| T-143 | EG-035: Multi-market intel comparison draft (Yelahanka + Devanahalli) | Kilo Code | DONE | P2 | — |
| T-144 | EG-036: Distressed project brief — Yelahanka (absorption 3.5%) | Kilo Code | DONE | P2 | — |
| T-145 | EG-039: RERA project enrichment gaps audit (post T-129 findings) | Kilo Code | DONE | P2 | — |
| **PHASE A — Pipeline Closure (Cline)** | | | | | |
| T-146 | PA-1: Add run_rera_detail_scout() to db_organizer + Stage 2 upsert wire in crew | Cline | SKIP | PA | — |
| T-147 | PA-2: Fix developer_scout — rewrite AI extraction sampling for SPA developer sites | Cline | DONE | PA | — |
| T-148 | PA-3: Add sentinel_agent __main__ healthcheck entrypoint block | Cline | SKIP | PA | — |
| T-149 | PA-4: Wire sentinel_agent into docker-compose healthcheck service | Cline | SKIP | PA | T-148 |
| T-150 | PA-5: Integration test Yelahanka — verify rera_detail enriched_fields > 0 in DB | Cline | READY | PA | — |
| T-151 | PA-6: Verify developer_scout returns > 0 projects for Brigade/Prestige standalone | Cline | READY | PA | T-147 |
| **PHASE B — Content + Analysis Quality Audit (Kilo Code)** | | | | | |
| T-152 | PB-1: Audit rera_detail_scout post-T-146: verify enriched_fields > 0 in checkpoint | Kilo Code | READY | PB | — |
| T-153 | PB-2: Audit developer_scout post-T-147: count projects per developer in checkpoint | Kilo Code | READY | PB | — |
| T-154 | PB-3: Draft wiki page Yelahanka using intel_report_20260518_1029.txt — live data only | Kilo Code | DONE | PB | — |
| T-155 | PB-4: EG-035 multi-market intel comparison Yelahanka vs Devanahalli (post Phase C) | Kilo Code | DEFERRED | PB | Post-Yelahanka launch |
| T-156 | PB-5: EG-036 distressed project brief Yelahanka — absorption 3.5%, 6 overdue, dev comp | Kilo Code | DONE | PB | — |
| T-157 | PB-6: EG-039 RERA enrichment gaps audit post-T-146 fix — how many fields now populated? | Kilo Code | SKIP | PB | Superseded by T-145 |
| T-158 | PB-7: Draft LLS action brief — signal index from all 3 markets + price entry thesis | Kilo Code | DEFERRED | PB | Post-Yelahanka launch |
| **PHASE C — Multi-Market Expansion (DEFERRED — post-Yelahanka launch)** | | | | | |
| T-159 | PC-1: Run crew Devanahalli — verify intel_report created + rera_projects > 0 in DB | Cline | DEFERRED | PC | Post-Yelahanka launch |
| T-160 | PC-2: Run crew Hebbal — verify intel_report created + rera_projects > 0 in DB | Cline | DEFERRED | PC | Post-Yelahanka launch |
| T-161 | PC-3: DB verify post-T-159/T-160 — v_market_brief returns non-null PSF for 3 markets | Cline | DEFERRED | PC | Post-Yelahanka launch |
| T-162 | PC-4: Fix any RERA POST parameter failures specific to Devanahalli/Hebbal markets | Cline | DEFERRED | PC | Post-Yelahanka launch |
| T-163 | PC-5: Run run_all_markets() end-to-end — verify 3 sequential intel reports generated | Cline | DEFERRED | PC | Post-Yelahanka launch |
| T-164 | PC-6: Verify v_developer_scorecard returns rows for Devanahalli + Hebbal developers | Cline | DEFERRED | PC | Post-Yelahanka launch |
| **PHASE D — Dashboard Activation (Cline)** | | | | | |
| T-165 | PD-1: Verify dashboard port 8050 exposed — curl /api/health returns 200 | Cline | READY | PD | — |
| T-166 | PD-2: Wire /api/agents endpoint to live DB (agent_runs query, replace in-memory dict) | Cline | READY | PD | T-165 |
| T-167 | PD-3: Wire /api/intel endpoint to serve latest intel_report_{ts}.txt per market | Cline | READY | PD | T-165 |
| T-168 | PD-4: Add scout log pattern monitor thread parsing crew.log in dashboard app.py | Cline | READY | PD | T-165 |
| T-169 | PD-5: Wire /api/db/state to return live row counts for all 12 tables | Cline | READY | PD | T-165 |
| T-170 | PD-6: Add /api/run POST endpoint — triggers market_intel_crew.py in background subprocess | Cline | READY | PD | T-165 |
| T-171 | PD-7: Smoke test dashboard — all 5 cabins respond, 6 API endpoints return valid JSON | Cline | READY | PD | T-170 |
| **PHASE E — Dashboard Content Audit (Kilo Code)** | | | | | |
| T-172 | PE-1: Audit /api/agents post-T-166 — verify live DB data returned, not in-memory placeholder | Kilo Code | BLOCKED | PE | T-166 |
| T-173 | PE-2: Audit dashboard HTML — verify all 5 cabin cards render states correctly | Kilo Code | BLOCKED | PE | T-171 |
| T-174 | PE-3: Audit SSE /api/logs/stream — verify log lines have correct format + colour codes | Kilo Code | BLOCKED | PE | T-171 |
| T-175 | PE-4: Draft spec for dashboard v2 — market selector UI + auto-refresh intel panel | Kilo Code | DONE | PE | — |
| T-176 | PE-5: Draft spec for market comparison panel — PSF + absorption side-by-side 3 markets | Kilo Code | READY | PE | — |
| T-177 | PE-6: Audit /api/intel error path — what happens when no report file exists for market? | Kilo Code | BLOCKED | PE | T-167 |
| T-178 | PE-7: Draft spec for /api/schedule endpoint — show next cron time + manual trigger UI | Kilo Code | READY | PE | — |
| **PHASE F — Intelligence Quality Upgrade (Cline)** | | | | | |
| T-179 | PF-1: Fix CEO synthesis truncation — set max_tokens=4096 for CEO LLM tier | Cline | READY | PF | — |
| T-180 | PF-2: Fix analyst 4x tool call loop — add tool_call_budget to analyst ReAct prompt | Cline | READY | PF | — |
| T-181 | PF-3: Add duration_seconds to kaveri + portal run logs in db_organizer._log_run() | Cline | READY | PF | — |
| T-182 | PF-4: Add WARNING logging to 4 silent failure paths (scout_memory:144, portal_scout:147, news_scout:151+169) | Cline | READY | PF | — |
| T-183 | PF-5: Add [ESTIMATED] prefix to CEO synthesis when >40% null unit_mix in rera_projects | Cline | READY | PF | — |
| **PHASE G — Intelligence Depth Audit (Kilo Code)** | | | | | |
| T-184 | PG-1: Audit CEO synthesis post-T-179 — 6 full sections, no Ollama truncation? | Kilo Code | BLOCKED | PG | T-179 |
| T-185 | PG-2: Audit news_articles table post-T-139 — do articles appear after fresh crew run? | Kilo Code | READY | PG | — |
| T-186 | PG-3: Draft market entry thesis Yelahanka — PSF entry point, developer comp, timing | Kilo Code | READY | PG | — |
| T-187 | PG-4: Audit run_history.jsonl post-T-181 — Yelahanka logged, duration_seconds present? | Kilo Code | BLOCKED | PG | T-181 |
| T-188 | PG-5: Draft all-market analyst brief — 3-market signal comparison for LLS board deck | Kilo Code | DEFERRED | PG | Post-Yelahanka launch |
| **PHASE H — Automation + Reliability (Cline)** | | | | | |
| T-189 | PH-1: Add scheduler cron for Yelahanka at 2:30 AM IST daily (post-RERA 2 AM scrape) | Cline | READY | PH | — |
| T-190 | PH-2: Add run_market() error isolation — if pipeline stage fails, log and exit cleanly | Cline | READY | PH | — |
| T-191 | PH-3: Add /health endpoint to agents container — returns DB status + last run timestamp | Cline | READY | PH | T-165 |
| T-192 | PH-4: Implement log rotation — crew.log > 5 MB rotates to crew.log.YYYY-MM-DD | Cline | READY | PH | — |
| T-193 | PH-5: Add /api/schedule endpoint to dashboard — show next cron run, allow manual trigger | Cline | BLOCKED | PH | T-189 |
| T-194 | PH-6: End-to-end system test — simulate overnight run Yelahanka, verify report next morning | Cline | READY | PH | T-189 |
| T-195 | PH-7: Update AGENTS.md + CLAUDE.md to reflect Yelahanka launch completion + new architecture | Cline | READY | PH | T-194 |
| **PHASE Y — Yelahanka Launch Focus (NEW — replaces Phase C)** | | | | | |
| T-203 | YA-1: Data source audit — query data_source breakdown for Yelahanka rera_projects (seed vs live) | Kilo Code | READY | PY | — |
| T-204 | YA-2: Confidence map — read latest Yelahanka intel report, count [FALLBACK] markers per section | Kilo Code | READY | PY | — |
| T-205 | YB-1: CEO prompt upgrade — add LLS decision framing (entry PSF, JD/JV targets, go/no-go) | Cline | READY | PY | T-150 |
| T-206 | YB-2: Analyst upgrade — add distressed_developer_list query (possession overdue + absorption > 60%) | Cline | READY | PY | T-150 |
| T-207 | YB-3: Debug run_rera_detail_scout DB write — trace why 97.8% null unit_mix persists post T-063+T-138 | Cline | READY | PY | T-150 |
| T-208 | YC-1: Fix Brigade/Prestige developer URLs for Yelahanka — find live project listing pages | Cline | READY | PY | T-151 |
| T-209 | YD-1: Synthesize Yelahanka decision pack — merge T-143/T-144/T-154 drafts into single brief | Kilo Code | READY | PY | — |

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
**Status:** DONE
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
**Status:** DONE ✅ — VERIFIED-OK 2026-05-16 by Cline. Column is correctly defined as `GENERATED ALWAYS AS (CASE WHEN actual_completion_date > possession_date THEN (actual_completion_date - possession_date) / 30 ELSE 0 END) STORED` at schema.sql:107-113. Formula computes delay in months (actual completion - promised possession). Non-negative fallback to 0. No changes needed.
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
**Status:** DONE ✅ — fixed 2026-05-16 by Claude. 3 fixes: start+middle sampling (5k+5k) instead of first 6k; Playwright wait_for_timeout 3000→6000ms; content fallback threshold 200→500 chars. Root cause: _clean_html stripping nav/header containing keywords, causing full text fallback truncated to hero copy.

**Changelog entry format:**
`T-042 | scrapers/developer_scout.py | fixed [description] | Claude | YYYY-MM-DD HH:MM`

---

## T-052 | Diagnose project_status varchar truncation
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T0 — Read-only + one SELECT query

**Context:** EG-001 found `StringDataRightTruncation` on `project_status varchar(50)` when inserting "Sai Kalyan Water Edge" (RERA ID `PRM/KA/RERA/1251/472/PR/201125/003721`). This project is missing from the DB and is blocking T-046 PASS. Claude needs the column length and where the value comes from to write the ALTER TABLE fix.

**What to do:**
1. Read `database/schema.sql` — search for "project_status". Note its exact type and length (e.g., `VARCHAR(50)`)
2. Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT MAX(LENGTH(project_status)) FROM rera_projects;"`
   Note the current max stored length (should be ≤50)
3. Read `utils/db_organizer.py` — find where `project_status` value is assigned before INSERT. What RERA field does it come from?
4. Do NOT fix anything

**Files to touch:** READ ONLY — `database/schema.sql`, `utils/db_organizer.py`
**Success check:** You have: column definition, current max stored length, source field name, recommended new size
**Output:** Write all findings to `kilo_output/audits/project_status_truncation.md`

**Log format:**
`## T-052 | project_status truncation | DONE | YYYY-MM-DD HH:MM`
`schema: varchar(N) | max_stored: X | source_field: [name] | recommended: varchar(Y)`

---

## T-053 | Diagnose Cerebras NameError — audit analyst_agent.py
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T0 — Read-only

**Context:** EG-001 found `NameError: name 'Cerebras' is not defined` inside `intel_crew.kickoff()`. The intel crew uses analyst + CEO agents. `get_analysis_llm()` returns an LLM object (not a bare Cerebras class). Root cause is inside one of the intel crew agents or their tools. `config/llm_router.py` confirmed clean — no bare `Cerebras` class call. Suspect: analyst_agent.py tools calling Cerebras directly.

**What to do:**
1. Read `agents/analyst_agent.py`
2. Find: every tool registered to the analyst (look for `tools=[...]`, `@tool`, or `Tool(...)`)
3. Search the file for: any line containing the word `Cerebras` (capital C) used as a Python name — not in a string or comment
4. Find: how the analyst's LLM is assigned — does it call `get_analysis_llm()` or construct an LLM directly?
5. Note: max_iter value if set
6. Do NOT fix anything

**Files to touch:** READ ONLY — `agents/analyst_agent.py`
**Success check:** You have: full tool list, whether `Cerebras` appears as a bare Python name, LLM assignment method
**Output:** Write findings to `kilo_output/audits/cerebras_nameerror.md`

**Log format:**
`## T-053 | Cerebras NameError diagnosis | DONE | YYYY-MM-DD HH:MM`
`tools={list} | Cerebras_as_python_name={yes/no at line N} | llm_via={get_analysis_llm/direct}`

---

## T-054 | Diagnose completed_at not set in agent_runs
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** MEDIUM
**Task Tier:** T0 — Read-only

**Context:** EG-002 found `duration_seconds = 0` for all agent_runs records. The root cause: `completed_at` is never set, so `duration_seconds` (which is computed from it) stays 0. This makes the monitoring dashboard useless. Need to find where the UPDATE should be added.

**What to do:**
1. Read `utils/db_organizer.py` — find the INSERT statement for `agent_runs`. Note all columns set on INSERT.
2. Search `utils/db_organizer.py` for any UPDATE on `agent_runs` — does `completed_at` ever get set?
3. Read `config/run_logger.py` — does it update `agent_runs.completed_at` on pipeline completion?
4. Note the exact file + function where `completed_at` should be set (but is not)
5. Do NOT fix anything

**Files to touch:** READ ONLY — `utils/db_organizer.py`, `config/run_logger.py`
**Success check:** You have: INSERT column list, whether completed_at is ever UPDATEd, exact location for the fix
**Output:** Write findings to `kilo_output/audits/agent_runs_completed_at.md`

**Log format:**
`## T-054 | completed_at diagnosis | DONE | YYYY-MM-DD HH:MM`
`insert_cols={list} | completed_at_update_exists={yes/no} | fix_location={file:function}`

---

## T-055 | Audit llm_router.py — get_analysis_llm full chain
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T0 — Read-only

**Context:** Pre-req for T-019 (fix analyst LLM loop). Also supplements T-053 — together they fully document the analysis-tier LLM flow. Need to confirm get_analysis_llm() returns an `LLM` object (not a Cerebras class), and document the full fallback chain.

**What to do:**
1. Read `config/llm_router.py`
2. Copy the full body of `get_analysis_llm()` verbatim
3. Note: what does it return? (`LLM(...)` object, a string, a class instance?)
4. Note: the fallback chain order (Cerebras → Groq → Ollama or similar)
5. Note: all imports at the top of the file — is `Cerebras` imported as a class anywhere?
6. Do NOT fix anything

**Files to touch:** READ ONLY — `config/llm_router.py`
**Success check:** You have: full get_analysis_llm() body, return type, fallback chain, import list
**Output:** Write findings to `kilo_output/audits/llm_router_analysis_chain.md`

**Log format:**
`## T-055 | llm_router analysis chain | DONE | YYYY-MM-DD HH:MM`
`returns={LLM/class/string} | chain={Cerebras→Groq→Ollama or similar} | Cerebras_import={yes/no}`

---

## T-056 | Audit ceo_agent.py — system prompt + output format
**Status:** READY
**Brain:** Kilo Code
**Phase:** P2
**Blocked by:** —
**Priority:** MEDIUM
**Task Tier:** T0 — Read-only

**Context:** Pre-req for T-020 (CEO report upgrade to 6-section structured brief). Claude needs the current system prompt and output format before designing the upgrade spec.

**What to do:**
1. Read `agents/ceo_agent.py`
2. Copy the system prompt / backstory / goal text verbatim (all of it, not just first N chars)
3. Note: is there an explicit output format instruction (JSON, markdown sections, free text)?
4. Note: max_iter value if set; any `verbose` or `allow_delegation` flags
5. Note: what LLM function is called to power the CEO?
6. Do NOT fix anything

**Files to touch:** READ ONLY — `agents/ceo_agent.py`
**Success check:** You have: full system prompt, output format spec, max_iter, LLM source
**Output:** Write findings to `kilo_output/audits/ceo_agent_format.md`

**Log format:**
`## T-056 | ceo_agent format audit | DONE | YYYY-MM-DD HH:MM`
`output_format={structured/free} | max_iter={N or unset} | llm_via={function_name}`

---

## T-057 | Audit scraper_agent.py — tools + Cerebras class usage
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T0 — Read-only

**Context:** `agents/scraper_agent.py` was recently modified (M in git status). The Cerebras NameError may have been introduced here. Need to audit what tools it registers and whether it references `Cerebras` as a Python class anywhere. Also pre-req for T-016 (wire 4 scouts as tools in scraper_agent).

**What to do:**
1. Read `agents/scraper_agent.py`
2. List all tools registered to the scraper agent (tools=[...] or @tool)
3. Search for any line where `Cerebras` is used as a Python name (not in a string or comment)
4. Note: what LLM is used for the scraper agent — `get_light_llm()`, direct construction, or other?
5. Note: does it import anything from `cerebras` or `langchain_cerebras`?
6. Do NOT fix anything

**Files to touch:** READ ONLY — `agents/scraper_agent.py`
**Success check:** You have: full tool list, whether Cerebras is used as a bare Python name, LLM assignment, any cerebras imports
**Output:** Write findings to `kilo_output/audits/scraper_agent_cerebras.md`

**Log format:**
`## T-057 | scraper_agent Cerebras audit | DONE | YYYY-MM-DD HH:MM`
`tools={list} | Cerebras_bare_name={yes at line N / no} | cerebras_import={yes/no} | llm_via={fn}`

---

## T-058 | Audit rera_karnataka.py — checkpoint file schema
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T0 — Read-only

**Context:** Pre-req for T-014 (fix rera_detail_scout checkpoint dependency). T-040 confirmed rera_detail_scout reads a checkpoint file looking for `detail_url`. This task reads the MAIN RERA scraper to see what it actually writes — if `detail_url` is absent, Claude must add it or restructure rera_detail_scout to read from DB.

**What to do:**
1. Read `scrapers/rera_karnataka.py`
2. Find the function that writes a checkpoint file — note: function name, exact file path written (e.g., `outputs/{market}/rera_checkpoint.json`)
3. List ALL fields written per record in that checkpoint
4. Note specifically: is `detail_url` or `project_url` included? If not, what URL-like fields exist?
5. Do NOT fix anything

**Files to touch:** READ ONLY — `scrapers/rera_karnataka.py`
**Success check:** You have: checkpoint path, full field list, whether detail_url is present
**Output:** Write findings to `kilo_output/audits/rera_checkpoint_schema.md`

**Log format:**
`## T-058 | rera checkpoint schema | DONE | YYYY-MM-DD HH:MM`
`path={checkpoint path} | fields={comma-separated list} | has_detail_url={yes/no}`

---

## T-059 | Audit dashboard/app.py — routes + cabin inventory
**Status:** DONE ✅ — audit complete, output at `kilo_output/audits/dashboard_routes_cabins.md`
**Brain:** Kilo Code
**Phase:** P2
**Blocked by:** —
**Priority:** MEDIUM
**Task Tier:** T0 — Read-only

**Context:** Pre-req for T-025 (wire dashboard to PostgreSQL). Claude needs the full route + cabin inventory before writing the DB wire-up spec. Currently the dashboard has hardcoded/static data — Claude needs to know what's live vs stubbed.

**What to do:**
1. Read `dashboard/app.py`
2. List ALL route definitions (`@app.route`, `@server.route`, or Dash callback `Output(...)`)
3. List all cabin IDs found in HTML layout (search for `id=` in components or HTML strings)
4. For each route: note whether it reads from PostgreSQL or uses hardcoded/static data
5. Note: which port the app binds to (`host=`, `port=`)
6. Do NOT fix anything

**Files to touch:** READ ONLY — `dashboard/app.py`
**Success check:** You have: full route list with DB vs static status, all cabin IDs, port
**Output:** Write findings to `kilo_output/audits/dashboard_routes_cabins.md`

**Log format:**
`## T-059 | dashboard routes audit | DONE | YYYY-MM-DD HH:MM`
`routes={count} | db_wired={count} | hardcoded={count} | cabins={list} | port={N}`

---

## T-060 | Audit config/settings.py — market keyword lists
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** MEDIUM
**Task Tier:** T0 — Read-only

**Context:** T-039 found developer_scout's North Bengaluru keyword filter was eliminating all results. The canonical keyword list may live in settings.py. Claude needs the exact lists to verify whether T-042's fix used the right keywords.

**What to do:**
1. Read `config/settings.py`
2. Find all keyword lists for Yelahanka, Devanahalli, Hebbal (look for `MARKET_KEYWORDS`, `NORTH_BENGALURU_KEYWORDS`, `SEARCH_TERMS`, or similar)
3. List the exact values — do they include both "Yelahanka" AND "North Bengaluru"? Any spelling variants?
4. Find Grade A/B/C developer thresholds (unit count cutoffs for grading)
5. Note any TODO or placeholder values in the file
6. Do NOT fix anything

**Files to touch:** READ ONLY — `config/settings.py`
**Success check:** You have: keyword lists for all 3 markets, grade thresholds, any TODOs
**Output:** Write findings to `kilo_output/audits/settings_keywords.md`

**Log format:**
`## T-060 | settings keyword audit | DONE | YYYY-MM-DD HH:MM`
`yelahanka_kw={count} | devanahalli_kw={count} | hebbal_kw={count} | grade_A_threshold={N} | todos={count}`

---

## T-061 | Draft spec for T-018 — wire scout outputs → db_organizer
**Status:** DONE
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** MEDIUM
**Task Tier:** T0 — Read-only + draft output

**Context:** T-018 is blocked because Claude hasn't written its full spec. Kilo Code can unblock it by reading db_organizer.py's existing upsert pattern and drafting the spec. Claude reviews the draft and either approves or adjusts before assigning to Cline.

**What to do:**
1. Read `utils/db_organizer.py` — find the main upsert function for rera_projects or listings. Note the function signature and input format it expects.
2. Read `kilo_output/summaries/output_inventory_*.md` (latest file) — find descriptions of portal_scout and developer_scout output formats.
3. Draft a spec for T-018 in `kilo_output/queue/spec_T-018_draft.md`:
   - What new function(s) to add to db_organizer.py
   - What input format each function expects (from scout JSONL/JSON output)
   - What DB table each writes to (`listings` table for both?)
   - What the ON CONFLICT clause should be (unique key for dedup)
4. Mark the draft clearly as "DRAFT — awaiting Claude review"

**Files to touch:** READ ONLY — `utils/db_organizer.py`, `kilo_output/summaries/output_inventory_*.md`
**Success check:** `kilo_output/queue/spec_T-018_draft.md` exists with: function signatures, input formats, DB tables, conflict resolution
**Output:** `kilo_output/queue/spec_T-018_draft.md`

**Log format:**
`## T-061 | spec draft T-018 | DONE | YYYY-MM-DD HH:MM`
`functions_drafted={count} | tables_covered={list} | status=DRAFT`

---

## EVERGREEN TASKS

These tasks run in a rotation loop. Kilo Code cycles EG-001 → EG-040, then returns to EG-001. Check for new Tier 1/2 tasks between each cycle.

Full specs for each task live in NEXT_TASKS.md § Tier 3.

| ID | Title | Category | Output location |
|----|-------|----------|----------------|
| EG-001 | Daily crew.log digest | Log | `kilo_output/summaries/crew_log_YYYY-MM-DD.md` |
| EG-002 | DB health snapshot | DB | `kilo_output/summaries/db_health_YYYY-MM-DD.md` |
| EG-003 | Scout output inventory | System | `kilo_output/summaries/output_inventory_YYYY-MM-DD.md` |
| EG-004 | CHANGELOG gap audit | Process | `kilo_output/audits/changelog_gaps_YYYY-MM-DD.md` |
| EG-005 | Draft wiki page from latest intel report | Content | `kilo_output/drafts/wiki_MARKET_YYYY-MM-DD.md` |
| EG-006 | Draft spec for next blocked task | Process | `kilo_output/queue/spec_T-XXX_draft.md` |
| EG-007 | Run history digest | Log | `kilo_output/summaries/run_history_YYYY-MM-DD.md` |
| EG-008 | Error pattern tracker | Log | `kilo_output/audits/error_patterns_YYYY-MM-DD.md` |
| EG-009 | Kilo output index | Process | `kilo_output/summaries/kilo_output_index_YYYY-MM-DD.md` |
| EG-010 | Intel delta comparison | Content | `kilo_output/drafts/intel_delta_MARKET_YYYY-MM-DD.md` |
| EG-011 | Groq rate limit frequency | Log | `kilo_output/audits/groq_rate_limits_YYYY-MM-DD.md` |
| EG-012 | Stage timing tracker | Log | `kilo_output/summaries/stage_timing_YYYY-MM-DD.md` |
| EG-013 | Scraper success rate by type | Log | `kilo_output/audits/scraper_success_rate_YYYY-MM-DD.md` |
| EG-014 | Scraper fallback mode audit | Log | `kilo_output/audits/fallback_modes_YYYY-MM-DD.md` |
| EG-015 | Developer leaderboard | DB | `kilo_output/summaries/developer_leaderboard_YYYY-MM-DD.md` |
| EG-016 | RERA project status distribution | DB | `kilo_output/summaries/project_status_dist_YYYY-MM-DD.md` |
| EG-017 | New projects this week | DB | `kilo_output/summaries/new_projects_YYYY-MM-DD.md` |
| EG-018 | Market absorption snapshot | DB | `kilo_output/summaries/absorption_snapshot_YYYY-MM-DD.md` |
| EG-019 | Guidance value freshness | DB | `kilo_output/audits/guidance_value_freshness_YYYY-MM-DD.md` |
| EG-020 | Listings table freshness | DB | `kilo_output/summaries/listings_freshness_YYYY-MM-DD.md` |
| EG-021 | Agent runs completion rate | DB | `kilo_output/audits/agent_runs_health_YYYY-MM-DD.md` |
| EG-022 | TODO/FIXME tracker | Code | `kilo_output/audits/todo_fixme_YYYY-MM-DD.md` |
| EG-023 | Output file size monitor | System | `kilo_output/audits/output_sizes_YYYY-MM-DD.md` |
| EG-024 | Checkpoint freshness check | System | `kilo_output/audits/checkpoint_freshness_YYYY-MM-DD.md` |
| EG-025 | Log file size monitor | System | `kilo_output/audits/log_sizes_YYYY-MM-DD.md` |
| EG-026 | Silent failure audit | Code | `kilo_output/audits/silent_failures_YYYY-MM-DD.md` |
| EG-027 | Checkpoint integrity check | System | `kilo_output/audits/checkpoint_integrity_YYYY-MM-DD.md` |
| EG-028 | Dead import finder | Code | `kilo_output/audits/dead_imports_YYYY-MM-DD.md` |
| EG-029 | Function length audit | Code | `kilo_output/audits/long_functions_YYYY-MM-DD.md` |
| EG-030 | API key coverage check | System | `kilo_output/audits/api_key_coverage_YYYY-MM-DD.md` |
| EG-031 | Docker service health check | Docker | `kilo_output/summaries/docker_health_YYYY-MM-DD.md` |
| EG-032 | Disk usage check | Docker | `kilo_output/summaries/disk_usage_YYYY-MM-DD.md` |
| EG-033 | Scheduler next run check | Docker | `kilo_output/summaries/scheduler_status_YYYY-MM-DD.md` |
| EG-034 | Scout memory dedup stats | System | `kilo_output/audits/scout_memory_stats_YYYY-MM-DD.md` |
| EG-035 | Multi-market intel comparison | Content | `kilo_output/drafts/multi_market_comparison_YYYY-MM-DD.md` |
| EG-036 | Distressed project brief | Content | `kilo_output/drafts/distressed_projects_MARKET_YYYY-MM-DD.md` |
| EG-037 | Competitor profile draft | Content | `kilo_output/drafts/competitor_DEVNAME_YYYY-MM-DD.md` |
| EG-038 | LLS action recommendations index | Content | `kilo_output/drafts/lls_action_history_YYYY-MM-DD.md` |
| EG-039 | RERA project enrichment gaps | DB | `kilo_output/audits/rera_enrichment_gaps_YYYY-MM-DD.md` |
| EG-040 | Market narrative draft | Content | `kilo_output/drafts/market_narrative_MARKET_YYYY-MM-DD.md` |

---

---

## T-062 | Re-run T-046 integration test — all bugs now fixed
**Status:** DONE ❌ (2026-05-18 12:26 IST, failed)
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T2 — Commands
**Plan mode:** OpenRouter → any free model
**Act mode:** OpenRouter → same

**What to do:**
1. Verify stack is up: `docker compose ps` — all 4 services should be Up
2. **Delete today's stale RERA checkpoint** so Stage 1 re-runs scouts:
   `docker compose exec agents rm -rf outputs/yelahanka/checkpoints/`
3. Run full crew: `docker compose exec agents python crews/market_intel_crew.py --market Yelahanka`
4. Watch for Stage 1 completing (should see portal_scout, developer_scout, news_scout tasks in output)
5. After run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT COUNT(*) FROM rera_projects; SELECT COUNT(*) FROM listings; SELECT COUNT(*) FROM news_articles;"`
6. Check report: `docker compose exec agents ls outputs/yelahanka/` — new intel_report should exist

**Success:** Run completes, listings > 0 OR portal_scout ran and returned 0 (portal blocked, not code bug), intel_report exists.
**If listings still 0:** Copy exact Stage 2 log lines from crew.log. Note whether "[Crew] No portal_scout checkpoint — skipping" appears.
**Changelog:** `T-062 | integration test Yelahanka | PASS/FAIL | [rera=N listings=N news=N, duration=Xs] | Cline | YYYY-MM-DD HH:MM`

**Execution log (2026-05-18):**
- `docker compose ps` → services up (agents/postgres/ollama/redis/scheduler)
- Checkpoints cleared: `outputs/yelahanka/checkpoints/`
- Crew run reached Stage 1 (RERA scrape 165 rows) but **failed** during LLM call with:
  `litellm.exceptions.NotFoundError: litellm.NotFoundError: NotFoundError: OpenAIException - 404 page not found`
- Post-run DB counts: `rera_projects=453`, `listings=4`, `news_articles=0`
- `outputs/yelahanka/` listing shows no new `intel_report_*.txt` generated at run timestamp.

---

## T-063 | Add Stage 2 upsert for rera_detail_scout enriched data
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T3 — Code edit (single file, 20-30 lines)
**Plan mode:** NinRouter → Codex
**Act mode:** OpenRouter → free model

**Context:** rera_detail_scout runs as part of Stage 1 and saves enriched records (unit_mix, project_cost, completion_pct, amenities) to checkpoint "rera_detail_scout". But Stage 2 never reads this checkpoint — the enrichment is computed and discarded. This task wires Stage 2 to upsert enriched fields back into rera_projects.

**What to do:**
1. Read `crews/market_intel_crew.py` — find the scout upserts section (after kaveri upsert, around "Scout upserts" comment)
2. Add this block after the news_findings block:
```python
        rera_detail_findings = cp.load(market_name, "rera_detail_scout") or []
        if rera_detail_findings:
            detail_upserted = 0
            for rec in rera_detail_findings:
                rera_num = rec.get("rera_number", "")
                if not rera_num:
                    continue
                try:
                    from sqlalchemy import text as _text
                    with organizer.engine.begin() as conn:
                        conn.execute(_text("""
                            UPDATE rera_projects SET
                                total_units = COALESCE(NULLIF(:units, 0), total_units),
                                raw_data = raw_data || CAST(:extra AS jsonb),
                                last_scraped_at = NOW()
                            WHERE rera_number = :rn
                        """), {
                            "rn": rera_num,
                            "units": int(rec.get("total_units") or 0),
                            "extra": json.dumps({
                                "unit_mix": rec.get("unit_mix"),
                                "project_cost_crore": rec.get("project_cost_crore"),
                                "completion_pct": rec.get("completion_pct"),
                                "amenities": rec.get("amenities"),
                            }),
                        })
                        detail_upserted += 1
                except Exception as exc:
                    logger.error(f"[Crew] rera_detail upsert failed for {rera_num}: {exc}")
            print(f"  RERA Detail Scout: {detail_upserted} records enriched in DB")
        else:
            logger.info("[Crew] No rera_detail_scout checkpoint — skipping")
```
3. Add `import json` near top if not already present (search first — it likely is)

**Files to touch:** READ+WRITE — `crews/market_intel_crew.py`
**Success check:** Code has no syntax errors. After next pipeline run, `SELECT total_units FROM rera_projects WHERE total_units > 0 LIMIT 5;` returns rows.
**If it fails:** Log error verbatim. Mark NEEDS-FIX.

**Changelog:** `T-063 | crews/market_intel_crew.py | added rera_detail_scout Stage 2 upsert | Cline | YYYY-MM-DD HH:MM`

---

## T-064 | Market expansion — Devanahalli + Hebbal
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-062
**Priority:** MEDIUM
**Task Tier:** T2 — Commands

**What to do:**
1. Verify T-062 PASSED
2. `docker compose exec agents python crews/market_intel_crew.py --market Devanahalli`
3. Wait for completion. Log counts.
4. `docker compose exec agents python crews/market_intel_crew.py --market Hebbal`
5. Log counts for both.

**Changelog:** `T-064 | market expansion | Devanahalli=PASS/FAIL, Hebbal=PASS/FAIL | [rera=N listings=N each] | Cline | YYYY-MM-DD HH:MM`

---

## T-065 | Dashboard: wire /api/agents endpoint to live DB
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-062
**Priority:** HIGH
**Task Tier:** T3 — Code edit
**Plan mode:** NinRouter → Codex
**Act mode:** OpenRouter → free model

**Context:** Dashboard currently returns hardcoded/static data for most endpoints. The dashboard audit (T-059) found `/api/agents` is in-memory (not DB-backed). This task wires it to the `agent_runs` table so the org chart shows real agent activity.

**What to do:**
1. Read `dashboard/app.py` — find the `/api/agents` route (or the closest route that serves agent status data)
2. Find the route that the cabin cards poll for their state — likely `/api/status` or `/api/agents`
3. Replace the hardcoded response with a DB query:
```python
with psycopg2.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT agent_name, status, records_inserted, completed_at
            FROM agent_runs
            ORDER BY completed_at DESC NULLS LAST
            LIMIT 20
        """)
        rows = cur.fetchall()
        agents = [{"name": r[0], "status": r[1], "records": r[2], "last_run": str(r[3])} for r in rows]
return jsonify({"agents": agents})
```
4. Import psycopg2 + DATABASE_URL at top if not already present

**Files to touch:** READ+WRITE — `dashboard/app.py`
**Success check:** `curl http://localhost:8050/api/agents` (or equivalent from host) returns real agent_runs data

**Changelog:** `T-065 | dashboard/app.py | /api/agents wired to agent_runs table | Cline | YYYY-MM-DD HH:MM`

---

## T-066 | Dashboard: wire /api/intel endpoint — serve latest intel report
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-065
**Priority:** HIGH
**Task Tier:** T3 — Code edit
**Plan mode:** NinRouter → Codex
**Act mode:** OpenRouter → free model

**Context:** Dashboard needs to show the latest intel report in the browser. T-059 confirmed `/api/reports/{market}` is file-based (reads `outputs/`). This task wires it correctly and adds a `/api/intel` endpoint that returns the latest report for any market.

**What to do:**
1. Read `dashboard/app.py` — find `/api/reports/<market>` route
2. Check: does it read the latest `intel_report_*.txt` from `outputs/{market}/`? If yes, just verify it works.
3. If no `/api/intel` route exists: add one that:
   - Lists `outputs/` for the latest file matching `intel_report_*.txt`
   - Returns the file contents as plain text
   - Accepts `?market=Yelahanka` query param
4. In the HTML template: add a text panel that polls `/api/intel?market=Yelahanka` and shows the report content

**Files to touch:** READ+WRITE — `dashboard/app.py`, `dashboard/templates/index.html`
**Success check:** Browser shows latest intel report text in dashboard panel

**Changelog:** `T-066 | dashboard | /api/intel endpoint + HTML panel wired | Cline | YYYY-MM-DD HH:MM`

---

## T-067 | Dashboard: expose port 8050 in docker-compose.yml
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-062
**Priority:** MEDIUM
**Task Tier:** T1 — Tiny edit
**Plan mode:** OpenRouter → any free model
**Act mode:** OpenRouter → same

**What to do:**
1. Read `docker-compose.yml` — check if `ports: - "8050:8050"` is already present under `agents` service
2. Read `dashboard/app.py` — confirm port (`app.run(host='0.0.0.0', port=8050)`)
3. If port mapping missing: add it. If present: verify correct port, mark DONE.
4. `docker compose up -d agents` and verify: `curl http://localhost:8050/api/health` returns 200

**Changelog:** `T-067 | docker-compose.yml | port 8050 verified/added for dashboard | Cline | YYYY-MM-DD HH:MM`

---

## T-068 | Dashboard: scout log patterns in monitor thread
**Status:** BLOCKED
**Brain:** Cline
**Phase:** P2
**Blocked by:** T-062
**Priority:** MEDIUM
**Task Tier:** T3 — Code edit
**Plan mode:** NinRouter → Codex
**Act mode:** OpenRouter → free model

**Context:** Dashboard has a log monitor thread that reads crew.log and updates cabin state. It only knows about the original 3 agents. The 4 new scouts need their own log patterns.

**What to do:**
1. Read `dashboard/app.py` — find the monitor thread (search for `tail`, `crew.log`, `monitor`)
2. Find the pattern list that updates cabin state (e.g., `[RERA]`, `[Listings]`)
3. Add patterns for: `[PortalScout]`, `[DeveloperScout]`, `[NewsScout]`, `[RERADetailScout]`
4. Map each to the scraper cabin state change: e.g., seeing `[PortalScout]` → scraper cabin = SCRAPING

**Changelog:** `T-068 | dashboard/app.py | added 4 scout log patterns to monitor thread | Cline | YYYY-MM-DD HH:MM`

---

## T-069 | Fix sentinel_agent __main__ block (T-010 enabler)
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** LOW
**Task Tier:** T1 — Tiny edit (10 lines)
**Plan mode:** OpenRouter → any free model
**Act mode:** OpenRouter → same

**Context:** T-010 added a Docker healthcheck to the agents service pointing to sentinel_agent.py. But sentinel_agent.py has no `if __name__ == "__main__":` block that exits 0 on health and 1 on failure, so Docker healthcheck can't evaluate it.

**What to do:**
1. Read `agents/sentinel_agent.py` — find the end of the file
2. Add a `__main__` block at the bottom:
```python
if __name__ == "__main__":
    import sys
    try:
        # Basic health: can we import our core deps and reach DB?
        from config.settings import DATABASE_URL
        from sqlalchemy import create_engine, text
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[sentinel] healthy")
        sys.exit(0)
    except Exception as e:
        print(f"[sentinel] unhealthy: {e}")
        sys.exit(1)
```
3. Save. Verify syntax: `docker compose exec agents python agents/sentinel_agent.py` → should print "[sentinel] healthy" and exit 0.

**Files to touch:** READ+WRITE — `agents/sentinel_agent.py`
**Success check:** `docker compose exec agents python agents/sentinel_agent.py` exits 0 and prints healthy

**Changelog:** `T-069 | agents/sentinel_agent.py | added __main__ health block | Cline | YYYY-MM-DD HH:MM`

---

## T-070 | Audit portal_scout output — verify cid field in all records
**Status:** DONE ✅ — Kilo Code 2026-05-17 21:33. `cid` is set in `_normalize()` (portal_scout.py:217/219/221) — every non-None record carries `cid`; `mark_all()` reads it but does not add it. Records without cid-equivalent data are dropped as `None` before reaching `mark_all()`. Risk: LOW. Output: `kilo_output/audits/portal_scout_cid_check.md`
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T0 — Read-only

**Context:** T-062 may still show listings=0 if portal_scout records are missing the `cid` field. `_upsert_listing_by_cid()` raises ValueError for any record without `cid`, silently failing all insertions.

**What to do:**
1. Read `scrapers/portal_scout.py` — find where records are built before being returned
2. Check: does every record dict have a `cid` key set? What function sets it? (look for `cid_project`, `cid_listing`, or `memory.mark_all()`)
3. Read `scrapers/scout_memory.py` — check `mark_all()` — does it add `cid` to each record?
4. Note: if `cid` is only set in mark_all(), records returned from `scout.scout()` will have it. But if portal_scout short-circuits before mark_all(), records won't have `cid`.
5. Do NOT fix anything

**Output:** Write findings to `kilo_output/audits/portal_scout_cid_check.md`
**Log format:** `## T-070 | portal_scout cid audit | DONE | 2026-05-17 21:33` then: `cid_set_in=_normalize()@portal_scout.py | all_records_have_cid=yes | risk=low`

---

## T-071 | Audit rera_detail_scout checkpoint — verify enriched fields
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** MEDIUM
**Task Tier:** T0 — Read-only

**Context:** T-063 adds Stage 2 upsert for rera_detail_scout enriched records. Before Cline runs T-063, Claude needs to know: does the checkpoint actually have unit_mix / project_cost_crore / completion_pct? If rera_detail_scout is failing silently, the checkpoint may be empty.

**What to do:**
1. Read `scrapers/rera_detail_scout.py` — find `_enrich_project()` — list all fields it returns in the enriched dict
2. Check: is the enriched dict returned only when AI extraction succeeds? Or always (with null fields)?
3. Find if there's a minimum content gate (e.g., `if len(text) < 100: return None`) that might cause all projects to fail enrichment
4. Do NOT fix anything

**Output:** Write findings to `kilo_output/audits/rera_detail_enrichment_fields.md`
**Log format:** `## T-071 | rera_detail enrichment audit | DONE | YYYY-MM-DD` then: `fields={list} | returns_on_ai_fail={yes(null fields)/no(None)} | gate={threshold}`

---

## T-072 | Audit market_intel_crew.py Stage 1 cache fix correctness
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T0 — Read-only

**Context:** Claude fixed the Stage 1 cache skip on 2026-05-17 — changed from "skip if rera_scraped exists" to "skip only if ALL 4 scout checkpoints exist". Kilo Code should verify the fix was written correctly in the file.

**What to do:**
1. Read `crews/market_intel_crew.py` — find the Stage 1 section (search for "STAGE 1" comment)
2. Find the `if cp.exists(...)` block — check: does it now check all 4 checkpoints (rera_scraped, portal_scout, developer_scout, news_scout)?
3. Note the exact condition written and confirm it is logically correct (all 4 must exist to skip)
4. Do NOT change anything

**Output:** Write findings to `kilo_output/audits/stage1_cache_fix.md`
**Log format:** `## T-072 | Stage 1 cache fix audit | DONE | YYYY-MM-DD` then: `fix_correct={yes/no} | condition={exact text}`

---

## T-073 | Draft spec for adding duration_seconds to kaveri + portal run logs
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** —
**Priority:** LOW
**Task Tier:** T0 — Read-only + draft

**Context:** `_log_run()` in db_organizer.py now correctly writes duration_seconds for the RERA ingest path. But `run_portal_scout()`, `run_developer_scout()`, `run_news_scout()`, and `run_kaveri()` do NOT call `_log_run()` — their runs are not logged to agent_runs at all.

**What to do:**
1. Read `utils/db_organizer.py` — find `run_portal_scout`, `run_developer_scout`, `run_news_scout`, `run_kaveri` — confirm they do NOT call `_log_run()`
2. Draft a spec for adding logging to each: which `task_type` string to use, where to insert the `_log_run()` call, what stats dict to pass
3. Write draft to `kilo_output/queue/spec_portal_logging_draft.md`

**Output:** `kilo_output/queue/spec_portal_logging_draft.md`
**Log format:** `## T-073 | portal run logging spec | DONE | YYYY-MM-DD`

---

## T-074 | Audit dashboard/app.py /api/agents — what data it currently returns
**Status:** READY
**Brain:** Kilo Code
**Phase:** P2
**Blocked by:** —
**Priority:** MEDIUM
**Task Tier:** T0 — Read-only

**Context:** T-065 will wire /api/agents to the DB. Before Cline does this, Kilo Code should confirm: what does the route currently return? (hardcoded JSON? in-memory state?) and what is the cabin polling interval?

**What to do:**
1. Read `dashboard/app.py` — find the `/api/agents` route (or equivalent — may be `/api/status`)
2. Note: what data structure it returns currently
3. Note: polling interval in `index.html` (search for `setInterval` or `fetch(/api/`)
4. Note: which cabin uses which field from the response

**Output:** Write to `kilo_output/audits/api_agents_current_state.md`
**Log format:** `## T-074 | /api/agents audit | DONE | YYYY-MM-DD` then: `route={path} | data_source={hardcoded/db/memory} | poll_interval={ms}`

---

## T-075 | Audit news_articles table — verify rows inserted after Stage 2 run
**Status:** READY
**Brain:** Kilo Code
**Phase:** P1
**Blocked by:** T-062
**Priority:** MEDIUM
**Task Tier:** T0 — One SELECT query + read

**Context:** news_articles table was created on 2026-05-16 #3 session. T-062 will be the first run where run_news_scout() can write to it. Kilo Code should verify rows appear after T-062.

**What to do:**
1. After T-062 DONE: run `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT COUNT(*), MIN(published_at), MAX(published_at) FROM news_articles;"`
2. If 0 rows: check crew.log for "[Organizer] news_articles table missing" or "[Crew] No news_scout checkpoint — skipping"
3. Note the count and date range

**Output:** Write to `kilo_output/audits/news_articles_post_run.md`
**Log format:** `## T-075 | news_articles audit | DONE | YYYY-MM-DD` then: `count={N} | date_range={min–max} | status={populated/empty}`

---

---

## T-076 | Audit portal_scout.py — all silent fail paths
**Status:** DONE ✅ | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
**Resolution (2026-05-17):** 2 ZERO-log paths: ImportError at line 332 and non-200 HTTP at line 321. 3 DEBUG-only paths: lines 325, 350, 166.
Output: `kilo_output/audits/portal_scout_silent_fails.md`

---

## T-077 | Audit developer_scout.py — verify T-042 sampling fix in file
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read `scrapers/developer_scout.py`. Find `_ai_extract_developer`. Verify: (1) sampling is start+middle (5k+5k) not first 6k; (2) `wait_for_timeout` is 6000ms not 3000ms; (3) content fallback threshold is 500 chars not 200.
**Output:** `kilo_output/audits/developer_scout_t042_verify.md`
**Log:** `## T-077 | developer_scout T-042 verify | DONE | YYYY-MM-DD | sampling={correct/wrong} timeout={6000/other} threshold={500/other}`

---

## T-078 | Audit news_scout.py — verify T-041 days_back fix + NEWS_QUERIES years
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read `scrapers/news_scout.py`. Verify: (1) default `days_back` in `_fetch_google_news_rss()`, `scout()`, `scout_news()`, argparse is 60 (not 14); (2) NEWS_QUERIES has year 2026 (not 2025); (3) ET Realty non-200 is logged.
**Output:** `kilo_output/audits/news_scout_t041_verify.md`
**Log:** `## T-078 | news_scout T-041 verify | DONE | YYYY-MM-DD | days_back={60/other} year={2026/other}`

---

## T-079 | Audit listings_scraper.py — superseded or still used?
**Status:** DONE ✅ | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
**Resolution (2026-05-17):** ACTIVELY USED — `ListingsScraperTool` registered in `scraper_agent.py:254-263`, `listings_scraper` is the tool name. Partially redundant with `PortalScoutTool` (both pull from 99acres/MagicBricks; portal_scout is AI-extracted with richer output). Do not remove from tool list without explicit decision.
Output: `kilo_output/audits/listings_scraper_usage.md`

## T-080 | Audit kaveri_karnataka.py — silent failure paths
**Status:** DONE ✅ | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
**Resolution (2026-05-17):** ZERO silent paths — cleanest scraper in codebase. All 10 error branches produce WARNING or above. Hardcoded fallback (74–97 + 100–277) is ultimate safety net; never returns nothing.
Output: `kilo_output/audits/kaveri_silent_fails.md`

## T-081 | Audit rera_karnataka.py — fallback triggers
**Status:** DONE ✅ | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
**Resolution (2026-05-17):** 3 fallback triggers (all WARNING-level logged): (1) missing RERA config at line 71, (2) portal returns 0 after 3 retries at line 78, (3) both above fire → `_fallback_rera_data()` at line 212 yields 8 Yelahanka + 2 Devanahalli sample records tagged `source: "fallback_sample"`.
Output: `kilo_output/audits/rera_fallback_triggers.md`

## T-082 | Audit config/checkpointer.py — format, TTL, edge cases
**Status:** DONE ✅ | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
**Resolution (2026-05-17):** JSON format, no TTL logic, implicit TTL via daily filename. Two edge cases: (1) `json.JSONDecodeError` not caught on corrupted file — crashes Stage 1, (2) no locking in `save()` — simultaneous writes lose-race silently. Force re-run requires manual `rm -rf outputs/{market}/checkpoints/`.
Output: `kilo_output/audits/checkpointer_behavior.md`

---

## T-083 | Audit config/run_logger.py — what it writes vs agent_runs needs
**Status:** DONE ✅ | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
**Resolution (2026-05-18):** run_logger.py JSONL: 12 fields (run_id, market, run_type, start/end_time, duration_seconds, status, error, error_type, agents_completed, report_path, notes). agent_runs DB: 14 columns (id PK, agent_name, task_type, micro_market, status, records_*/error_message/metadata/started_at/completed_at/duration_seconds). Different-level abstractions — JSONL = 1 row per pipeline run, DB = 1 row per agent task. 5 shared fields (status, error/duration_seconds). User-focused: no structural sync. Primary live-gap: agent_runs.completed_at was never populated (fixed in T-054). Output: `kilo_output/audits/run_logger_vs_agent_runs.md`
**Log:** `## T-083 | run_logger vs agent_runs | DONE | 2026-05-18 | jsonl_only=12, db_only=born_from=0`

---

## T-084 | Audit agents/analyst_agent.py — repeated tool call prevention
**Status:** READY | **Brain:** Kilo Code | **Phase:** P2 | **Tier:** T0
Read `agents/analyst_agent.py`. Find: (1) the prompt/goal/backstory text — does it tell the analyst to call each tool ONCE? (2) Is max_iter=3 currently set? (3) Does the analyze task description say "call market_summary_query once"? T-019 (fix analyst loop) requires this context.
**Output:** `kilo_output/audits/analyst_tool_loop.md`
**Log:** `## T-084 | analyst tool loop | DONE | YYYY-MM-DD | max_iter={N} one_call_instruction={yes/no}`

---

## T-085 | Audit agents/ceo_agent.py — verify 6-section output in practice
**Status:** READY | **Brain:** Kilo Code | **Phase:** P2 | **Tier:** T0
Read `agents/ceo_agent.py`. Read the latest intel_report in `outputs/yelahanka/`. Find: do 6 sections appear in the actual output, or does the CEO produce unstructured prose? List the sections found (or missing). T-020 needs this gap.
**Output:** `kilo_output/audits/ceo_output_vs_spec.md`
**Log:** `## T-085 | CEO output vs spec | DONE | YYYY-MM-DD | sections_found={N/6} structured={yes/no}`

---

## T-086 | Audit utils/validator.py — all validation rules
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read `utils/validator.py`. List EVERY validation rule as a table: field, rule, what happens on fail (skip record, fill default, raise). Note: what is the current pass rate expectation? Are any rules too strict (rejecting valid records)?
**Output:** `kilo_output/audits/validator_rules.md`
**Log:** `## T-086 | validator rules | DONE | YYYY-MM-DD | N rules | strictest={field_name}`

---

## T-087 | Audit crews/market_intel_crew.py — _EXCLUDED.clear() call sites
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read `crews/market_intel_crew.py`. Find every `_EXCLUDED.clear()` call. Verify: is it called on BOTH success and failure paths of `_kickoff_with_fallback`? Is it called after each market in `run_all_markets()`? Missing calls = provider exclusions bleed between markets.
**Output:** `kilo_output/audits/excluded_clear_calls.md`
**Log:** `## T-087 | _EXCLUDED.clear audit | DONE | YYYY-MM-DD | clear_on_success={yes/no} clear_on_fail={yes/no} clear_between_markets={yes/no}`

---

## T-088 | DB: count rows in ALL 12 tables
**Status:** DONE ✅ | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
**Resolution (2026-05-17):** 6 of 12 tables populated: rera_projects=165, developers=144, guidance_values=15, kaveri_registrations=45, micro_markets=20, agent_runs=29. listings=0 (portal_scout not yet wired), 3 Phase 3 tables=0 (expected).
**Output:** `kilo_output/summaries/all_table_counts_2026-05-17.md`
**Log:** `## T-088 | all table counts | DONE | 2026-05-17 | rera_projects=165 listings=0 agent_runs=29`

---

## T-089 | DB: developer grade distribution
**Status:** DONE ✅ | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
**Resolution (2026-05-17):** Grade A=14 (9.7%), B=0, C=130 (90.3%), NULL=0. No B-grade and no ungraded developers. Grading logic likely uses binary thresholds; recommend verifying whether B label is categorically impossible or just sparsely populated.
**Output:** `kilo_output/summaries/developer_grades_2026-05-17.md`
**Log:** `## T-089 | developer grades | DONE | 2026-05-17 | A=14 B=0 C=130 ungraded=0`

---

## T-090 | DB: stale rera_projects records
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT COUNT(*) stale FROM rera_projects WHERE last_scraped_at < NOW() - INTERVAL '7 days';"`
Also: count those with `last_scraped_at IS NULL`. Flag if >50% of records are stale.
**Output:** `kilo_output/audits/stale_records_YYYY-MM-DD.md`
**Log:** `## T-090 | stale records | DONE | YYYY-MM-DD | stale_7d=N null_scraped=N pct=X%`

---

## T-091 | DB: market coverage — which micro_markets have data?
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT m.name, COUNT(r.id) projects FROM micro_markets m LEFT JOIN rera_projects r ON r.micro_market_id = m.id GROUP BY m.name ORDER BY 2 DESC;"`
Flag any configured market with 0 projects.
**Output:** `kilo_output/summaries/market_coverage_YYYY-MM-DD.md`
**Log:** `## T-091 | market coverage | DONE | YYYY-MM-DD | yelahanka=N devanahalli=N hebbal=N`

---

## T-092 | DB: listings unique constraint verification
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read `database/schema.sql` — find the `listings` table definition. Note: exact columns in the UNIQUE/PRIMARY constraint. Check: is `(source, source_listing_id)` the unique key? Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT source, COUNT(*) FROM listings GROUP BY source;"` to see source distribution.
**Output:** `kilo_output/audits/listings_constraint_YYYY-MM-DD.md`
**Log:** `## T-092 | listings constraint | DONE | YYYY-MM-DD | unique_on={cols} sources={list}`

---

## T-093 | DB: agent_runs by status
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT status, COUNT(*) FROM agent_runs GROUP BY status; SELECT agent_name, COUNT(*) FROM agent_runs GROUP BY agent_name ORDER BY 2 DESC;"`
**Output:** `kilo_output/summaries/agent_runs_status_YYYY-MM-DD.md`
**Log:** `## T-093 | agent_runs status | DONE | YYYY-MM-DD | completed=N failed=N agents={list}`

---

## T-094 | DB: guidance_values — populated or empty?
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT market, COUNT(*), AVG(guidance_value_psf) avg_psf FROM guidance_values gv JOIN micro_markets m ON gv.micro_market_id = m.id GROUP BY market;"`
If 0 rows: Kaveri scraper returning 0 GV records — flag for investigation.
**Output:** `kilo_output/summaries/guidance_values_YYYY-MM-DD.md`
**Log:** `## T-094 | guidance_values | DONE | YYYY-MM-DD | total=N markets_covered={list}`

---

## T-095 | DB: kaveri_registrations — populated or empty?
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT COUNT(*), MIN(transaction_date), MAX(transaction_date), AVG(transaction_amount) FROM kaveri_registrations;"`
**Output:** `kilo_output/summaries/kaveri_registrations_YYYY-MM-DD.md`
**Log:** `## T-095 | kaveri_registrations | DONE | YYYY-MM-DD | total=N date_range={min-max}`

---

## T-096 | DB: project_snapshots — populated or empty?
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT COUNT(*) FROM project_snapshots;"`
If 0: note "project_snapshots never populated — no scraper writes to it currently."
**Output:** `kilo_output/audits/project_snapshots_status.md`
**Log:** `## T-096 | project_snapshots | DONE | YYYY-MM-DD | count=N`

---

## T-097 | DB: regulatory_zones + overlay_constraints + infra_pipeline status
**Status:** READY | **Brain:** Kilo Code | **Phase:** P3 | **Tier:** T0
Run COUNT(*) on all three. These are Phase 3 tables. If all empty: note "Phase 3 tables unpopulated — expected at this stage."
**Output:** `kilo_output/audits/phase3_tables_status.md`
**Log:** `## T-097 | phase3 tables | DONE | YYYY-MM-DD | reg_zones=N overlay=N infra=N`

---

## T-098 | DB: top 10 developers by project count
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT d.name, d.grade, COUNT(r.id) projects FROM developers d LEFT JOIN rera_projects r ON r.developer_id = d.id GROUP BY d.name, d.grade ORDER BY 3 DESC LIMIT 10;"`
**Output:** `kilo_output/summaries/top_developers_YYYY-MM-DD.md`
**Log:** `## T-098 | top developers | DONE | YYYY-MM-DD | top={dev_name N projects}`

---

## T-099 | DB: rera_projects with total_units=0
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT COUNT(*) zero_units, (SELECT COUNT(*) FROM rera_projects) total FROM rera_projects WHERE total_units = 0;"`
High zero count means RERA listing page doesn't provide unit counts — rera_detail_scout enrichment is critical.
**Output:** `kilo_output/audits/zero_units_records.md`
**Log:** `## T-099 | zero_units records | DONE | YYYY-MM-DD | zero=N total=N pct=X%`

---

## T-100 | DB: rera_projects missing developer_id
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT COUNT(*) FROM rera_projects WHERE developer_id IS NULL;"` and `SELECT project_name FROM rera_projects WHERE developer_id IS NULL LIMIT 5;`
**Output:** `kilo_output/audits/orphaned_projects.md`
**Log:** `## T-100 | orphaned projects | DONE | YYYY-MM-DD | no_dev_id=N examples={list}`

---

## T-101 | DB: rera_projects missing micro_market_id
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT COUNT(*) unclassified FROM rera_projects WHERE micro_market_id IS NULL;"` and sample 5 with locality field.
**Output:** `kilo_output/audits/unclassified_projects.md`
**Log:** `## T-101 | unclassified projects | DONE | YYYY-MM-DD | no_market_id=N sample_localities={list}`

---

## T-102 | DB: possession_date distribution — how many overdue?
**Status:** READY | **Brain:** Kilo Code | **Phase:** P2 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT COUNT(*) overdue FROM rera_projects WHERE possession_date < NOW() AND project_status NOT ILIKE '%complet%';"` and count by year bucket.
**Output:** `kilo_output/summaries/possession_date_distribution.md`
**Log:** `## T-102 | possession dates | DONE | YYYY-MM-DD | overdue=N total_with_date=N`

---

## T-103 | DB: v_market_brief view — run and summarize
**Status:** READY | **Brain:** Kilo Code | **Phase:** P2 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT * FROM v_market_brief;"` If view fails: note the error. If succeeds: write all rows to output.
**Output:** `kilo_output/summaries/v_market_brief_YYYY-MM-DD.md`
**Log:** `## T-103 | v_market_brief | DONE | YYYY-MM-DD | rows=N or error={msg}`

---

## T-104 | DB: v_developer_scorecard view — run and summarize
**Status:** READY | **Brain:** Kilo Code | **Phase:** P2 | **Tier:** T0
Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT * FROM v_developer_scorecard LIMIT 10;"` Write full output.
**Output:** `kilo_output/summaries/v_developer_scorecard_YYYY-MM-DD.md`
**Log:** `## T-104 | v_developer_scorecard | DONE | YYYY-MM-DD | rows=N or error={msg}`

---

## T-105 | Inventory all intel_report_*.txt files
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
List all files matching `outputs/*/intel_report_*.txt`. For each: market, date, file size in bytes. Flag any <500 bytes (likely empty/fallback). Note which markets have reports and which are missing.
**Output:** `kilo_output/summaries/intel_report_inventory_YYYY-MM-DD.md`
**Log:** `## T-105 | intel report inventory | DONE | YYYY-MM-DD | total=N empty=N markets={list}`

---

## T-106 | Read latest intel report — flag fallback markers
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read the newest `intel_report_*.txt` in `outputs/yelahanka/`. Search for: "[FALLBACK SAMPLE]", "[ESTIMATED]", "CEO synthesis unavailable", "no data", "0 projects". Count each. If any present: note which sections are degraded.
**Output:** `kilo_output/audits/intel_report_quality_YYYY-MM-DD.md`
**Log:** `## T-106 | intel report quality | DONE | YYYY-MM-DD | fallback_markers=N quality={high/medium/low}`

---

## T-107 | Compare two intel reports — PSF + absorption delta
**Status:** READY | **Brain:** Kilo Code | **Phase:** P2 | **Tier:** T0
Find the two most recent `intel_report_*.txt` files in `outputs/yelahanka/`. Extract PSF range and absorption rate from each. Calculate delta. If values are identical or missing: note "no meaningful delta — likely same data source both runs."
**Output:** `kilo_output/drafts/intel_delta_yelahanka_YYYY-MM-DD.md`
**Log:** `## T-107 | intel delta | DONE | YYYY-MM-DD | psf_delta={N} absorption_delta={N%}`

---

## T-108 | Audit kilo_output/queue/ — unactioned spec drafts
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
List all files in `kilo_output/queue/`. For each: filename, creation date, which task it specs, and whether that task is still BLOCKED/READY or already DONE. Flag any spec draft that was written but the corresponding task never got actioned.
**Output:** `kilo_output/audits/queue_spec_status_YYYY-MM-DD.md`
**Log:** `## T-108 | queue spec audit | DONE | YYYY-MM-DD | specs=N actioned=N unactioned=N`

---

## T-109 | Audit kilo_output/drafts/ — summarize wiki draft key claims
**Status:** READY | **Brain:** Kilo Code | **Phase:** P2 | **Tier:** T0
Read all files in `kilo_output/drafts/`. For each wiki/intel draft: extract 3 key claims (PSF, absorption, top developer, or LLS recommendation). Compile into a master summary table.
**Output:** `kilo_output/summaries/draft_claims_index_YYYY-MM-DD.md`
**Log:** `## T-109 | draft claims index | DONE | YYYY-MM-DD | drafts=N claims=N`

---

## T-110 | Silent failure audit — scrapers/ directory
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read all .py files in `scrapers/`. Find EVERY `except` block that returns an empty collection (`[]`, `{}`, `""`, `None`) WITHOUT logging first. List: file, line number, what exception is swallowed, what data is lost. This is the root cause catalog for silent zeros.
**Output:** `kilo_output/audits/scrapers_silent_failures_YYYY-MM-DD.md`
**Log:** `## T-110 | scrapers silent failures | DONE | YYYY-MM-DD | N silent except blocks across N files`

---

## T-111 | Dead import finder — agents/ directory
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read each .py in `agents/`. For each `import X` or `from X import Y`: check if `X` or `Y` appears anywhere else in the file body. List imports that appear ONLY in the import line — likely unused.
**Output:** `kilo_output/audits/dead_imports_agents_YYYY-MM-DD.md`
**Log:** `## T-111 | dead imports agents | DONE | YYYY-MM-DD | N suspect imports across N files`

---

## T-112 | Dead import finder — scrapers/ directory
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Same as T-111 but for `scrapers/` directory. Pay special attention to unused AI/LLM imports that add latency on startup.
**Output:** `kilo_output/audits/dead_imports_scrapers_YYYY-MM-DD.md`
**Log:** `## T-112 | dead imports scrapers | DONE | YYYY-MM-DD | N suspect imports`

---

## T-113 | TODO/FIXME tracker — full codebase
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read all .py files in `agents/`, `scrapers/`, `utils/`, `config/`, `crews/`. Find all TODO, FIXME, HACK, XXX, TEMP, DEPRECATED comments. Group by file. Include line number and full comment text.
**Output:** `kilo_output/audits/todo_fixme_full_YYYY-MM-DD.md`
**Log:** `## T-113 | todo/fixme | DONE | YYYY-MM-DD | N items across N files | most in={filename}`

---

## T-114 | Function length audit — scrapers/ + crews/
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read all .py in `scrapers/` and `crews/`. Find every function definition. Count its lines (from `def` to next `def`/EOF). Flag any function >50 lines. Include: file, function name, line count. Longest function is a refactor candidate.
**Output:** `kilo_output/audits/long_functions_YYYY-MM-DD.md`
**Log:** `## T-114 | long functions | DONE | YYYY-MM-DD | N functions >50 lines | longest={name N lines}`

---

## T-115 | API key coverage check — settings.py
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read `config/settings.py`. For each API key variable (CEREBRAS_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, NVIDIA_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY_1 through _4): note whether it reads from env, has a non-empty default fallback, and whether it would silently be empty string if unset. Do NOT log actual key values.
**Output:** `kilo_output/audits/api_key_coverage_YYYY-MM-DD.md`
**Log:** `## T-115 | api key coverage | DONE | YYYY-MM-DD | N keys | N empty_if_unset`

---

## T-116 | Docker service health check
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Run: `docker compose ps`. For each of the 5 services (postgres, redis, ollama, agents, scheduler): note Up/Down/Restarting/Unhealthy status. Note uptime. Flag any service not Up.
**Output:** `kilo_output/summaries/docker_health_YYYY-MM-DD.md`
**Log:** `## T-116 | docker health | DONE | YYYY-MM-DD | all_up={yes/no} issues={list}`

---

## T-117 | Disk usage check
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Check sizes of `outputs/`, `logs/`, `kilo_output/`, `kilo_logs/`. Use PowerShell: `(Get-ChildItem 'path' -Recurse | Measure-Object -Property Length -Sum).Sum`. Flag any dir >200MB. Find the 3 largest files.
**Output:** `kilo_output/summaries/disk_usage_YYYY-MM-DD.md`
**Log:** `## T-117 | disk usage | DONE | YYYY-MM-DD | outputs=XMB logs=XMB kilo=XMB`

---

## T-118 | Scheduler next run check
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read `config/scheduler.py`. Find the APScheduler job: cron expression, target function, which markets it runs. Run `docker compose ps scheduler` to verify it is Up. Note: is the 2AM RERA refresh still configured, or has it changed?
**Output:** `kilo_output/summaries/scheduler_status_YYYY-MM-DD.md`
**Log:** `## T-118 | scheduler | DONE | YYYY-MM-DD | cron={expr} target={fn} running={yes/no}`

---

## T-119 | Scout memory dedup stats
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Find the scout_memory storage. Read `scrapers/scout_memory.py` — find where it stores CIDs (JSON file or DB?). If JSON: read the file for Yelahanka, count entries per prefix (rera:, listing:, project:, dev:, news:). If DB: run SELECT COUNT per type.
**Output:** `kilo_output/audits/scout_memory_stats_YYYY-MM-DD.md`
**Log:** `## T-119 | scout memory | DONE | YYYY-MM-DD | rera=N listing=N project=N dev=N news=N`

---

## T-120 | Checkpoint freshness — all files
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
List all files under `outputs/` matching `*checkpoint*` or in `checkpoints/` dirs. For each: note filename, last modified date, age in days. Flag any checkpoint older than 2 days — means that scout hasn't refreshed.
**Output:** `kilo_output/audits/checkpoint_freshness_YYYY-MM-DD.md`
**Log:** `## T-120 | checkpoint freshness | DONE | YYYY-MM-DD | fresh=N stale=N oldest={name age}`

---

## T-121 | Log file size monitor
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Check sizes of `logs/crew.log` and `logs/run_history.jsonl`. Count line count for each. Flag `crew.log` if >5MB (needs rotation). Note the timestamp of the oldest and newest log entry.
**Output:** `kilo_output/audits/log_sizes_YYYY-MM-DD.md`
**Log:** `## T-121 | log sizes | DONE | YYYY-MM-DD | crew_log=XMB lines=N needs_rotation={yes/no}`

---

## T-122 | Cross-check AGENTS.md vs current tool stack
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read `AGENTS.md`. Check each brain listed (Claude, Cline, Kilo Code, Gemini CLI, Aider, OpenCode) against `TOOL_GUIDE.md`. Find: any brain in AGENTS.md that has been removed/replaced. Find: any new tool in TOOL_GUIDE.md not yet in AGENTS.md. Note any outdated instructions.
**Output:** `kilo_output/audits/agents_md_drift.md`
**Log:** `## T-122 | AGENTS.md drift | DONE | YYYY-MM-DD | N stale entries | N missing entries`

---

## T-123 | Audit VISION.md — phase count vs DEVLOG.md
**Status:** READY | **Brain:** Kilo Code | **Phase:** P2 | **Tier:** T0
Read `VISION.md` — list the 14 phases and their names. Read `DEVLOG.md` (last 5 phases only — jump to bottom). Note: which phase are we currently on per DEVLOG? Does DEVLOG's current phase match VISION.md's roadmap? Flag any phase completed in DEVLOG but not marked done in VISION.
**Output:** `kilo_output/audits/vision_vs_devlog.md`
**Log:** `## T-123 | vision vs devlog | DONE | YYYY-MM-DD | current_phase=PN | next_in_vision={name}`

---

## T-124 | Audit .gitignore — outputs/, kilo_output/, logs/ excluded?
**Status:** READY | **Brain:** Kilo Code | **Phase:** P1 | **Tier:** T0
Read `.gitignore`. Check: are `outputs/`, `kilo_output/`, `logs/`, `kilo_logs/`, `.env` all excluded? If any are missing from .gitignore: flag — these could accidentally be committed with API keys or large data files.
**Output:** `kilo_output/audits/gitignore_coverage.md`
**Log:** `## T-124 | gitignore | DONE | YYYY-MM-DD | outputs={excluded/missing} env={excluded/missing} N gaps`

---

## T-125 | Draft LLS action brief — chronological recommendation index
**Status:** READY | **Brain:** Kilo Code | **Phase:** P2 | **Tier:** T0
Read ALL `intel_report_*.txt` files across all markets in `outputs/`. For each report: extract the "LLS action" or "CEO recommendation" section (last paragraph, or any section mentioning LLS). Compile into a chronological index: date, market, one-line recommendation. What is the evolving picture? Are recommendations consistent or contradicting?
**Output:** `kilo_output/drafts/lls_action_brief_YYYY-MM-DD.md`
**Log:** `## T-125 | LLS action brief | DONE | YYYY-MM-DD | N reports indexed | consistent={yes/no}`

---

## ADDING NEW TASKS

When a review cycle reveals new work, Claude adds tasks here following the spec format above.
Claude assigns the next available T-XXX number and inserts the row in the INDEX + writes the DETAIL SPEC.

**Current last task ID: T-145**
**Next task ID to use: T-146**

---

*This file is the ground truth for all pending work. VISION.md has the strategic picture. AGENTS.md has the protocol. TASK_QUEUE.md has the jobs.*

---

## T-138 | Fix rera_detail_scout _build_detail_url() — wrong URL type
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** CRITICAL
**Task Tier:** T4 — Scraper/debug
**Plan mode:** NinRouter → Codex
**Act mode:** NinRouter → Codex

**Root cause (Kilo Code T-129 finding):**
`_build_detail_url()` currently builds `viewAllProjects?regNo=...` URLs. These return search-result pages (750 chars, nav-only). The actual project detail page is `viewAllProjectDetails?regNo=...`. Both requests and Playwright return the same nav-only content. AI extraction returns all-null JSON silently — no exception, no WARNING. Result: 30/30 records "enriched" but every field (total_units, unit_mix, site_area, approvals, completion_pct, amenities) is null.

**Fix:**
1. Open `scrapers/rera_detail_scout.py`
2. Find `_build_detail_url()` method
3. Change URL template from `viewAllProjects?regNo=` to `viewAllProjectDetails?regNo=`
4. Also: add a fallback — if Playwright returns <1000 chars, log WARNING "detail page returned nav-only content" and set all enriched fields to None explicitly (do not let AI infer null silently)
5. Test: `docker compose exec agents python scrapers/rera_detail_scout.py --market Yelahanka`
6. Verify: at least 1 record should have a non-null total_units or site_area field

**Files to touch:** `scrapers/rera_detail_scout.py`
**Success check:** At least 1 enriched record with non-null total_units in checkpoint file
**Changelog entry:** `T-138 | Fix rera_detail_scout URL + null logging | PASS/FAIL | [N enriched records / error] | Cline | YYYY-MM-DD HH:MM`

---

## T-139 | Fix news_scout Gemini 429 — add fallback on rate limit
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T3 — Code edit
**Plan mode:** NinRouter → Codex
**Act mode:** OpenRouter free

**Root cause (Kilo Code T-075 + EG-008 finding):**
`_ai_analyze_articles()` in `scrapers/news_scout.py` uses Gemini Flash exclusively. On Gemini 429 (daily quota exhausted at ~06:38 UTC), it hits a bare `except Exception → return []`. No retry, no fallback to Cerebras or NVIDIA. Result: news_articles table stays at 0 for the rest of the day.

**Fix:**
1. Open `scrapers/news_scout.py`
2. Find `_ai_analyze_articles()` method
3. Wrap the Gemini call in a try/except that:
   - On 429 or RateLimitError: log `WARNING: Gemini 429 in news_scout — falling back to Cerebras`
   - Retry with Cerebras 8b (use `get_light_llm()` from `config/llm_router.py`)
   - If Cerebras also fails: log `ERROR: all LLM fallbacks exhausted in news_scout — returning []`
4. Import `get_light_llm` from `config/llm_router.py` at top of file
5. Do NOT change the function signature or return type

**Files to touch:** `scrapers/news_scout.py`
**Success check:** Running with Gemini quota exhausted falls back and logs WARNING (can simulate by temporarily setting an invalid Gemini key)
**Changelog entry:** `T-139 | news_scout Gemini 429 fallback | DONE | [fallback to Cerebras added] | Cline | YYYY-MM-DD HH:MM`

---

## T-140 | Fix agent_runs status casing — SQL migration
**Status:** READY
**Brain:** Cline
**Phase:** P2
**Blocked by:** —
**Priority:** MEDIUM
**Task Tier:** T2 — Commands
**Plan mode:** OpenRouter free
**Act mode:** OpenRouter free

**Root cause (Kilo Code T-093/T-131 finding):**
`agent_runs.status` column has 4 distinct values: `completed`(29), `success`(1), `In Progress`(1), `in_progress`(1). Canonical value should be `completed` (lowercase, past tense). Mixed casing breaks any query filtering on status.

**Fix — 3 SQL migrations in order:**
```sql
-- 1. Normalize non-standard values
UPDATE agent_runs SET status = 'completed' WHERE status = 'success';
UPDATE agent_runs SET status = 'in_progress' WHERE status = 'In Progress';

-- 2. Add CHECK constraint
ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_status_check;
ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_status_check
  CHECK (status IN ('in_progress', 'completed', 'failed', 'skipped'));
```

**Then in `config/settings.py`:**
Add at the bottom:
```python
AGENT_RUN_STATUSES = ["in_progress", "completed", "failed", "skipped"]
```

**Steps:**
1. Run the two UPDATE statements via `docker compose exec re_os_db psql -U re_os_user -d re_os`
2. Run the ALTER TABLE statements
3. Add AGENT_RUN_STATUSES to `config/settings.py`
4. Verify: `SELECT DISTINCT status FROM agent_runs;` — should return only canonical values

**Files to touch:** `config/settings.py` (settings only — SQL via docker exec)
**Success check:** `SELECT DISTINCT status FROM agent_runs;` returns max 4 values, all lowercase
**Changelog entry:** `T-140 | agent_runs status casing fix | DONE | [N rows migrated] | Cline | YYYY-MM-DD HH:MM`

---

## T-141 | Fix .gitignore — add kilo_output/ and kilo_logs/
**Status:** READY
**Brain:** Cline
**Phase:** P1
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T1 — Tiny edit
**Plan mode:** OpenRouter free
**Act mode:** OpenRouter free

**Root cause (Kilo Code T-133 finding):**
`.gitignore` does not exclude `kilo_output/` or `kilo_logs/`. These are AI-generated audit/draft files — ~100+ files, ~1MB. They should never hit the repo. Risk: accidental `git add .` commits all of them.

**Fix:**
1. Open `.gitignore`
2. Find the section with `outputs/` and `logs/` entries
3. Append after those entries:
```
kilo_output/
kilo_logs/
```
4. Run `git status` to confirm the directories disappear from untracked list

**Files to touch:** `.gitignore`
**Success check:** `git status` no longer shows kilo_output/ or kilo_logs/ as untracked
**Changelog entry:** `T-141 | .gitignore fix — kilo_output + kilo_logs | DONE | Cline | YYYY-MM-DD HH:MM`

---

## T-142 | EG-019: Guidance value freshness audit
**Status:** READY
**Brain:** Kilo Code
**Phase:** P2
**Blocked by:** —
**Task Tier:** T0 — Read-only

**What to do:** Run EG-019 from the EVERGREEN TASKS table. Query guidance_values table — check `created_at` or `fetch_date` for all 15 records. Flag any older than 30 days as stale.
**Output:** `kilo_output/audits/guidance_value_freshness_2026-05-18.md`
**Log:** `kilo_logs/CHANGELOG.md`

---

## T-143 | EG-035: Multi-market intel comparison draft
**Status:** DONE
**Brain:** Kilo Code
**Phase:** P2
**Blocked by:** —
**Task Tier:** T0 — Read-only

**What to do:** Run EG-035 from the EVERGREEN TASKS table. Read all intel_report_*.txt files across all 3 markets (Yelahanka, Devanahalli, Hebbal). Compare PSF ranges, absorption rates, and supply counts. Draft a multi-market summary.
**Output:** `kilo_output/drafts/multi_market_comparison_2026-05-18.md`
**Log:** `kilo_logs/CHANGELOG.md`

---

## T-144 | EG-036: Distressed project brief — Yelahanka
**Status:** DONE
**Brain:** Kilo Code
**Phase:** P2
**Blocked by:** —
**Task Tier:** T0 — Read-only

**What to do:** Run EG-036 from the EVERGREEN TASKS table. Query rera_projects for Yelahanka — identify projects with: possession_date in the past AND project_status != 'completed', OR total_sold_units = 0 with possession_date < today. These are distressed. Draft a brief with project names and developer names.
**Output:** `kilo_output/drafts/distressed_projects_Yelahanka_2026-05-18.md`
**Log:** `kilo_logs/CHANGELOG.md`

---

## T-145 | EG-039: RERA project enrichment gaps audit
**Status:** DONE
**Brain:** Kilo Code
**Phase:** P2
**Blocked by:** —
**Task Tier:** T0 — Read-only

**What to do:** Run EG-039 from the EVERGREEN TASKS table. Given T-129 finding (all 30 rera_detail records have null enriched fields), query rera_projects to count: how many records have null total_units, null site_area, null completion_pct. Report the gap as a %. This is the enrichment baseline before T-138 fix.
**Output:** `kilo_output/audits/rera_enrichment_gaps_2026-05-18.md`
**Log:** `kilo_logs/CHANGELOG.md`

---

## PHASE A — Pipeline Closure Detail Specs (Cline, PA-1 to PA-6)

Phase A canonical order: **T-063 → T-147 → T-069 → T-010 → T-150 → T-151**
T-146 / T-148 / T-149 in INDEX = SKIP (duplicates of T-063 / T-069 / T-010 respectively)

---

## T-147 | PA-2: Fix developer_scout — SPA extraction rewrite
**Status:** DONE
**Brain:** Cline
**Phase:** PA
**Blocked by:** —
**Priority:** HIGH
**Task Tier:** T4 — Scraper/debug
**Plan mode:** NinRouter → Codex
**Act mode:** OpenRouter → free model

**Context:** `developer_scout.py` returns 0 projects for all 8 developers. Root cause (T-039 + T-042): `_clean_html()` strips nav/header tags which contain the matching keywords. When no keyword hit in stripped text, scout falls back to full page text, then `_ai_extract_developer()` takes the first 6k chars — which is hero/banner copy on SPAs, not project listings. T-042 partially fixed with a 5k+5k start+middle sample, but developer_scout still returns 0 in production. Need a deeper fix: explicit DOM-target extraction.

**What to do:**
1. Read `scrapers/developer_scout.py` in full — understand `_ai_extract_developer`, `_clean_html`, `_playwright_fetch`, `_scout_developer`
2. In `_playwright_fetch`: after wait_for_timeout (already 6000ms), add a scroll step to trigger lazy-loaded project cards:
   ```python
   await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
   await page.wait_for_timeout(2000)
   ```
3. In `_ai_extract_developer`: change sampling strategy — instead of start+middle, extract ALL `<a>`, `<h2>`, `<h3>`, `<p>` tags containing any of the north_bengaluru_keywords BEFORE passing to AI. If DOM-targeted extraction yields < 500 chars, fall back to start+middle (5k+5k).
4. For the AI prompt in `_ai_extract_developer`: add explicit instruction — "Look for project names, launch dates, BHK configurations, and price ranges. If page is a homepage with no project list, return empty array."
5. Test standalone: `docker compose exec agents python scrapers/developer_scout.py --developer Brigade --market Yelahanka`

**Files to touch:** READ+WRITE — `scrapers/developer_scout.py`
**Success check:** Brigade or Prestige returns ≥ 1 project in standalone test
**If it fails:** Log exact AI response for the failing developer (add a debug print before AI call). Mark NEEDS-FIX with the AI response snippet.

**Changelog:** `T-147 | scrapers/developer_scout.py | SPA extraction rewrite — scroll + DOM targeting | Cline | YYYY-MM-DD`

---

## T-150 | PA-5: Integration test Yelahanka — verify rera_detail enriched fields > 0
**Status:** READY
**Brain:** Cline
**Phase:** PA
**Blocked by:** T-063
**Priority:** HIGH
**Task Tier:** T2 — Commands

**Context:** As of 2026-05-18, all 30 rera_detail records have null enriched fields (T-129 finding). T-063 adds Stage 2 upsert. T-138 fixed the URL type. This test verifies both fixes are working end-to-end.

**What to do:**
1. Delete today's checkpoints so Stage 1 runs fresh: `docker compose exec agents rm -rf outputs/yelahanka/checkpoints/`
2. Run: `docker compose exec agents python crews/market_intel_crew.py --market Yelahanka`
3. After completion, run this DB query: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT COUNT(*) FROM rera_projects WHERE total_units > 0;"`
4. Also check: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT rera_number, total_units, raw_data->>'completion_pct' FROM rera_projects WHERE total_units > 0 LIMIT 5;"`
5. Verify intel_report was created: `ls outputs/yelahanka/intel_report_*.txt` (should have a new file from today)

**Files to touch:** NONE — command only
**Success check:** `total_units > 0` count is > 0 (any non-zero). Intel report created.
**If rera_detail enrichment = 0:** Check crew.log for "RERA Detail Scout" line — did Stage 1 run detail scout? Did Stage 2 log "N records enriched"? Report both to Claude.

**Changelog:** `T-150 | integration test | PASS/FAIL | [rera_detail_enriched=N, intel_report=yes/no] | Cline | YYYY-MM-DD`

---

## T-151 | PA-6: Verify developer_scout > 0 projects — standalone test
**Status:** READY
**Brain:** Cline
**Phase:** PA
**Blocked by:** T-147
**Priority:** MEDIUM
**Task Tier:** T2 — Commands

**What to do:**
1. Run: `docker compose exec agents python scrapers/developer_scout.py --developer "Brigade,Prestige,Sobha" --market Yelahanka`
2. Wait up to 5 minutes (Playwright is slow)
3. Check output file in `outputs/yelahanka/` for developer_scout results
4. Count total projects found across all 3 developers

**Files to touch:** READ ONLY
**Success check:** ≥ 1 project found for at least 1 developer
**If still 0:** Capture the AI response for one developer (add `--debug` or add a print before AI call). Report verbatim to Claude.

**Changelog:** `T-151 | developer_scout standalone | PASS/FAIL | [Brigade=N Prestige=N Sobha=N] | Cline | YYYY-MM-DD`

---

## T-203 | YA-1: Data source audit — Yelahanka data provenance breakdown
**Status:** READY
**Brain:** Kilo Code
**Phase:** PY
**Blocked by:** —
**Priority:** HIGH

**Context:** T-145 found 97.8% null unit_mix. Before debugging writes, we need to know how much of the DB data is seeded vs. live-scraped. If it's mostly `seed_estimated`, the pipeline is running correctly but on artificial data.

**What to do:**
1. Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT data_source, COUNT(*) FROM rera_projects GROUP BY data_source ORDER BY COUNT(*) DESC;"`
2. Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT data_source, COUNT(*) FROM listings GROUP BY data_source;"`
3. Run: `docker compose exec postgres psql -U re_os_user -d re_os -c "SELECT data_source, COUNT(*) FROM kaveri_registrations GROUP BY data_source;"`
4. Write findings to `kilo_output/audits/data_source_breakdown_yelahanka_YYYY-MM-DD.md`

**Success check:** All 3 queries return results. File written with data_source distribution table.
**Key question to answer:** What % of rera_projects are `rera_scraped` vs `seed_estimated`?

**Kilo Code log:** `T-203 | data_source audit | DONE | rera={seed_estimated:N, rera_scraped:N}, listings={...}, kaveri={...} | Kilo Code | YYYY-MM-DD`

---

## T-204 | YA-2: Confidence map — count [FALLBACK] markers in latest Yelahanka intel report
**Status:** READY
**Brain:** Kilo Code
**Phase:** PY
**Blocked by:** —
**Priority:** HIGH

**What to do:**
1. Run: `ls outputs/yelahanka/intel_report_*.txt` — find the latest file
2. Read the full file
3. Count every occurrence of: `[FALLBACK]`, `[SAMPLE]`, `[ESTIMATED]`, `fallback data`, `sample data`
4. For each of the 6 CEO report sections (Market Overview / Competitive Landscape / Pricing Analysis / Absorption Velocity / Risk Flags / LLS Strategic Actions): note which sections contain fallback markers
5. Write to `kilo_output/audits/yelahanka_confidence_map_YYYY-MM-DD.md`

**Success check:** File written with per-section confidence assessment.
**Key output:** Which CEO sections can Jinu trust today vs. which are still on sample data?

**Kilo Code log:** `T-204 | confidence map | DONE | fallback_count=N, weakest_section=[name] | Kilo Code | YYYY-MM-DD`

---

## T-205 | YB-1: CEO prompt upgrade — Yelahanka LLS decision framing
**Status:** READY
**Brain:** Cline
**Phase:** PY
**Blocked by:** T-150
**Priority:** HIGH
**Task Tier:** T3 — Code edit
**Plan mode:** NinRouter → Codex
**Act mode:** OpenRouter → free

**Context:** Current CEO synthesis produces a generic 6-section brief. For LLS Yelahanka decisions, the brief needs specific entry intelligence. Kilo Code found: ₹5,400–6,000 PSF white space (T-154), 5 distressed developers (T-144), bifurcated market (Grade A absorbed well; Grade C stalled).

**Exact file and location:**
File: `crews/market_intel_crew.py`
Function: `_build_intel_crew()` — the `ceo_synthesis` Task starting at line ~278.
Find the f-string in `description=`. It currently ends with:
```
f"  If data is fallback/sample: say so and note confidence is LOW.\n\n"
f"DATA QUALITY CHECK: If the analyst report says data is FALLBACK SAMPLE, "
f"prefix every number with [ESTIMATED] and add a warning at the top."
```

**What to add:** Insert this new section BEFORE the `DATA QUALITY CHECK` line:
```python
f"SECTION 7 — LLS ENTRY INTELLIGENCE\n"
f"  a) Entry PSF Band: '₹X,XXX–X,XXX psf — [1-line rationale from competitor data]'\n"
f"  b) JD/JV Targets: List any developer where possession_date is past, project_status is On-Going, and absorption > 60%. These are capital-constrained. Format: 'Developer | Project | absorption% | N months overdue'\n"
f"  c) Grade Split: 'Grade A avg absorption: X% | Grade B/C avg: Y%'\n"
f"  d) Go/No-Go: 'Yelahanka: [ENTER / HOLD / EXIT] — [one reason with one number]'\n\n"
```

Also update `expected_output=` to add `| LLS Entry Intelligence` to the section list.

**Files to touch:** `crews/market_intel_crew.py`
**Success check:** Section 7 with all 4 sub-items (a/b/c/d) appears in next Yelahanka intel report.

**Changelog:** `T-205 | CEO Section 7 Yelahanka LLS framing | DONE | crews/market_intel_crew.py | Cline | YYYY-MM-DD`

---

## T-206 | YB-2: Analyst upgrade — distressed_developer_list query
**Status:** READY
**Brain:** Cline
**Phase:** PY
**Blocked by:** T-150
**Priority:** HIGH
**Task Tier:** T3 — Code edit
**Plan mode:** NinRouter → Codex
**Act mode:** OpenRouter → free

**Context:** The analyst currently queries market summary, competitor analysis, and listings. It doesn't expose the distressed developer signal directly. T-144 (Kilo Code) found 5 distressed projects manually via SQL. This task wires that query into the analyst so it surfaces automatically on every run.

**Exact file and location:**
File: `agents/analyst_agent.py`
Class: `MarketSummaryTool`
Method: `_run(self, market_name: str)`
Location: After the `gv_summary` query (line ~151) and before the `result = {...}` dict (line ~168).

**Add this SQL query block** (use `conn.execute(text(...), {"market": f"%{market_name}%"}).fetchall()`):

```python
# JD/JV candidates — overdue possession, not completed, high absorption (capital-constrained)
distressed = conn.execute(
    text("""
    SELECT
        d.name as developer,
        r.project_name,
        r.rera_number,
        r.possession_date,
        r.project_status,
        r.sold_units,
        r.total_units,
        r.absorption_pct,
        (CURRENT_DATE - r.possession_date) AS days_overdue
    FROM rera_projects r
    JOIN micro_markets m ON r.micro_market_id = m.id
    LEFT JOIN developers d ON r.developer_id = d.id
    WHERE m.name ILIKE :market
      AND r.possession_date < CURRENT_DATE
      AND r.project_status NOT ILIKE '%%complet%%'
      AND r.absorption_pct > 60
    ORDER BY days_overdue DESC
    LIMIT 10
    """),
    {"market": f"%{market_name}%"},
).fetchall()
```

**Then add to the `result` dict:**
```python
"distressed_developers": [dict(r._mapping) for r in distressed],
```

Note: Use `d.name` and `m.name` (not `d.developer_name` or `m.market_name`) — matches existing analyst schema pattern.

**Files to touch:** `agents/analyst_agent.py`
**Success check:** `distressed_developers` key appears in analyst tool output JSON on next run.

**Changelog:** `T-206 | analyst distressed_developer query | DONE | agents/analyst_agent.py | Cline | YYYY-MM-DD`

---

## T-207 | YB-3: Debug run_rera_detail_scout DB write — trace 97.8% null unit_mix
**Status:** READY
**Brain:** Cline
**Phase:** PY
**Blocked by:** T-150
**Priority:** CRITICAL
**Task Tier:** T4 — Debug
**Plan mode:** NinRouter → Codex
**Act mode:** NinRouter → Codex

**Context:** T-145 found 97.8% null unit_mix in rera_projects despite T-063 (Stage 2 upsert wiring) and T-138 (detail URL fix). Two possible failure points: (1) run_rera_detail_scout() is being called but _upsert_rera_detail() is failing silently, or (2) the rera_detail_scout checkpoint contains data but `enriched_fields` are all null.

**What to do:**
1. Read the latest rera_detail_scout checkpoint: `docker compose exec agents cat outputs/yelahanka/checkpoints/rera_detail_scout_YYYY-MM-DD.json | python -m json.tool | head -100`
2. Check if checkpoint records have non-null `total_units`, `unit_mix`, etc. — if all null in checkpoint, the scraper is returning empty enriched fields (AI extraction failing)
3. Add explicit logging to `utils/db_organizer.py` `_upsert_rera_detail()` — log the values being written to `total_units` and `unit_mix` before the SQL
4. Run a fresh pipeline: `docker compose exec agents python crews/market_intel_crew.py --market Yelahanka`
5. Check crew.log for the new log line from step 3
6. Report: (a) checkpoint has data? (b) DB write executing? (c) What value is being written?

**Root cause candidates:**
- A: Checkpoint is empty/null enriched fields → AI extraction failing on RERA detail pages → fix is in `scrapers/rera_detail_scout.py` AI prompt
- B: Checkpoint has data but _upsert_rera_detail() SQL is wrong → fix SQL UPDATE SET clause

**Files to touch:** `utils/db_organizer.py` (add logging only — no logic change yet)
**Success check:** Identify whether failure is in scraper (candidate A) or DB write (candidate B). Report to Claude.

**Changelog:** `T-207 | rera_detail DB write debug | DONE | root_cause=[A/B], details=[...] | Cline | YYYY-MM-DD`

---

## T-208 | YC-1: Fix Brigade/Prestige developer URLs for Yelahanka
**Status:** READY
**Brain:** Cline
**Phase:** PY
**Blocked by:** T-151
**Priority:** MEDIUM
**Task Tier:** T4 — Debug
**Plan mode:** NinRouter → Codex
**Act mode:** NinRouter → Codex

**Context:** T-147 confirmed Godrej returns 6 projects via Cerebras fallback. Brigade and Prestige URLs are dead — `brigade.in/all-properties?city=bangalore` and `prestige.co.in/residential-projects/bangalore` return 0 or timeout.

**What to do:**
1. Read `scrapers/developer_scout.py` — find the `DEVELOPER_SITES` dict
2. For Brigade: try `https://www.brigadegroup.com/residential` or `https://www.brigadegroup.com/residential/ongoing` — check if these return project listings
3. For Prestige: try `https://www.prestigeconstructions.com/projects/residential/ongoing` or `https://www.prestigeconstructions.com/upcoming-projects`
4. Update `DEVELOPER_SITES["Brigade"]["url"]` and `DEVELOPER_SITES["Prestige"]["url"]` with working URLs
5. Test: `docker compose exec agents python scrapers/developer_scout.py --developer "Brigade,Prestige" --market Yelahanka`

**Files to touch:** `scrapers/developer_scout.py`
**Success check:** At least 1 Brigade project or 1 Prestige project found for Yelahanka
**If still 0 after URL fix:** Check if their sites require JS rendering (try `use_playwright=True`). Report to Claude.

**Changelog:** `T-208 | brigade/prestige URL fix | DONE | Brigade=N Prestige=N projects | Cline | YYYY-MM-DD`

---

## T-209 | YD-1: Yelahanka decision pack — merge T-143/T-144/T-154 drafts
**Status:** READY
**Brain:** Kilo Code
**Phase:** PY
**Blocked by:** —
**Priority:** MEDIUM

**Context:** Three Kilo Code drafts exist with Yelahanka intelligence: T-143 (multi-market comparison — extract Yelahanka sections), T-144 (distressed project brief), T-154 (wiki page). This task merges them into a single decision-ready brief for Jinu/LLS.

**What to do:**
1. Read `kilo_output/drafts/multi_market_comparison_2026-05-18.md` — extract Yelahanka sections only
2. Read `kilo_output/drafts/distressed_projects_Yelahanka_2026-05-18.md`
3. Read `kilo_output/drafts/wiki_Yelahanka_2026-05-18.md`
4. Synthesize into `kilo_output/drafts/yelahanka_decision_pack_YYYY-MM-DD.md` with this structure:
   - **Section 1 — Market Snapshot:** Key metrics (PSF range, absorption rate, unit count, active developers)
   - **Section 2 — LLS Entry Window:** Recommended PSF band, white space opportunity, competitor positioning
   - **Section 3 — JD/JV Targets:** Distressed developers (high absorption, overdue) with contact/outreach rationale
   - **Section 4 — Risks:** Oversupply signals, developer competition, price ceiling
   - **Section 5 — Decision:** Go/No-Go with one-sentence rationale

**Success check:** File written, all 5 sections present, no unsupported claims.

**Kilo Code log:** `T-209 | Yelahanka decision pack | DONE | sections=5, file=kilo_output/drafts/yelahanka_decision_pack_YYYY-MM-DD.md | Kilo Code | YYYY-MM-DD`

---

## Runtime Status Overrides (2026-05-17)

**T-046 SUPERSEDED by T-062.** Use T-062 spec (it adds checkpoint delete step and correct DB counts).

**T-062 reset reason (Claude 2026-05-17):**
- Listings=0 root cause found and fixed: Stage 1 cache skip was skipping portal/dev/news scouts when RERA checkpoint existed. Fixed in market_intel_crew.py to require ALL 4 checkpoints before skipping.
- T-063 added: rera_detail_scout enriched data now gets upserted in Stage 2 (was being discarded).
- duration_seconds now written to agent_runs via _log_run() in db_organizer.py.
