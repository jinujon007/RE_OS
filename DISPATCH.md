# DISPATCH.md — Kilo Code Window Assignments
**Last updated: 2026-05-27 (batch 4 — revised)**
**Project root: `d:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS`**

---

## RULES (read once, apply always)

- Stay in your file lane. Only touch files listed under your window.
- `python -m py_compile <file>` after every edit. No exceptions.
- Flask routes: `@app.route(...)` must sit **directly** above its own `def`. Never insert between an existing decorator and its def.
- PostgreSQL only — never sqlite3. Pattern: `from sqlalchemy import create_engine, text` + `from config.settings import DATABASE_URL`
- New files = safe to parallel. Existing files = one window owns it.
- Banned files (do not open): `scrapers/developer_scout.py`, `scrapers/rera_karnataka.py`, `alembic/versions/`, `database/schema.sql`, `docker-compose.yml`
- When done: tell the user the task ID. Do NOT pick next task.

---

## COPY-PASTE START PROMPTS

Paste the entire block for your window into Kilo Code. Nothing else needed.

---

### WINDOW 1 — paste this entire block

```
Working directory: d:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS

Task: T-255 — Memory injection into CEO + Analyst agents

File to edit: crews/market_intel_crew.py ONLY

What to do:
1. At the top of crews/market_intel_crew.py, add this import (after existing imports):
   from utils.agent_memory import read_memories

2. In the function run_market_intelligence(), find the Stage 3 block that starts with:
   _banner("STAGE 3/3", ...)
   
   Before _build_intel_crew() is called, add:
   
   ceo_memories = read_memories("ceo", market_name, limit=5)
   analyst_memories = read_memories("analyst", market_name, limit=5)
   memory_context = ""
   if ceo_memories:
       memory_context = "\n\nINSTITUTIONAL MEMORY — confirmed facts from previous runs:\n"
       memory_context += "\n".join([f"- {m['fact']} (confidence: {m['confidence']:.2f})" for m in ceo_memories])

3. Pass memory_context into _build_intel_crew():
   Change: intel_crew = _build_intel_crew(market_name, db_stats, has_fallback_data)
   To:     intel_crew = _build_intel_crew(market_name, db_stats, has_fallback_data, memory_context=memory_context)

4. In _build_intel_crew(), add memory_context="" to the function signature:
   def _build_intel_crew(market_name, db_stats, has_fallback_data=False, memory_context=""):

5. Inside _build_intel_crew(), find where the CEO task description is built.
   At the end of the description string, append:
   + (f"\n\nINSTITUTIONAL MEMORY:\n{memory_context}" if memory_context else "")

6. If analyst_memories is non-empty, do the same for the analyst task description.

Verify: python -m py_compile crews/market_intel_crew.py
Report: "T-255 done" when clean.
```

---

### WINDOW 2 — paste this entire block

```
Working directory: d:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS

Task: T-257 — Create 4 department head agents in agents/board_room/

Files to create (NEW files only — no existing files touched):
  agents/board_room/__init__.py
  agents/board_room/bd_head.py
  agents/board_room/engineering_head.py
  agents/board_room/finance_head.py
  agents/board_room/operations_head.py

Persona specs are in:
  kilo_output/drafts/board_room_personas/bd_head.yaml
  kilo_output/drafts/board_room_personas/engineering_head.yaml
  kilo_output/drafts/board_room_personas/finance_head.yaml
  kilo_output/drafts/board_room_personas/operations_head.yaml

Pattern for each file (example: bd_head.py):

  from crewai import Agent
  from config.llm_router import get_analysis_llm

  def build_bd_head_agent() -> Agent:
      return Agent(
          role="VP — Business Development & Investment Decisions",
          goal="Evaluate market pitch and deliver GO/NO-GO with 3 risks and 3 upsides.",
          backstory="""<paste persona field from yaml here>""",
          llm=get_analysis_llm(),
          max_iter=2,
          verbose=False,
      )

Use the role/goal/backstory from each YAML file's persona field.
__init__.py should be empty.

Verify each: python -m py_compile agents/board_room/bd_head.py (and the other 3)
Report: "T-257 done" when all 4 files compile clean.
```

---

### WINDOW 3 — paste this entire block

```
Working directory: d:\Brain\JINU JOSHI\03 LLS\02 Projects\RE_market\RE_OS

Task: T-256 — CEO memory write post-synthesis
NOTE: Only start this AFTER Window 1 (T-255) is done AND reviewed by Claude Code.

File to edit: crews/market_intel_crew.py ONLY

What to do:
After Stage 3 completes and the intel report is written to file, add a memory
extraction call. Find the block where synthesis output is written:
  - Look for where report_body or synthesis text is saved to outputs/ file
  - After that write, add:

  from utils.agent_memory import write_memory
  from config.llm_router import get_light_llm

  # Extract 3 key facts from synthesis and write to agent_memories
  try:
      _extract_and_write_memories(market_name, synthesis_text)
  except Exception as exc:
      logger.warning(f"Memory write failed (non-fatal): {exc}")

Add this helper function BEFORE run_market_intelligence():

  def _extract_and_write_memories(market: str, synthesis_text: str):
      """Extract 3 facts from CEO synthesis and write to agent_memories."""
      import json as _json
      llm = get_light_llm()
      prompt = (
          f"From this market report extract exactly 3 key facts as a JSON array. "
          f"Each element: {{\"fact\": \"one sentence with a number\", \"confidence\": 0.6}}. "
          f"Return ONLY the JSON array, no other text.\n\nReport:\n{synthesis_text[:2000]}"
      )
      try:
          response = llm.call(prompt)
          facts = _json.loads(response)
          for item in facts[:3]:
              write_memory("ceo", market, item["fact"], item.get("confidence", 0.6))
      except Exception as exc:
          logger.warning(f"Memory extraction parse failed: {exc}")

Verify: python -m py_compile crews/market_intel_crew.py
Report: "T-256 done" when clean.
```

---

## TASK STATUS

| Task | Window | Status | Notes |
|------|--------|--------|-------|
| T-255 memory injection | W1 | READY | market_intel_crew.py |
| T-257 dept head agents | W2 | READY | new files only |
| T-256 CEO memory write | W3 | SEQ after W1 | market_intel_crew.py |
| T-260 board room API | — | DONE | committed ceccf9f |
| T-262 notifier.py | — | DONE | committed |
| T-265 obsidian sync | — | DONE | wired into crew |
| T-218 board_room.py skeleton | — | DONE | committed |
| T-220 agent_memory.py | — | DONE | committed |

---

## COMPLETED BATCHES

| Batch | Tasks Done |
|-------|-----------|
| B1 | T-233, T-234, T-235, T-250, T-180, T-206, T-205, T-183, T-247, T-245/253 |
| B2 | T-218, T-220, T-262, T-265 |
| B3 | T-260 |
| Claude Code fixes | T-279, developer_scout ×3, health route, SQLite→PG, dup route/env |
