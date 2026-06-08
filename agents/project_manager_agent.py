"""
RE_OS — Project Manager Agent (Sprint 58 — Operations Department)
Role: Track project status, generate status reports and weekly briefs.
Uses LIGHT LLM tier (Cerebras). Parameterized by project_id.
"""

import os
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from loguru import logger

__all__ = ["ProjectStatusReport", "ProjectManagerAgent"]

_LLM_IMPORTED = False
try:
    from config.llm_router import get_light_llm as _get_light_llm
    _LLM_IMPORTED = True
except ImportError:
    logger.warning("[PM] config.llm_router not available — will use fallback only")


@dataclass
class ProjectStatusReport:
    project_id: str = ""
    project_name: str = ""
    status: str = ""
    open_task_count: int = 0
    done_task_count: int = 0
    overdue_count: int = 0
    current_stage_days: int = 0
    next_task: str = ""
    days_in_stage: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _validate_project_id(pid: str) -> bool:
    return bool(pid and len(pid) > 0 and len(pid) < 100)


def _get_project_status(project_id: str) -> ProjectStatusReport:
    """Query DB for project status report. Pure data — no LLM."""
    report = ProjectStatusReport(project_id=project_id)
    if not _validate_project_id(project_id):
        report.status = "invalid_id"
        return report
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conn:
            proj = conn.execute(
                text("""
                    SELECT id, name, status, created_at
                    FROM projects WHERE id = :pid
                """),
                {"pid": project_id},
            ).fetchone()
            if not proj:
                report.status = "not_found"
                return report

            report.project_id = str(proj[0])
            report.project_name = str(proj[1] or "")
            report.status = str(proj[2] or "unknown")
            created = proj[3]
            if created:
                report.days_in_stage = (datetime.now(timezone.utc) - created).days

            tasks = conn.execute(
                text("""
                    SELECT status, COUNT(*) as cnt
                    FROM project_tasks WHERE project_id = :pid
                    GROUP BY status
                """),
                {"pid": project_id},
            ).fetchall()

            for t in tasks:
                st = str(t[0] or "")
                cnt = int(t[1])
                if st in ("todo", "in_progress"):
                    report.open_task_count += cnt
                elif st == "done":
                    report.done_task_count += cnt

            overdue = conn.execute(
                text("""
                    SELECT COUNT(*) FROM project_tasks
                    WHERE project_id = :pid
                      AND status IN ('todo', 'in_progress')
                      AND due_date < CURRENT_DATE
                """),
                {"pid": project_id},
            ).scalar()
            report.overdue_count = int(overdue) if overdue else 0

            next_t = conn.execute(
                text("""
                    SELECT title FROM project_tasks
                    WHERE project_id = :pid AND status IN ('todo', 'in_progress')
                    ORDER BY due_date ASC NULLS LAST, created_at ASC
                    LIMIT 1
                """),
                {"pid": project_id},
            ).fetchone()
            if next_t:
                report.next_task = str(next_t[0] or "")

    except Exception as exc:
        logger.warning("[PM] Status report query failed: {}", exc)
        report.status = "error"
    return report


def _generate_weekly_brief_file(project_id: str, content: str) -> str:
    """Write weekly brief to outputs/pm_briefs/{id}_{date}.md. Keeps max 20 per project."""
    brief_dir = "outputs/pm_briefs"
    os.makedirs(brief_dir, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = f"{brief_dir}/{project_id}_{date_str}.md"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("[PM] Weekly brief written: {}", path)
        # Rotate: keep max 20 briefs per project
        existing = sorted(
            p for p in os.listdir(brief_dir) if p.startswith(project_id) and p.endswith(".md")
        )
        while len(existing) > 20:
            oldest = existing.pop(0)
            os.remove(os.path.join(brief_dir, oldest))
            logger.info("[PM] Rotated out old brief: {}", oldest)
        return path
    except Exception as exc:
        logger.warning("[PM] Failed to write brief: {}", exc)
        return ""


class ProjectManagerAgent:
    """Project Manager — tracks project health and generates weekly briefs.

    Uses LIGHT LLM tier. Pure data status reporting uses only DB queries.
    Weekly brief generation uses LLM to synthesize status data into narrative.
    """

    _LLM_TIMEOUT_S = 30

    def __init__(self, temperature: float = 0.3):
        self.temperature = temperature

    def status_report(self, project_id: str) -> ProjectStatusReport:
        return _get_project_status(project_id)

    def weekly_brief(self, project_id: str) -> str:
        """Generate and save a weekly brief for the given project."""
        report = _get_project_status(project_id)
        if report.status in ("not_found", "error"):
            return f"Unable to generate brief: project {report.status}"

        if not _LLM_IMPORTED:
            return self._fallback_brief(report)

        try:
            llm = _get_light_llm(temperature=self.temperature)
            prompt = (
                f"Write a 1-page weekly brief for project '{report.project_name}' "
                f"(status: {report.status}, {report.days_in_stage}d in stage).\n"
                f"Open: {report.open_task_count}, Done: {report.done_task_count}, "
                f"Overdue: {report.overdue_count}.\n"
                f"Next: {report.next_task}\n\n"
                "Sections: Status Summary, Progress, Blockers, Next Week."
            )

            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    llm.invoke,
                    [
                        {"role": "system",
                         "content": "You are a Project Manager writing a weekly status brief."},
                        {"role": "user", "content": prompt},
                    ]
                )
                response = future.result(timeout=self._LLM_TIMEOUT_S)

            raw = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            logger.warning("[PM] Weekly brief LLM failed: {}", exc)
            raw = self._fallback_brief(report)

        path = _generate_weekly_brief_file(project_id, raw)
        return raw + f"\n\n---\n_Saved to: {path}_" if path else raw

    def _fallback_brief(self, report: ProjectStatusReport) -> str:
        return (
            f"# Weekly Project Brief — {report.project_name or report.project_id}\n\n"
            f"**Status:** {report.status}\n"
            f"**Days in stage:** {report.days_in_stage}\n\n"
            f"## Progress\n"
            f"- Open tasks: {report.open_task_count}\n"
            f"- Completed: {report.done_task_count}\n"
            f"- Overdue: {report.overdue_count}\n\n"
            f"## Next Task\n"
            f"{report.next_task or 'None scheduled'}\n\n"
            f"## Note\n"
            f"Automated brief — LLM was unavailable. Data from project_tasks table."
        )
