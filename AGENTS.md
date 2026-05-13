# AGENTS.md — RE_OS Coordination Protocol
**Last updated: 2026-05-13**

Three AI brains work on this project. Any brain can plan, design, or execute. The only rule is: **read before you act, log after you act.** That's it. This keeps all brains in sync without restricting who can do what.

---

## The Three Brains

| Brain | What it runs in | Strengths |
|-------|----------------|-----------|
| **Claude Code** | VS Code terminal / Claude.ai | Research, architecture thinking, multi-file analysis, complex diagnosis |
| **Cline** | VS Code extension | Fast file editing, docker commands, sequential execution, testing |
| **RE_OS Crew** | Docker container | Runtime pipeline — the intelligence product itself, not a developer |

RE_OS Crew does not contribute to development. It is the thing being built. All development is Claude Code + Cline.

---

## Pre-Session Read Order (mandatory, ~2 min)

Before any brain touches anything, read in this order:

1. **`CLAUDE.md`** — full project state, architecture, known bugs, run commands
2. **`DEVLOG.md`** — what phases have been completed and what the system can do right now
3. **`CHANGELOG.md`** — recent file-level changes (who changed what, when, why)
4. **`.cline_logs/CHANGELOG.md`** — Cline's session log (if Cline ran recently)
5. **Backlog table at the bottom of this file** — what's in progress

If you skip this read and act on stale context, you will overwrite someone else's work. The 2-minute read prevents that.

---

## Before Touching a File

If a file was changed in the last 24 hours (visible in `CHANGELOG.md`), **read the entire file** before editing it. Don't rely on memory of what was there before — read the current state.

If a task in the Backlog below is marked 🔄 (in progress), don't start it. Pick a different task, or check in with Jinu first.

---

## After Any Meaningful Change

Two things, always:

**1. Add a phase entry to `DEVLOG.md`** using the template at the bottom of that file.
- What the situation was
- What you changed (file + what changed + why)
- What the system can do now that it couldn't before
- What's still broken

**2. Update `CHANGELOG.md`** — one-line entry per file changed: `path | what changed | brain | timestamp`

If you ran the pipeline and got a result, add the run ID to the phase entry.

---

## Conflict Rule

If you need to edit a file that another brain edited in the same session, read the full current file first, then make your changes on top. Never overwrite based on a version you saw earlier in the session.

If two changes are in conflict (incompatible approaches), don't resolve it silently. Log both in DEVLOG.md and flag for Jinu to decide.

---

## Active Work Backlog

Mark tasks 🔄 when you start them. Mark ✅ when done. Add new tasks as they emerge.

| P | Task | Status | Brain Working On It | Notes |
|---|------|--------|---------------------|-------|
| P0 | RERA portal selector calibration — Playwright returns 0 (portal structure changed) | Open | — | Needs manual portal inspection before fixing |
| P0 | DB upsert returning 0 rows — `ON CONFLICT DO UPDATE` not setting `micro_market_id` | Open | — | `db_organizer._upsert_project` fix needed |
| P1 | Kaveri portal selector calibration — always unreachable | Open | — | Check portal URL, form field names |
| P1 | CEO report upgrade — 6-section structured brief (not 4 sentences) | Open | — | See `plans/MASTER_PLAN.md` Phase 1 |
| P1 | Analyst upgrade — 6 signals: velocity, momentum, delivery score, supply pressure, GV gap, launch lag | Open | — | See `plans/MASTER_PLAN.md` |
| P1 | Add `httpx`, `price-parser`, `dateparser` to requirements + rebuild agents | Open | — | requirements.txt → rebuild container |
| P1 | Wire CEO output to file: `outputs/{market}/intel_report_{ts}.txt` | Open | — | Currently prints to terminal only |
| P2 | Fix analyst LLM loop — calls `market_summary_query` 4× per run | Open | — | Prompt tightening in analyst_agent.py |
| P2 | Expand to Devanahalli + Hebbal markets | Open | — | Yelahanka stable, ready to expand |
| P2 | Listings scraper — 99acres + MagicBricks (Playwright) | Open | — | Current version uses sample data |
| P2 | Fix `delay_months` generated column in schema.sql | Open | — | Only fails on DB wipe — not urgent |
| P3 | Developer Intelligence module | Open | — | See `plans/developer_intelligence_plan.md` |
| P3 | News Intelligence module | Open | — | See `plans/news_intelligence_plan.md` |

---

## Key Files Quick Reference

| File | What it is | Update when |
|------|-----------|-------------|
| `CLAUDE.md` | Full project state — architecture, run commands, known bugs | After every significant session |
| `DEVLOG.md` | Phase-by-phase build history | After every meaningful change |
| `CHANGELOG.md` | File-level change log | After every file edit |
| `.cline_logs/CHANGELOG.md` | Cline session log | Cline updates after every session |
| `plans/MASTER_PLAN.md` | Bloomberg Terminal vision, all 8 modules, execution phases | When architecture changes |
| `logs/runs_summary.md` | Pipeline run history | Auto-generated by pipeline |
| `logs/crew.log` | Live pipeline log | Auto-generated by pipeline |

---

*Protocol maintained by whoever last worked on it. If this file is stale, update it.*
