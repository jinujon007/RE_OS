# TOOL_GUIDE.md — RE_OS Development Tool Playbook
**Last updated: 2026-05-16 | Owner: Jinu Joshi | Maintained by: Claude Code**

This is the operating manual for every tool in the RE_OS build stack.
Read this before using any tool. It tells you what each tool is for, what it cannot do, and the exact commands to run.

---

## The Tool Stack at a Glance

| Tool | Where | Role in RE_OS | When to reach for it |
|------|-------|---------------|----------------------|
| **Claude Code** | VS Code terminal | CEO + Architect | Architecture, review, task planning, complex multi-file analysis |
| **Cline** | VS Code extension | Primary implementer | Atomic task execution from TASK_QUEUE.md |
| **Kilo Code** | VS Code extension | Secondary implementer (free) | Simple audits, read-only tasks, single-file edits |
| **Gemini CLI** | Terminal | Large-context reader | Read many files at once, summarize logs, codebase Q&A |
| **Aider** | Terminal | Autonomous editor | Multi-file refactors, T3/T4 tasks, git-committed fixes |
| **OpenCode** | Terminal | Free CLI agent | Routine reads, explain, small edits — replaces Claude Code for cheap tasks |

---

## 1. Claude Code — The Architect

**Role:** Principal brain. Sets direction, reviews work, writes the hard code, maintains all protocol files.
**Never:** Executes routine tasks from TASK_QUEUE.md unprompted. Waits to be triggered.

### When Jinu triggers Claude Code

| Trigger phrase | What Claude does |
|----------------|-----------------|
| "review the project development" | Reads CHANGELOG + DEVLOG + changed files → fixes drift → adds tasks to queue |
| "review and align" | Same as above |
| "next task" | Not Claude's job — tell Cline or Kilo Code instead |
| "what should we build next?" | Claude reads VISION.md + current state → recommends next phase |

### Claude Code task types (what belongs here)
- Writing new agent logic (new LLM tools, new crew stages)
- Architecture decisions
- Reviewing completed Cline/Kilo work for correctness
- Writing complex SQL views or migration logic
- Any task in TASK_QUEUE.md where Brain = Claude

### What Claude Code does NOT do
- Run docker commands on your behalf (those go to Cline)
- Make repetitive single-file edits (those go to Cline or Kilo Code)
- Browse the web (use `/browse` skill)

---

## 2. Cline — Primary Implementer

**Role:** Workhorse. Reads TASK_QUEUE.md, picks the next READY task marked `Brain: Cline`, executes, logs, marks done.
**Lives in:** VS Code extension panel.

### How to use Cline

**Starting a session:**
```
Tell Cline: "Go to your next task"
```
Cline will: read AGENTS.md → read TASK_QUEUE.md → find first READY Cline task → execute spec exactly → log → mark DONE → loop.

**After 5–7 tasks:** Tell Claude Code "review the project development" before continuing.

### Cline's sweet spot
- Running docker commands: `docker compose exec agents python ...`
- Single-file edits with exact spec (T-007, T-008, T-009, T-010 etc.)
- Reading files and answering specific questions
- Container builds and smoke tests

### What to never ask Cline to do
- Make architecture decisions ("how should we structure this?")
- Edit files without a detailed spec — it will hallucinate
- Work on Claude-assigned tasks (T-016, T-017, T-019 etc.)
- Fix bugs that require understanding the full codebase

### Cline's TASK_QUEUE.md loop (paste this into Cline if it forgets)
```
Read AGENTS.md. Then TASK_QUEUE.md. Find the first READY task where Brain = Cline.
Read the full DETAIL SPEC for that task. Execute exactly as written. No improvisation.
After done: write one changelog line to CHANGELOG.md in the format specified.
Update TASK_QUEUE.md: change Status from READY to DONE (or NEEDS-FIX if failed).
Then find the next READY Cline task and repeat.
```

---

## 3. Kilo Code — Secondary Implementer (Free Tier)

**Role:** Backup implementer when Cline is busy or for simple read-and-report tasks.
**Lives in:** VS Code extension panel (replaces Roo Code).
**Free tier constraint:** Smaller context window, lighter model. Use accordingly.

### Kilo Code's operating boundaries (free tier)

**CAN DO:**
- Read a single file and answer specific questions (T-005, T-006, T-035, T-036 type tasks)
- Run a single docker command and report the output
- Add 2–5 lines to a file when the exact lines are specified
- Verify that a changelog entry was written correctly

**CANNOT DO (will produce garbage on free tier):**
- Read files longer than ~300 lines reliably (context overflow)
- Edit more than 1–2 files per task
- Understand multi-file architecture
- Take Claude-assigned tasks (T-016, T-017 etc.)
- Run Playwright/browser tests reliably

### How to trigger Kilo Code

**Starting a session:**
```
Tell Kilo Code: "Go to your next task"
```

Paste this as the system prompt / opening message:
```
You are Kilo Code, implementer B for the RE_OS project.
Read AGENTS.md first. Then TASK_QUEUE.md.
Find the first READY task where:
  - Brain = Kilo Code, OR
  - Brain = Cline AND the task is READ-ONLY (no file writes)
Read the full DETAIL SPEC. Execute exactly. No improvisation.
IMPORTANT: If you feel like you are running out of context or the file is too long,
STOP. Write to CHANGELOG.md: "T-XXX | KILO CONTEXT LIMIT — task requires Cline | Kilo Code | DATE"
Mark the task NEEDS-FIX in TASK_QUEUE.md. Do not guess.
```

### Good tasks for Kilo Code right now
From the current TASK_QUEUE.md, Kilo Code can handle:
- **T-005** — Audit scout_memory.py (read-only, ~150 lines file)
- **T-006** — Schema audit (read-only, SQL file)
- **T-007** — Add 3 lines to requirements.txt (tiny edit, exact spec)
- **T-035** — Verify delay_months column (read-only, SQL file)
- **T-036** — Diagnose Kaveri URL (read-only + one curl command)

### Tasks Kilo Code must NOT touch
T-001 through T-004 (docker Playwright runs — too heavy), T-008 (crew.py too large), T-009 (db_organizer.py logic), T-010 (docker-compose + sentinel analysis), anything marked Brain = Claude.

---

## 4. Gemini CLI — Large-Context Reader

**Role:** Read and summarize large amounts of code or log files that would blow out Claude Code's context. Ask it questions about the codebase.
**Lives in:** Terminal (not VS Code extension).
**Free tier:** 1,500 requests/day, 1M token context window — enough to read the entire RE_OS codebase in one shot.

### Setup
```powershell
# Verify installed
gemini --version

# Authenticate (first time only)
gemini auth login
# Follow the browser OAuth prompt
```

### How to use Gemini CLI in RE_OS

**Use case 1: Read multiple files + ask a question**
```powershell
# "What does each scout file do and what are their dependencies?"
gemini -p "You are analyzing the RE_OS real estate intelligence project. $(Get-Content scrapers/news_scout.py, scrapers/portal_scout.py, scrapers/developer_scout.py, scrapers/rera_detail_scout.py -Raw) --- Question: What does each file do? What external packages does each one import? Are there any obvious bugs?"
```

**Use case 2: Summarize a large log**
```powershell
Get-Content logs/crew.log | gemini -p "Summarize this pipeline log. List: any errors or tracebacks, which stages completed, which stages failed, and the final output produced."
```

**Use case 3: Codebase Q&A**
```powershell
# Ask about the whole project
Get-Content CLAUDE.md, agents/scraper_agent.py, crews/market_intel_crew.py | gemini -p "Based on these files, explain how Stage 1 of the pipeline works and where data flows after scraping."
```

**Use case 4: Pre-review before Claude code review**
```powershell
# Quick sanity check on a changed file
Get-Content agents/scraper_agent.py | gemini -p "Review this Python file for: import errors, undefined variables, functions that are defined but never called, and any obvious logic bugs. List them with line numbers."
```

### Gemini CLI limits and gotchas
- **Context is huge but not unlimited** — avoid piping binary files or entire docker images
- **No memory between sessions** — each command is stateless
- **Not for editing** — Gemini CLI only reads and responds. Use Aider or Cline for edits.
- **Rate limit:** If you get 429, wait 1 minute. 1,500 req/day resets midnight Pacific.
- **Does not know your local filesystem** — you must pipe file contents in explicitly

### Gemini CLI cheat sheet
```powershell
# Basic query
gemini -p "your question here"

# Pipe file
Get-Content file.py | gemini -p "explain this"

# Multiple files
Get-Content file1.py, file2.py | gemini -p "compare these two files"

# Interactive chat (press Ctrl+C to exit)
gemini
```

---

## 5. Aider — Autonomous Multi-File Editor

**Role:** Make targeted, multi-file code changes automatically. Unlike Cline (interactive) or Gemini CLI (read-only), Aider edits files AND commits to git.
**Lives in:** Terminal.
**Free via:** Gemini API key (same key as Gemini CLI) — uses Gemini Flash or Gemini Pro.

### Setup
```powershell
# Verify installed
aider --version   # should show 0.86.2 or later
```

Aider uses a **key rotation router** — `scripts/aider_router.py`. It tests all 4 Gemini keys in order (KEY_1 → KEY_4), picks the first with available quota, and launches Aider. Falls back to Groq Scout automatically if all Gemini keys are exhausted.

**4 Gemini key slots live in `.env`:**
```
GEMINI_API_KEY_1=...   ← primary (always try first)
GEMINI_API_KEY_2=...   ← backup 1
GEMINI_API_KEY_3=...   ← backup 2
GEMINI_API_KEY_4=...   ← backup 3
```
To add more keys: open `.env`, paste into the next empty slot. Router picks it up automatically.

### How Aider works

Aider runs in your terminal. You tell it what files to work on and what to do. It reads the files, makes changes, and commits them to git automatically. You can accept or reject each change.

**The three modes:**
- `/architect` — Aider thinks first, then edits (best quality, use this always)
- Default — Aider edits directly (faster, lower quality)
- `--no-auto-commits` — Aider edits but doesn't commit (review before committing)

### How to use Aider in RE_OS

**Starting a session — always use the router:**
```powershell
cd "D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS"
python scripts/aider_router.py
# or shorthand:
.\scripts\aider.ps1
```

The router prints which key it picked and launches Aider. If you see `quota exhausted ✗` for a key, it moves to the next one automatically.

Aider will show a prompt: `>`

**Add files to work on:**
```
> /add agents/scraper_agent.py
> /add scrapers/news_scout.py
```

**Give the instruction:**
```
> Wire news_scout.py as a CrewAI Tool in scraper_agent.py.
  The tool should be called NewsScoutTool.
  Input: market name (string). Output: list of article dicts.
  Follow the existing pattern used by RERAScraperTool in this file.
```

Aider will: read both files, plan the change, make the edit, show you a diff, commit to git.

**Accepting/rejecting:**
- Press `y` or Enter to accept a change
- Press `n` to reject
- Type feedback to redirect

### RE_OS Aider use cases

**Use case 1: Systematic package import fix**
```
> /add requirements.txt scrapers/news_scout.py
> Add httpx>=0.27.0 to requirements.txt. Then update news_scout.py to import httpx instead of requests wherever requests.get is used for HTTP calls.
```

**Use case 2: Fix a specific error across files**
```
> /add utils/db_organizer.py
> In the _upsert_project function, add micro_market_id = EXCLUDED.micro_market_id to the ON CONFLICT DO UPDATE SET clause. Touch nothing else.
```

**Use case 3: Rename a variable across a file**
```
> /add crews/market_intel_crew.py
> The variable `result` at the end of run_pipeline() is ambiguous. Rename it to `ceo_brief` throughout this file only.
```

**Use case 4: Add error handling to one function**
```
> /add scrapers/rera_karnataka.py
> In the scrape() function, wrap the requests.post() call in a try/except. On requests.RequestException, log the error and return an empty list.
```

### Aider limits and gotchas
- **Always run from RE_OS root directory** — git context depends on it
- **Add only the files relevant to the task** — more files = more confusion
- **Review the diff before accepting** — Aider can hallucinate if the instruction is vague
- **Free Gemini model is smaller** — for complex logic changes, break into smaller steps
- **Aider auto-commits** — check `git log` after each session to see what landed
- **Do not use Aider for architecture tasks** — get Claude Code to spec it first, then Aider to execute

### Aider cheat sheet
```
/add <file>          — add a file to the working set
/drop <file>         — remove a file from the working set
/files               — list currently added files
/diff                — show current git diff
/undo                — undo last commit made by Aider
/clear               — clear chat history (start fresh)
/quit                — exit Aider
```

---

## 6. OpenCode — Free Claude Code Alternative

**Role:** Lightweight CLI coding agent for routine tasks. Use instead of opening a Claude Code session when you need to read a file, explain an error, or make a small single-file edit.
**Lives in:** Terminal (PowerShell).
**Cost:** Free.

### Setup — one time only

**Download (Jinu does this manually):**
1. Go to `github.com/opencode-ai/opencode/releases` in browser
2. Download Windows binary (`.exe`)
3. Move to `C:\tools\` → rename to `opencode.exe`
4. Open new PowerShell → `opencode --version`

**If no releases page / binary not available — try Go install:**
```powershell
# Only if Go is already installed on your machine
go install github.com/opencode-ai/opencode@latest
```

**Configure:**
```powershell
opencode config set api-key "paste your OPENROUTER_API_KEY value here"
opencode config set model "google/gemini-flash-1.5"
```

### When to use OpenCode vs Claude Code

| Task | OpenCode | Claude Code |
|------|----------|-------------|
| "What does this file do?" | ✅ free | ❌ wasteful |
| "Read crew.log and explain the error" | ✅ free | ❌ wasteful |
| "Add one import line to this file" | ✅ free | ❌ wasteful |
| "Design the next phase architecture" | ❌ | ✅ |
| "Review this whole change for correctness" | ❌ | ✅ |
| "Write the spec for a new Cline task" | ❌ | ✅ |

### How to use in RE_OS

```powershell
cd "D:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS"
opencode
```

Then type naturally:
```
> Read agents/scraper_agent.py and list every Tool class defined in it
> Read logs/crew.log last 100 lines — what failed and why?
> Add `import httpx` to scrapers/developer_scout.py after the existing imports
```

### OpenCode limits
- Not for architecture decisions — that's Claude Code
- Not for multi-file complex changes — that's Aider
- Quality depends on free model — good for reading, basic editing

---

## 7. The Right Tool for Every Situation

| Situation | Tool to reach for |
|-----------|-------------------|
| I want to understand the whole codebase quickly | **Gemini CLI** — pipe 10 files in, ask questions |
| "What does this file do?" / small read question | **OpenCode** — free, instant, no session cost |
| Next atomic single-file task from the queue | **Cline** — "go to next task" |
| Simple read-only audit task | **Kilo Code** — "go to next task" |
| Multi-file task (T3/T4) — 2+ files, logic change | **Aider** — add files, give instruction, commits automatically |
| Systematic refactor (rename, restructure) | **Aider** — add files, give instruction |
| Fix a bug in 1 file with exact spec | **Aider** — fastest single-file fix |
| Run docker commands and verify output | **Cline** |
| Architecture decision / new agent design | **Claude Code** — trigger review |
| Something is broken and I don't know why | **Gemini CLI** first → **Claude Code** to fix |
| Review completed work before pushing | **Claude Code** — "review and align" |
| Small one-off read or explanation | **OpenCode** — don't burn a Claude session |

---

## 8. The Daily Workflow

A typical RE_OS build session:

```
1. Morning: Jinu opens VS Code + two terminal windows

2. Terminal A — Kilo Code (always running in background):
   Paste Kilo Code start prompt → it runs evergreen loop forever

3. Terminal B — Cline (T1/T2 single-file tasks):
   Paste Cline start prompt → Cline picks next READY task, reports models, waits for confirm

4. Claude Code: "review the project development" (every 5–7 tasks)
   → reads CHANGELOG, fixes drift, updates TASK_QUEUE.md

5. If anything fails: Gemini CLI reads the log → diagnosis
6. Small isolated fix or multi-file change: Aider
7. Architecture question: Claude Code
8. Routine question ("what does X do?"): OpenCode — not Claude Code
9. End of day: check git log, update DEVLOG.md
```

---

## 9. Reading Order Before Any Session

Every brain (including you, Jinu) reads these before touching anything:

1. `CLAUDE.md` — project state, architecture, known bugs
2. `DEVLOG.md` — last 2 phases only (bottom of file)
3. `CHANGELOG.md` — what changed since you last worked here
4. `TASK_QUEUE.md` — find the next task

If you skip this, you will overwrite work or implement something already done.

---

## 10. Cline Model Routing — Plan Mode + Act Mode per Task

### How Cline model switching works

Cline has **two separate mode slots** you set independently:
- **Plan mode** — Cline thinks through the task, reads context, plans the steps. Needs a smart model that reasons well.
- **Act mode** — Cline executes tool calls (reads files, edits code, runs terminal). Needs a model reliable at tool-call JSON formatting.

You switch these **manually** in the Cline settings before each task. The task spec always tells you what to set for both. You switch, confirm, then Cline runs.

### Your available providers

| Provider | What it gives you | Cost |
|----------|------------------|------|
| **Ollama** | Local models on your machine | Free, unlimited, no API needed |
| **OpenRouter** | DeepSeek V3, Llama 3.3 70b, Gemini Flash, etc. | Free tier |
| **NinRouter** | NVIDIA models + Ollama + OpenRouter + **OpenAI Codex** | Codex = OpenAI subscription; rest free |
| **Hugging Face** | HF-hosted open models | Coming soon |

**NinRouter is where Codex lives.** Use it for any task where you need real code understanding — T3 and T4 tasks.

### Model routing table — Plan + Act per task tier

| Tier | Task type | Plan mode | Act mode |
|------|-----------|-----------|----------|
| **T0** | Read file, audit only, no edits | Ollama (any local) | Ollama (same) |
| **T1** | 1–10 line edit, exact spec given | OpenRouter free | OpenRouter free |
| **T2** | Docker exec, run script, verify | OpenRouter free | OpenRouter free |
| **T3** | 10–50 line code edit, logic change | NinRouter → Codex | OpenRouter free |
| **T4** | Scraper fix, HTML, multi-step debug | NinRouter → Codex | NinRouter → Codex |
| **T5** | Architecture, multi-file | → Claude Code | Not Cline's job |

**Why Plan ≠ Act for T3:**
Codex in Plan mode reasons about the *right* fix from the diagnosis notes and existing code pattern. OpenRouter free in Act mode just writes the file — it doesn't need to reason, just execute. This saves Codex tokens on the mechanical part.

**Why both = Codex for T4:**
Scraper debugging requires understanding browser behavior, HTML selectors, anti-scraping patterns. The act of reading the HTML and deciding the fix is also reasoning-heavy — cheap Act model will miss it.

### Fallback when primary fails or rate-limits

```
T0:   Ollama unavailable → OpenRouter free
T1/T2: OpenRouter rate-limited → Ollama local
T3:   Codex quota hit → Plan = OpenRouter deepseek-v3, Act = OpenRouter free
T4:   Codex quota hit → Plan = OpenRouter deepseek-v3, Act = OpenRouter deepseek-v3
```

### Why Cline keeps suggesting Sonnet

Three causes, three fixes:

| Cause | Fix |
|-------|-----|
| Act model fails tool calls (bad JSON) | Switch Act → OpenRouter `deepseek/deepseek-chat-v3-0324:free` (handles tool calls) |
| Plan model hits context limit | Task too big — split it or escalate to Claude Code |
| No model configured | Open Cline settings, set Plan + Act to anything — Cline defaults to Sonnet if blank |

**Never need Sonnet.** If Cline insists: the model selection is blank or broken. Set Plan + Act explicitly.

### How to switch models in Cline

1. Click the **model selector** at the top of the Cline panel
2. Cline shows two slots: **Plan** and **Act**
3. Set each independently — pick provider then pick model
4. Click confirm. Takes effect immediately for the next message.

### Prompt to paste into Cline at the start of every session

```
Read AGENTS.md. Then TASK_QUEUE.md.
Find the first READY task where Brain = Cline.
Mark that task IN-PROGRESS in the INDEX immediately (before doing anything else).
Read the full DETAIL SPEC for that task.
Find the Plan mode and Act mode lines in the spec.

Output exactly this before doing anything:
  Task: [T-XXX — task title]
  Tier: [T0/T1/T2/T3/T4]
  Plan mode: set to [provider → model]
  Act mode: set to [provider → model]
  Switch these in Cline settings now, then confirm to proceed.

Wait for Jinu's confirmation. Then execute exactly as written. No improvisation.
After done: write one line to CHANGELOG.md. Update STATUS from IN-PROGRESS to DONE in TASK_QUEUE.md.
Report the Plan/Act model for the NEXT ready Cline task.
```

### Prompt to paste into Kilo Code at the start of every session

```
You are Kilo Code, secondary implementer for RE_OS. You run on your free built-in model.
Read AGENTS.md. Then TASK_QUEUE.md.
Find the first READY task where Brain = Kilo Code.
Mark that task IN-PROGRESS in the INDEX immediately.
Read the full DETAIL SPEC. Execute exactly as written. No improvisation.

HARD LIMIT: If any file you need to read is longer than 300 lines, STOP.
Write to CHANGELOG.md: "T-XXX | FILE TOO LONG — escalated to Cline | Kilo Code | DATE"
In TASK_QUEUE.md: change that task row — Brain = Cline, Status = READY.
Then move to the next Kilo Code task.
```

---

## 11. Log Format — Every Brain, Every Change

All brains write to `CHANGELOG.md` after every meaningful edit.

**Format:**
```
T-XXX | path/to/file.py | what changed (one line) | [Brain name] | YYYY-MM-DD HH:MM
```

**Example:**
```
T-007 | requirements.txt | added httpx>=0.27.0, price-parser>=0.3.4, dateparser>=1.2.0 | Cline | 2026-05-15 14:32
T-009 | utils/db_organizer.py | added micro_market_id to ON CONFLICT SET clause | Aider | 2026-05-15 14:45
```

Aider logs automatically via git commit message. For Aider changes, copy the commit summary to CHANGELOG.md as well so all brains can see it in one place.

---

*This file is maintained by Claude Code. If it conflicts with AGENTS.md, AGENTS.md wins on protocol. This file wins on tool-specific how-to.*
