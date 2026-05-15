# AGENTS.md — RE_OS Multi-Brain Coordination Protocol
**Last updated: 2026-05-15**

---

## ⚠️ Tool Stack Update — 2026-05-15
**Roo Code shut down on 2026-05-15.** Replaced by **Kilo Code** (VS Code extension, free tier).
**New tools added: Gemini CLI + Aider (CLI).**
Full usage guide → `TOOL_GUIDE.md`

---

## The Development Brains

| Brain | Lives in | Role | Strengths | Free Tier Limit |
|-------|----------|------|-----------|-----------------|
| **Claude Code** | VS Code terminal | Principal — architect, reviewer, aligner | Architecture, multi-file analysis, vision alignment | Per session (generous) |
| **Cline** | VS Code extension | Implementer A — atomic execution | Single-file edits, terminal runs, config changes | API key dependent |
| **Kilo Code** | VS Code extension | Implementer B — simple targeted edits | READ tasks, single-file audits, run commands, verify output | Free: low context, light tasks only |
| **Gemini CLI** | Terminal (`gemini`) | Large-context reader + summarizer | Read 10+ files at once, codebase Q&A, log analysis | Free: 1,500 req/day, 1M token context |
| **Aider** | Terminal (`aider`) | Autonomous multi-file editor | Systematic refactors, git-committed changes, test-fix loops | Free via Gemini key |

**RE_OS Crew** is not a development brain. It is the product being built. Do not confuse it with the three development brains above.

---

## How Each Brain Finds Its Work

### Cline — finding the next task (PRIMARY IMPLEMENTER)
1. Open `TASK_QUEUE.md`
2. Scan the **TASK INDEX** table at the top
3. Find the first row where `Status = READY` and `Brain = Cline`
4. Note the Task ID (e.g., T-007)
5. Jump to that task's **DETAIL SPEC** section in TASK_QUEUE.md
6. Read every line of the spec before doing anything
7. Execute exactly as written — no improvisation
8. Check success criteria — did it pass?
9. Write one log line to `CHANGELOG.md` using the exact format in the spec
10. Update the task row in TASK_QUEUE.md: change `Status` from `READY` → `DONE` (or `NEEDS-FIX` if failed)
11. Return to step 2 and find the next READY task

**One task at a time. Do not start T-009 until T-008 is marked DONE or NEEDS-FIX.**

### Kilo Code — finding the next task (SECONDARY IMPLEMENTER — FREE TIER)
Same loop as Cline. ONLY pick tasks where:
- Brain = `Kilo Code` in TASK_QUEUE.md, OR
- Brain = `Cline` and the task is READ-ONLY (audit, verify, diagnose — no writes required)

**Hard limits for Kilo Code free tier:**
- Do NOT take tasks requiring edits to more than 2 files
- Do NOT take tasks where the spec says "read file in full" if the file is >300 lines
- Do NOT take Claude-assigned tasks — those require full architecture context
- If context feels truncated mid-task: STOP. Mark NEEDS-FIX, note "Kilo context limit hit". Move on.

### Gemini CLI — NOT a task-picker (READ + ANALYZE only)
Gemini CLI does not pick tasks from TASK_QUEUE.md. Jinu triggers it directly.
Used for: "read all 5 scraper files and tell me what's broken", "summarize crew.log", "what does scout_memory.py do?"
See `TOOL_GUIDE.md` for exact commands.

### Aider — NOT a task-picker (TARGETED REFACTORS)
Aider does not pick tasks from TASK_QUEUE.md. Jinu triggers it directly.
Used for: systematic bug fixes across files, rename-and-replace refactors, test fix loops.
Always runs in `/architect` mode. Always commits to git after changes.
See `TOOL_GUIDE.md` for exact commands.

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
- Summary to Jinu: what was done well, what was fixed, what's next

---

## Task Format Reference

All tasks in `TASK_QUEUE.md` follow this structure. Brains must read the full spec before executing.

```
## T-XXX | Task Title
Status: READY | IN-PROGRESS | DONE | NEEDS-FIX | NEEDS-CLARIFICATION | BLOCKED
Brain: Cline | Roo Code | Claude
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
| `CHANGELOG.md` | File-level change log (one line per file changed) | All brains after every edit |
| `.cline_logs/CHANGELOG.md` | Cline session log | Cline updates after every session |
| `logs/crew.log` | Live pipeline log | Auto-generated by pipeline |
| `logs/runs_summary.md` | Pipeline run history | Auto-generated by pipeline |

---

*Protocol maintained by Claude. If this file is stale or contradicts VISION.md, VISION.md wins.*
