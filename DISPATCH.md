# DISPATCH.md — Kilo Code Window Assignments
**Updated by: Claude Code after every review session**
**Last updated: 2026-05-27 (batch 4)**

---

## HOW TO USE

1. Read `KILO_BRIEF.md` first — rules, banned files, verify checklist
2. Find your window number below
3. Do ONLY the task listed — read its DETAIL SPEC in `TASK_QUEUE.md`
4. `python -m py_compile` every file you touched — must be clean
5. Report done to user. Do NOT pick the next task yourself.

---

## ACTIVE WINDOWS — BATCH 4

### 🪟 WINDOW 1 — Memory injection into pipeline
**Task:** T-255
**File:** `crews/market_intel_crew.py` only
**What to do:**
Before Stage 3 crew kickoff in `run_market_intelligence()`, add:
```python
from utils.agent_memory import read_memories
memories = read_memories("ceo", market_name, limit=5)
memory_context = "\n".join([f"- {m['fact']} (confidence: {m['confidence']:.2f})" for m in memories])
```
Then append `memory_context` to the CEO task description (only if memories non-empty).
Do the same for Analyst using `read_memories("analyst", market_name, limit=5)`.
Full spec in `TASK_QUEUE.md ## T-255`.
**Verify:** `python -m py_compile crews/market_intel_crew.py`
**WARNING:** Window 4 also touches this file — do NOT run simultaneously.

---

### 🪟 WINDOW 2 — Board Room API endpoints
**Task:** T-260
**File:** `dashboard/app.py` only
**What to do:**
Add two routes using `run_board_session()` and `get_board_session()` from `crews/board_room.py`:
```python
@app.route("/api/board/session", methods=["POST"])
def board_session_create(): ...

@app.route("/api/board/session/<session_id>", methods=["GET"])
def board_session_get(session_id): ...
```
Full spec in `TASK_QUEUE.md ## T-260`.
DECORATOR RULE: place each `@app.route` immediately above its own `def`. Do not insert between existing decorator+def pairs.
**Verify:** `python -m py_compile dashboard/app.py`

---

### 🪟 WINDOW 3 — Department head agents (new files)
**Task:** T-257
**Files:** New folder `agents/board_room/` with 5 new files
**What to create:**
- `agents/board_room/__init__.py` — empty
- `agents/board_room/bd_head.py` — Business Development agent
- `agents/board_room/engineering_head.py` — Engineering agent
- `agents/board_room/finance_head.py` — Finance agent
- `agents/board_room/operations_head.py` — Operations agent

Each file: one `build_<dept>_head_agent()` function returning a CrewAI `Agent`.
Use `get_analysis_llm()` from `config/llm_router.py`.
Read persona specs from `kilo_output/drafts/` (T-223 output).
Full spec in `TASK_QUEUE.md ## T-257`.
**Verify:** `python -m py_compile agents/board_room/bd_head.py` (and the other 3)
**Safe:** New files only — no collision risk.

---

### 🪟 WINDOW 4 — CEO memory write post-synthesis
**Task:** T-256
**File:** `crews/market_intel_crew.py` only
**WARNING:** Window 1 ALSO touches this file. Start Window 4 ONLY after Window 1 is DONE and Claude Code has reviewed + committed it.
**What to do:**
After CEO synthesis text is written to file in `run_market_intelligence()`, call a mini LLM extraction and write 3 facts to `agent_memories` via `write_memory("ceo", market_name, fact, confidence=0.6)`.
Full spec in `TASK_QUEUE.md ## T-256`.
**Verify:** `python -m py_compile crews/market_intel_crew.py`

---

## QUEUE — NEXT BATCH (after current batch done + reviewed)

| Window | Task | Notes |
|--------|------|-------|
| W1 | T-263 — RERA new approval alert → Telegram | After T-262 verified working |
| W2 | T-261 — Board Room dashboard panel | After T-260 done |
| W3 | T-258 — concurrent runner run_board_session() | After T-257 done |
| W4 | T-181 — duration_seconds to kaveri+portal run logs | Standalone, no deps |

---

## COMPLETED (do not re-open)

| Batch | Tasks | Notes |
|-------|-------|-------|
| B1-W1 | T-233, T-234, T-235, T-250 | dashboard/app.py fixes |
| B1-W2 | T-180, T-206 | analyst_agent.py |
| B1-W3 | T-205, T-183, T-247, T-245/253 | crews + CEO |
| Claude Code | T-279 P0, developer_scout bugs ×3 | P0 fix + recurring corruption |
| B2-W1 | T-220 | agent_memory.py (PostgreSQL rewrite by Claude Code) |
| B2-W2 | T-218 | board_room.py skeleton (expanded by Claude Code) |
| B2-W3 | T-262 | utils/notifier.py |
| B2-W4 | T-265 | utils/obsidian_sync.py + wired into crew |
| Claude Code | Dup route/import, dup env vars, SQLite→PG, NotImplementedError stub | Review fixes |
| B3-W? | T-262 notifier.py simplification | OK — kept |
| Claude Code | /api/health route collision, developer_scout ×2 corruption | Fixed again |

---

## KNOWN RECURRING BUGS — WATCH FOR THESE

| Bug | How it happens | Detection |
|-----|---------------|-----------|
| Decorator collision | New route inserted between existing @app.route and def | Flask returns wrong handler |
| SQLite instead of PostgreSQL | Kilo Code defaults to sqlite3 | grep sqlite in new file |
| Docstring corruption | Kilo Code edits developer_scout.py header | py_compile fails |
| Duplicate env var | Two windows append to same file | grep shows duplicate section |
| Duplicate function def | Two windows both add same function | Second def silently shadows first |
