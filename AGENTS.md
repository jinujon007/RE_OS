# AGENTS.md — RE_OS Multi-Brain Coordination Protocol
**Last updated: 2026-05-15**

---

## ⚠️ Tool Stack Update — 2026-05-16
**Roo Code shut down on 2026-05-15.** Replaced by **Kilo Code** (VS Code extension, free tier).
**New tools added: Gemini CLI + Aider (CLI).**
**Plandex removed 2026-05-16** — Plandex Cloud (api.plandex.ai) decommissioned; v2.x has no Windows binary. Aider covers T3/T4 multi-file tasks.
Full usage guide → `TOOL_GUIDE.md`

---

## The Development Brains

| Brain | Lives in | Role | Strengths | Cost |
|-------|----------|------|-----------|------|
| **Claude Code** | VS Code terminal | Principal — architect, reviewer, aligner | Architecture, multi-file analysis, vision alignment, writes specs | Per session |
| **Cline** | VS Code extension | Implementer A — single-file atomic tasks | T1/T2 tasks: single-file edits, docker commands, config changes | Switchable per task (see model routing) |
| **Kilo Code** | VS Code extension | Implementer B — background loop | T0 + evergreen: audits, summaries, drafts, kilo_output only | Free tier built-in |
| **Gemini CLI** | Terminal (`gemini`) | Large-context reader + summarizer | Read 10+ files at once, codebase Q&A, log analysis | Free: 1,500 req/day |
| **Aider** | Terminal (`aider`) | Autonomous multi-file editor | T3/T4 tasks + systematic refactors, git-committed changes, test-fix loops | Free via Gemini key |
| **OpenCode** | Terminal (`opencode`) | Free CLI agent for routine tasks | Read, explain, small 1-file edits — replaces Claude Code for non-architecture asks | Free via OpenRouter |

**RE_OS Crew** is not a development brain. It is the product being built. Do not confuse it with the development brains above.

**Cline model switching:** Cline supports multiple API providers — you can swap which key/model it uses before each task. The task spec always tells you which model to set. High-level coding tasks (T3/T4) use OpenAI `o4-mini` (Codex-class via your OpenAI subscription). Simpler tasks use free Groq or Ollama. You never need Sonnet for any task in this queue.

**Brain responsibility boundary:**
- Claude Code → designs, specs, reviews. Never does routine tasks.
- Cline → executes specs. **Only picks Brain=Cline tasks.** Never touches Brain=Kilo Code or Brain=Claude rows.
- Kilo Code → T0 read-only only. **Only picks Brain=Kilo Code tasks.** Never touches Brain=Cline or Brain=Claude rows.
- **No overlap between Cline and Kilo.** When both run simultaneously, they work on entirely separate tasks with no shared rows.

---

## How Each Brain Finds Its Work

### Cline — finding the next task (PRIMARY IMPLEMENTER)

**PARALLEL-SAFE PROTOCOL (Kilo Code may be running at the same time):**

1. Open `TASK_QUEUE.md`
2. Scan the **TASK INDEX** — find the first row where `Status = READY` and `Brain = Cline`
   - **ONLY pick Brain=Cline rows.** Never touch Brain=Kilo Code or Brain=Claude rows.
3. **Immediately mark that row `IN-PROGRESS`** in the INDEX — save the file. This claims the task.
4. Jump to that task's **DETAIL SPEC** section
5. Read every line of the spec — **find the `Plan mode:` and `Act mode:` lines**
6. **Output to Jinu:** Task name, Tier, Plan mode model, Act mode model. Wait for Jinu to switch models and confirm.
7. Execute exactly as written — no improvisation
8. Check success criteria
9. Write one log line to `CHANGELOG.md`
10. Change `IN-PROGRESS` → `DONE` (or `NEEDS-FIX`) in TASK_QUEUE.md
11. Report Plan + Act models for the NEXT ready Cline task, then return to step 2

**One task at a time. Never start the next task until the current one is marked DONE or NEEDS-FIX.**

**Model routing (quick ref):**
- T0 → Plan: Ollama, Act: Ollama
- T1/T2 → Plan: OpenRouter free, Act: OpenRouter free
- T3 → Plan: NinRouter Codex, Act: OpenRouter free
- T4 → Plan: NinRouter Codex, Act: NinRouter Codex
- Full guide + copy-paste prompts → `TOOL_GUIDE.md` § 9

### Kilo Code — finding the next task (SECONDARY IMPLEMENTER — FREE TIER)

**PARALLEL-SAFE PROTOCOL (Cline may be running at the same time):**

**Three-tier loop — work top to bottom, return to top after each task:**

```
TIER 1 — Urgent (explicitly assigned by Claude)
  → Scan TASK_QUEUE.md INDEX for first READY row where Brain = Kilo Code
  → If found: claim it (mark IN-PROGRESS), execute, log, mark DONE, return to TIER 1

TIER 2 — Ready prep (pre-audits for upcoming blocked tasks)
  → Scan TASK_QUEUE.md INDEX for READY Brain=Kilo Code rows not yet taken
  → Same claim/execute/log cycle as Tier 1

TIER 3 — Evergreen (always available, never blocked, never empty)
  → See TASK_QUEUE.md § EVERGREEN TASKS
  → Pick next evergreen task in rotation
  → Execute, write output to kilo_output/, log to kilo_logs/CHANGELOG.md
  → Return to TIER 1 (check if new Tier 1/2 tasks appeared)
```

**Only pick Brain=Kilo Code rows. Never touch Brain=Cline or Brain=Claude rows.**
This is a hard rule for parallel-safe operation. No exceptions.

**Model:** Kilo Code free tier uses its built-in default model. No model selection needed.

---

**Write zones — where Kilo Code is allowed to write:**

| Zone | What it's for | Allowed? |
|------|--------------|---------|
| `kilo_output/summaries/` | Log digests, DB snapshots, inventories | ✅ YES |
| `kilo_output/audits/` | Mismatch reports, flagged issues | ✅ YES |
| `kilo_output/drafts/` | New file drafts awaiting Claude review | ✅ YES |
| `kilo_output/queue/` | Task spec drafts for Claude to finalize | ✅ YES |
| `kilo_logs/CHANGELOG.md` | Kilo Code session log | ✅ YES |
| Any existing production file | — | ❌ NEVER |
| Root `CHANGELOG.md` | — | ❌ NEVER |
| `TASK_QUEUE.md` | — | ❌ NEVER (read-only for Kilo Code) |
| `DEVLOG.md` | — | ❌ NEVER |
| `AGENTS.md` | — | ❌ NEVER |
| `NEXT_TASKS.md` | — | ❌ NEVER |

**Kilo Code creates new files in kilo_output/. It never edits existing production files.**
This is the core safety boundary. CHANGELOG.md has been overwritten twice — this rule is ABSOLUTE.

**⚠️ INCIDENT LOG:**
- Phase 16 (2026-05-15): Kilo Code (T-038) replaced 534-line CHANGELOG.md with 36-line task spec dump.
- Phase 21 (2026-05-19): Kilo Code replaced 549-line CHANGELOG.md with T-051 TypeScript content from an unrelated project.
- Both incidents recovered from git. Root cause: Kilo Code treating CHANGELOG.md as a task output file.
- Prevention: CHANGELOG.md is NEVER a Kilo Code output target. Log to `kilo_logs/CHANGELOG.md` ONLY.

---

**What Kilo Code CAN do (expanded from T0-only):**
- Read any file, any size — no line limit
- Run read-only terminal commands: `docker compose ps`, `SELECT` queries, `ls outputs/`, `cat logs/`
- Create new files inside `kilo_output/` or `kilo_logs/`
- Audit, analyse, draft, summarize, propose specs

**What Kilo Code CANNOT do:**
- Edit any existing file outside `kilo_output/` or `kilo_logs/`
- Run docker exec write operations (INSERT, UPDATE, DROP, restart)
- Git commits or git operations
- Take tasks marked Brain=Cline or Brain=Claude

---

**Logging — ONE file only:**

**`kilo_logs/CHANGELOG.md`** — Kilo Code's session log.
```
## T-XXX | Task Title | PASS/FAIL/DONE | YYYY-MM-DD HH:MM

**Findings:**
- key finding 1
- key finding 2
**Output written to:** kilo_output/[path]
**Status change:** T-XXX → DONE
```

For evergreen tasks:
```
## EG-XXX | Task Title | DONE | YYYY-MM-DD HH:MM

**Output written to:** kilo_output/[path/filename]
**Summary:** one line of what was found
```

⚠️ **CRITICAL: Never paste task specs into any log file.** Specs live in TASK_QUEUE.md — do not copy them.

---

**On context limit / file too long:**
1. STOP immediately
2. Write to `kilo_logs/CHANGELOG.md`: escalation note with reason and file name
3. In TASK_QUEUE.md: change Brain `Kilo Code` → `Cline`, Status `IN-PROGRESS` → `READY`
4. Move to next Kilo Code task (Tier 1 → Tier 2 → Tier 3)

### OpenCode — NOT a task-picker (ROUTINE READS + SMALL EDITS)
OpenCode does not pick tasks from TASK_QUEUE.md. Jinu triggers it directly for routine questions.
Used for: "what does X do?", "read this log and explain", "add this import line".
It replaces Claude Code sessions for anything that does not require architecture thinking.
See `TOOL_GUIDE.md § 7` for exact commands.

### Gemini CLI — NOT a task-picker (READ + ANALYZE only)
Gemini CLI does not pick tasks from TASK_QUEUE.md. Jinu triggers it directly.
Used for: "read all 5 scraper files and tell me what's broken", "summarize crew.log", "what does scout_memory.py do?"
See `TOOL_GUIDE.md` for exact commands.

### Aider — NOT a task-picker (MULTI-FILE EDITS + REFACTORS)
Aider does not pick tasks from TASK_QUEUE.md. Jinu triggers it directly.
Used for: T3/T4 tasks touching 2+ files, systematic bug fixes, rename-and-replace refactors, test fix loops.
Always runs in `/architect` mode. Always commits to git after changes.
See `TOOL_GUIDE.md § 5` for exact commands.

### Claude Code — review cycle
Claude does NOT pick tasks from TASK_QUEUE.md during normal operation.
Claude is triggered by Jinu manually with: *"review the project development"* or *"review and align."*

When triggered, Claude:
1. Reads `CHANGELOG.md` — all entries since last review
2. Reads `DEVLOG.md` — last 2 phases only
3. Reads every file that was changed since last review (use CHANGELOG.md as the list)
4. Checks: does the work align with `VISION.md`? Is anything broken? Is quality acceptable?
5. Makes fixes inline — does not create tickets for things it can fix in the session
6. Adds new tasks to `TASK_QUEUE.md` for anything that Cline should handle next
7. Marks any NEEDS-FIX tasks as READY again with a fix spec if the fix is Cline-appropriate
8. Updates `CLAUDE.md` if architecture has meaningfully changed
9. Ends with a brief summary to Jinu: what passed, what was fixed, what's queued next

---

## Read Order — Mandatory Before Touching Anything

Every brain, every session, before touching a single file:

1. **`CLAUDE.md`** — full project state, architecture, known bugs, run commands
2. **`DEVLOG.md`** — last 2 phases only (jump to bottom)
3. **`CHANGELOG.md`** — recent file-level changes (who changed what, when)
4. **`TASK_QUEUE.md`** — find your next task

Skip this and you will overwrite someone else's work or implement something that was already done.

---

## Rules for All Brains

**Before touching a file:** If CHANGELOG.md shows this file was changed in the last 24 hours, read the full current file before editing. Never edit from memory of an older version.

**After every meaningful change:** Two logs, always:
1. `CHANGELOG.md` — one line: `path | what changed | brain | timestamp`
2. `DEVLOG.md` — phase entry (what situation, what changed, what works now, what's still broken)

**On conflict:** If you need to edit a file another brain edited in the same session, read the current file first. If two changes are incompatible, do NOT silently resolve — log both in DEVLOG.md and flag for Jinu.

**On failure:** If a task fails and you cannot fix it in under 5 minutes, mark it NEEDS-FIX with a note, move to the next task. Do not spiral trying to fix a broken environment.

**On ambiguity:** If a task spec is unclear, mark it NEEDS-CLARIFICATION. Do not guess.

---

## Review Cycle Trigger

Jinu triggers Claude review after approximately every 5–7 completed tasks, or after any phase completes.

Trigger phrase: *"review the project development"* or *"review and align"*

Claude's review output:
- Inline fixes to any drifted code
- Updated `TASK_QUEUE.md` (new tasks, reprioritized queue)
- Updated `CLAUDE.md` if architecture changed
- Summary to Jinu: what passed, what was fixed, what's queued next

---

## Task Format Reference

All tasks in `TASK_QUEUE.md` follow this structure. Brains must read the full spec before executing.

```
## T-XXX | Task Title
Status: READY | IN-PROGRESS | DONE | NEEDS-FIX | NEEDS-CLARIFICATION | BLOCKED
Brain: Cline | Kilo Code | Claude | Codex
Phase: P1 / P2 / etc.
Blocked by: T-XXX or —
Priority: HIGH | MEDIUM | LOW

What to do:
[Exact step-by-step. No decision-making required. Everything is specified.]

Files to touch:
[explicit list — READ ONLY or READ+WRITE per file]

Command (if applicable):
[exact command to run in docker or local terminal]

Success check:
[Binary. What exact output/state proves this is DONE]

If it fails:
[What to do — usually: log the error verbatim, mark NEEDS-FIX, move on]

Changelog entry format:
T-XXX | [task title] | PASS/FAIL | [one-line result] | [Brain] | YYYY-MM-DD HH:MM
```

---

## Key Files Quick Reference

| File | What it is | Updated by |
|------|-----------|------------|
| `CLAUDE.md` | Full project state, architecture, known bugs, run commands | Claude after major sessions |
| `VISION.md` | 14-phase office vision, org chart, all department plans | Claude after vision sessions |
| `TASK_QUEUE.md` | Atomic task list — the daily work queue | Claude (adds tasks), Cline/Kilo (marks done) |
| `AGENTS.md` | Tool protocol, roles, how-to — you are here | Claude |
| `TOOL_GUIDE.md` | How to use Kilo Code, Gemini CLI, Aider, Cline effectively | Claude |
| `DEVLOG.md` | Phase-by-phase build history | All brains after meaningful changes |
| `CHANGELOG.md` | File-level change log (one line per file changed) | Claude + Cline only — **Kilo Code must NOT touch this file** |
| `.cline_logs/CHANGELOG.md` | Cline session log | Cline updates after every session |
| `kilo_logs/CHANGELOG.md` | Kilo Code ONLY log — full findings per T0 task. Claude harvests entries into root CHANGELOG.md during review. | Kilo Code updates after every task |
| `logs/crew.log` | Live pipeline log | Auto-generated by pipeline |
| `logs/runs_summary.md` | Pipeline run history | Auto-generated by pipeline |

---

*Protocol maintained by Claude. If this file is stale or contradicts VISION.md, VISION.md wins.*
