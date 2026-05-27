# DISPATCH.md — Kilo Code Window Assignments
**Updated by: Claude Code after every review session**
**Last updated: 2026-05-27**

---

## HOW TO USE THIS FILE

When you open a Kilo Code window:
1. Read this file
2. Find your window number (tell me which window you are, or pick the lowest unclaimed one)
3. Do the task listed under your window — read its DETAIL SPEC in TASK_QUEUE.md
4. When done: run `python -m py_compile <file>` to verify, then tell Claude Code
5. Do NOT pick tasks from another window's lane

---

## ACTIVE WINDOWS — CURRENT ASSIGNMENTS

### 🪟 WINDOW 1 — `utils/agent_memory.py` (new file)
**Status:** READY
**Task:** T-220
**One-liner:** Create `utils/agent_memory.py` with `read_memories(agent_id, market, limit=5)` and `write_memory(agent_id, market, fact, confidence)` and decay logic.
**Files to create:** `utils/agent_memory.py`
**Files to touch:** none (new file only)
**Verify:** `python -m py_compile utils/agent_memory.py`
**After done:** Window 3 T-255 unblocks — tell Claude Code.

---

### 🪟 WINDOW 2 — `crews/board_room.py` (new file)
**Status:** READY
**Task:** T-218
**One-liner:** Create `crews/board_room.py` skeleton — `run_board_session(pitch, market)` stub, wired to `board_sessions` table insert, returns `{session_id, status}`.
**Files to create:** `crews/board_room.py`
**Files to touch:** none (new file only)
**Verify:** `python -m py_compile crews/board_room.py`

---

### 🪟 WINDOW 3 — `utils/notifier.py` (new file)
**Status:** READY
**Task:** T-262
**One-liner:** Create `utils/notifier.py` with `send_alert(message, level)` using Telegram bot API. Add `/api/alert/test` GET endpoint to `dashboard/app.py`.
**Files to create:** `utils/notifier.py`
**Files to touch:** `dashboard/app.py` (add one route only — read current file first)
**Verify:** `python -m py_compile utils/notifier.py && python -m py_compile dashboard/app.py`

---

### 🪟 WINDOW 4 — `utils/obsidian_sync.py` (new file)
**Status:** READY
**Task:** T-265
**One-liner:** Create `utils/obsidian_sync.py` with `sync_to_obsidian(market, synthesis_text)`. Target: `D:\Brain\JINU JOSHI\03 LLS\01 Wiki\markets\{market}.md`. Add OBSIDIAN_VAULT_PATH to config/settings.py.
**Files to create:** `utils/obsidian_sync.py`
**Files to touch:** `config/settings.py` (add one env var — read current file first)
**Verify:** `python -m py_compile utils/obsidian_sync.py && python -m py_compile config/settings.py`

---

## QUEUE — NEXT ASSIGNMENTS (after current batch done)

These are locked until current batch completes. Claude Code will update DISPATCH.md.

| Window | Next Task | Blocked By |
|--------|-----------|------------|
| W1 | T-255 — Memory injection into CEO + Analyst at Stage 3 start | T-220 (this batch) |
| W2 | T-257 — 4 dept head agents in `agents/board_room/` | T-218 (this batch) |
| W3 | T-263 — RERA new approval alert → Telegram push | T-262 (this batch) |
| W4 | T-181 — Add duration_seconds to kaveri + portal run logs | — |

---

## COMPLETED LANES (do not re-open)

| Window | Tasks Done | Date |
|--------|-----------|------|
| W1 (was dashboard/app.py) | T-233, T-234, T-235, T-250 | 2026-05-27 |
| W2 (was analyst_agent.py) | T-180, T-206 | 2026-05-27 |
| W3 (was crews + CEO) | T-205, T-183, T-247, T-245/253 | 2026-05-27 |
| Claude Code | T-279 (P0 fix Kilo missed), 2× bug fixes in developer_scout.py | 2026-05-27 |

---

## RULES FOR KILO CODE WINDOWS

1. **Read your task's DETAIL SPEC in TASK_QUEUE.md** — full implementation instructions are there
2. **Stay in your file lane** — only touch files listed under your window
3. **New files = safe to parallel** — creating a new file never conflicts with another window
4. **Existing files = one window at a time** — if two windows touch the same file, conflict
5. **Always py_compile verify** — syntax error in production code = broken pipeline
6. **If the spec says "read current file first"** — do it, don't assume the file matches the spec
7. **When done** — tell Claude Code (or the user) which task ID is done. Do not pick next task yourself.
