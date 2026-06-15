"""
RE_OS — Operations Head Agent (Sprint 58 — Operations Department)
Role: Decompose approved Board Room actions into per-dept sub-tasks.
Uses ANALYSIS LLM tier (Cerebras/Groq).
"""

import json
from dataclasses import dataclass, asdict
from loguru import logger

__all__ = ["TaskDelegatorResult", "OperationsHeadAgent"]

_LLM_IMPORTED = False
try:
    from config.llm_router import get_analysis_llm as _get_analysis_llm

    _LLM_IMPORTED = True
except ImportError:
    logger.warning("[OpsHead] config.llm_router not available — will use fallback only")


@dataclass
class TaskDelegatorResult:
    task_id: str = ""
    title: str = ""
    dept: str = ""
    status: str = "todo"

    def to_dict(self) -> dict:
        return asdict(self)


def _task_delegator_tool(
    project_id: str, task_title: str, dept: str, due_days: int = 7
) -> TaskDelegatorResult:
    if due_days < 1:
        due_days = 1
    """Write a task to project_tasks DB table. Returns TaskDelegatorResult."""
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        from datetime import datetime, timedelta, timezone

        due = (datetime.now(timezone.utc) + timedelta(days=due_days)).strftime(
            "%Y-%m-%d"
        )
        with get_engine().begin() as conn:
            row = conn.execute(
                text("""
                    INSERT INTO project_tasks (project_id, title, owner_agent_id, dept, status, due_date)
                    VALUES (:pid, :title, 'ops_head', :dept, 'todo', CAST(:due AS date))
                    RETURNING id, title, dept, status
                """),
                {"pid": project_id, "title": task_title, "dept": dept, "due": due},
            ).fetchone()
            if row:
                logger.info("[OpsHead] Task created: {} ({})", task_title, dept)
                return TaskDelegatorResult(
                    task_id=str(row[0]),
                    title=str(row[1]),
                    dept=str(row[2]),
                    status=str(row[3]),
                )
    except Exception as exc:
        logger.warning("[OpsHead] Task delegation failed: {}", exc)
    return TaskDelegatorResult(status="error")


class OperationsHeadAgent:
    """Operations Head — converts Board Room actions into executable tasks.

    Receives a list of approved actions from the Board Room. Uses ANALYSIS LLM
    to decompose each action into per-department sub-tasks. Falls back to
    rule-based decomposition when LLM unavailable.
    """

    _LLM_TIMEOUT_S = 45

    def __init__(self, temperature: float = 0.3):
        self.temperature = temperature

    def _build_system_prompt(self) -> str:
        return (
            "You are the Operations Head for LLS (Lavish Life Styles), a premium real estate "
            "developer in North Bengaluru. Your role is to take approved Board Room actions "
            "and decompose them into concrete, executable tasks per department.\n\n"
            "Departments available: bd (business development), legal, finance, engineering, ops.\n\n"
            "For each action, output a JSON list of tasks. Each task has:\n"
            "- title: specific, actionable task (≤80 chars)\n"
            "- dept: one of bd, legal, finance, engineering, ops\n"
            "- due_days: estimated days to complete (integer, 1-30)\n\n"
            "Rules:\n"
            "1. Every action must produce at least 1 task\n"
            "2. Tasks must be concrete, not vague ('Call landowner' not 'Follow up')\n"
            "3. Due dates must be realistic for the department\n"
            "4. Return ONLY valid JSON — no markdown, no explanation"
        )

    def _build_prompt(self, actions: list[str], project_context: str) -> str:
        actions_str = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(actions))
        return (
            f"Approved Board Room actions for project:\n{project_context}\n\n"
            f"Actions to decompose:\n{actions_str}\n\n"
            "Return a JSON array of tasks, each with 'title', 'dept', 'due_days'."
        )

    def _fallback_decompose(
        self, actions: list[str], project_id: str
    ) -> list[TaskDelegatorResult]:
        dept_map = {
            "land": "bd",
            "owner": "bd",
            "survey": "bd",
            "legal": "legal",
            "rera": "legal",
            "encumbrance": "legal",
            "financial": "finance",
            "irr": "finance",
            "psf": "finance",
            "design": "engineering",
            "architect": "engineering",
            "fsi": "engineering",
            "due diligence": "ops",
            "site visit": "ops",
            "coordinate": "ops",
        }
        results = []
        for action in actions:
            action_lower = action.lower()
            dept = "ops"
            for keyword, mapped_dept in dept_map.items():
                if keyword in action_lower:
                    dept = mapped_dept
                    break
            title = action[:80]
            result = _task_delegator_tool(project_id, title, dept, due_days=7)
            results.append(result)
        return results

    def _parse_llm_response(self, raw: str) -> list[dict]:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            try:
                start = raw.index("[")
                end = raw.rindex("]") + 1
                data = json.loads(raw[start:end])
            except (ValueError, json.JSONDecodeError):
                logger.warning("[OpsHead] Failed to parse LLM output as JSON")
                return []
        if isinstance(data, dict):
            data = data.get("tasks", [])
        if not isinstance(data, list):
            return []
        return data

    def decompose_actions(
        self, actions: list[str], project_id: str, project_context: str = ""
    ) -> list[TaskDelegatorResult]:
        if not actions:
            logger.info("[OpsHead] No actions to decompose")
            return []
        if not project_id or not isinstance(project_id, str) or len(project_id) > 100:
            logger.warning("[OpsHead] Invalid project_id: {}", project_id)
            return []

        if not _LLM_IMPORTED:
            logger.warning("[OpsHead] LLM unavailable — using fallback decomposition")
            return self._fallback_decompose(actions, project_id)

        try:
            llm = _get_analysis_llm(temperature=self.temperature)
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_prompt(actions, project_context)

            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    llm.invoke,
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                response = future.result(timeout=self._LLM_TIMEOUT_S)

            raw = ""
            if hasattr(response, "content"):
                raw = response.content
            elif isinstance(response, str):
                raw = response
            else:
                raw = str(response)

            tasks = self._parse_llm_response(raw)
            results = []
            for t in tasks:
                title = str(t.get("title", ""))[:80]
                dept = str(t.get("dept", "ops"))
                due_days = int(t.get("due_days", 7))
                result = _task_delegator_tool(
                    project_id, title, dept, due_days=due_days
                )
                results.append(result)
            if results:
                return results

        except concurrent.futures.TimeoutError:
            logger.warning("[OpsHead] LLM timeout — using fallback")
        except Exception as exc:
            logger.warning("[OpsHead] LLM error: {} — using fallback", exc)

        return self._fallback_decompose(actions, project_id)
