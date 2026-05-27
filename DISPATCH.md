# DISPATCH.md — Kilo Code Window Assignments
**Updated by: Claude Code after every review session**
**Last updated: 2026-05-27 (batch 3)**

---

## HOW TO USE THIS FILE

When you open a Kilo Code window:
1. Read KILO_BRIEF.md first (stack reference, rules)
2. Read this file — find your window number
3. Do ONLY the task listed under your window — read its full spec in TASK_QUEUE.md
4. Verify with `python -m py_compile <file>` before reporting done
5. Do NOT touch files listed under another window

---

## ⚠️ COLLISION RULE — READ BEFORE STARTING

Two windows must NEVER edit the same file at the same time.
If your task requires editing a file another window is using: STOP and tell the user.
New files = always safe. Existing files = one window only.

---

## ACTIVE WINDOWS — CURRENT ASSIGNMENTS

### 🪟 WINDOW 1 — `crews/market_intel_crew.py` memory injection
**Status:** READY
**Task:** T-255
**One-liner:** At Stage 3 start in `run_market_intelligence()`, call `read_memories("ceo", market, limit=5)` and append facts to CEO backstory. Same for Analyst. Read the full T-255 spec in TASK_QUEUE.md.
**Files to touch:** `crews/market_intel_crew.py` only
**Read first:** Confirm `utils/agent_memory.py` exists and has `read_memories()` — it does.
**Verify:** `python -m py_compile crews/market_intel_crew.py`
**⚠️ Window 1 owns crews/market_intel_crew.py — no other window touches it**

---

### 🪟 WINDOW 2 — `dashboard/app.py` Board Room API endpoints
**Status:** READY
**Task:** T-260
**One-liner:** Add `POST /api/board/session` and `GET /api/board/session/<session_id>` routes to dashboard/app.py using `run_board_session()` and `get_board_session()` from `crews/board_room.py`. Read full T-260 spec in TASK_QUEUE.md.
**Files to touch:** `dashboard/app.py` only
**Read first:** Confirm `crews/board_room.py` exists and has `run_board_session()` and `get_board_session()` — it does.
**Verify:** `python -m py_compile dashboard/app.py`
**⚠️ Window 2 owns dashboard/app.py — no other window touches it**

---

### 🪟 WINDOW 3 — `agents/board_room/` dept head agents
**Status:** READY
**Task:** T-257
**One-liner:** Create `agents/board_room/` folder with 4 files: `bd_head.py`, `engineering_head.py`, `finance_head.py`, `operations_head.py`. Each returns a CrewAI Agent with role/goal/backstory from the persona specs (read kilo_output/drafts/ for T-223 output). Read full T-257 spec in TASK_QUEUE.md.
**Files to create:** `agents/board_room/__init__.py`, `agents/board_room/bd_head.py`, `agents/board_room/engineering_head.py`, `agents/board_room/finance_head.py`, `agents/board_room/operations_head.py`
**Files to touch:** none (new files only)
**Verify:** `python -m py_compile agents/board_room/bd_head.py` (and the other 3)
**⚠️ New files only — safe to run parallel with other windows**

---

### 🪟 WINDOW 4 — `utils/obsidian_sync.py` integration into pipeline
**Status:** READY
**Task:** Wire T-265 into the crew pipeline
**One-liner:** `utils/obsidian_sync.py` exists but is NOT yet called from `crews/market_intel_crew.py`. Add the call after CEO synthesis is written to file. Read the T-265 spec in TASK_QUEUE.md for exact location.
**Files to touch:** `crews/market_intel_crew.py` only
**⚠️ CONFLICT CHECK:** Window 1 also touches `crews/market_intel_crew.py`. DO NOT run Window 4 at the same time as Window 1. Start Window 4 ONLY after Window 1 reports done and you have reviewed + committed.

---

## QUEUE — NEXT ASSIGNMENTS (locked until current batch done)

| Window | Next Task | Blocked By |
|--------|-----------|------------|
| W1 | T-256 — CEO memory write post-synthesis | T-255 (this batch) |
| W2 | T-261 — Board Room dashboard panel | T-260 (this batch) |
| W3 | T-258 — concurrent runner run_board_session() | T-257 (this batch) |
| W4 | T-263 — RERA new approval alert | — (no dep) |

---

## COMPLETED (do not re-open)

| Batch | Tasks | Status |
|-------|-------|--------|
| Batch 1 — W1 dashboard/app.py | T-233, T-234, T-235, T-250 | ✅ DONE |
| Batch 1 — W2 analyst_agent.py | T-180, T-206 | ✅ DONE |
| Batch 1 — W3 crews + CEO | T-205, T-183, T-247, T-245/253 | ✅ DONE |
| Claude Code | T-279 P0 fix, 2× developer_scout bugs | ✅ DONE |
| Batch 2 — W1 | T-220 agent_memory.py (rewritten to PostgreSQL by Claude Code) | ✅ DONE |
| Batch 2 — W2 | T-218 board_room.py skeleton (expanded to DB-wired by Claude Code) | ✅ DONE |
| Batch 2 — W3 | T-262 utils/notifier.py | ✅ DONE |
| Batch 2 — W4 | T-265 utils/obsidian_sync.py | ✅ DONE |
| Claude Code review | Duplicate route/import in dashboard/app.py, duplicate env vars in settings.py | ✅ FIXED |

---

## RULES

1. One window per file lane — check the ⚠️ notes above
2. Window 4 this batch is SEQUENCED after Window 1 (same file)
3. Always `python -m py_compile` before reporting done
4. If a dependency file doesn't exist or has wrong API: stop, tell user
5. New files = safe to run parallel. Existing files = one window at a time.
