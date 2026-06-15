"""
RE_OS — Runbook Documenter Agent (T-1010, Sprint 61)
Writes process-automation runbooks to docs/solutions/process-automation/.
LIGHT LLM tier. Falls back to template-based runbook when LLM unavailable.
"""

import json
import os
import threading
from pathlib import Path
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4
from loguru import logger

from utils.process_automation import (
    retry_with_backoff,
    run_with_timeout,
    safe_extract_json,
    LLM_TIMEOUT_S as _LLM_TIMEOUT,
    LLM_RETRY_MAX,
)
from config.metrics import process_audit_runbooks_total, process_audit_llm_calls_total

__all__ = ["RunbookDocumenterAgent"]

_LLM_IMPORTED = False
_LLM_LOCK = Lock()
try:
    from config.llm_router import get_light_llm as _get_light_llm

    _LLM_IMPORTED = True
except ImportError:
    logger.warning(
        "[RunbookDoc] config.llm_router not available — will use fallback only"
    )

_SOLUTIONS_DIR = (
    Path(__file__).resolve().parent.parent / "docs" / "solutions" / "process-automation"
)
_RUNBOOK_WRITE_LOCK = threading.Lock()
_LLM_RESPONSE_MAX_BYTES = 100_000
_REQUIRED_RUNBOOK_SECTIONS = [
    "Problem Type",
    "Tags",
    "Description",
    "Recommended Action",
    "Solution",
]

_MAX_RUNBOOK_SIZE = int(
    os.environ.get("PROCESS_AUTOMATION_RUNBOOK_MAX_BYTES", "500_000")
)


def _resolve_path(date_str: str, stage: str) -> Path:
    _SOLUTIONS_DIR.mkdir(parents=True, exist_ok=True)
    base = _SOLUTIONS_DIR / f"{date_str}_{stage}_runbook"
    path = base.with_suffix(".md")
    version = 1
    with _RUNBOOK_WRITE_LOCK:
        while path.exists():
            version += 1
            path = Path(str(base) + f"_v{version}.md")
    return path


def _validate_runbook_content(content: str) -> bool:
    if not content or len(content) < 50:
        return False
    if len(content) > _MAX_RUNBOOK_SIZE:
        logger.warning(
            "[RunbookDoc] Runbook content exceeds max size ({} > {})",
            len(content),
            _MAX_RUNBOOK_SIZE,
        )
        return False
    if not content.startswith("#"):
        return False
    missing = [s for s in _REQUIRED_RUNBOOK_SECTIONS if s not in content]
    if missing:
        logger.warning("[RunbookDoc] Runbook missing sections: {}", missing)
        return False
    return True


def _fallback_runbook(
    path: Path, bottleneck: dict[str, Any], proposal: dict[str, Any] | None = None
) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p_desc = (
        proposal.get("description", "Run pipeline audit.")
        if proposal
        else "Run pipeline audit."
    )
    p_file = proposal.get("target_file", "N/A") if proposal else "N/A"
    p_prio = proposal.get("priority", "LOW") if proposal else "LOW"
    p_tokens = proposal.get("estimated_token_saving_pct", 0) if proposal else 0
    content = (
        f"# Runbook — {bottleneck.get('bottleneck_stage', 'unknown')} Bottleneck\n\n"
        f"_Generated: {today}_\n"
        f"_Module: process-automation/runbook-documenter_\n\n"
        f"## Problem Type\n{bottleneck.get('bottleneck_stage', 'unknown')}\n\n"
        f"## Tags\n`process-automation`, `runbook`, "
        f"`{bottleneck.get('bottleneck_stage', 'unknown')}`\n\n"
        f"## Description\n"
        f"{bottleneck.get('bottleneck_reason', 'No bottleneck reason provided.')}\n\n"
        f"## Recommended Action\n{bottleneck.get('recommendation', p_desc)}\n\n"
        f"## Target File\n{p_file}\n\n"
        f"## Priority\n{p_prio}\n\n"
        f"## Estimated Token Saving\n{p_tokens}%\n\n"
        "## Solution\n"
        "1. Review the bottleneck stage identified above.\n"
        "2. Implement the recommended action.\n"
        "3. Monitor the next 10 pipeline runs for improvement.\n"
        "4. If no improvement, re-run the Log Analyst and Efficiency Optimizer.\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


_SYSTEM_PROMPT = (
    "You are a Runbook Documenter for RE_OS. Write clear, concise SOP documents "
    "in Markdown. Each runbook must include: problem type, tags, description, "
    "recommended action, target file, priority, solution steps, and estimated impact.\n\n"
    "Return ONLY valid Markdown starting with '# ' — no JSON, no explanatory wrapper."
)


class RunbookDocumenterAgent:
    _CORRELATION_PREFIX = "runbook_doc"

    def __init__(self):
        self._correlation_id = f"{self._CORRELATION_PREFIX}_{uuid4().hex[:8]}"

    def run(
        self,
        bottleneck_report: dict[str, Any],
        improvement_proposal: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bottleneck = bottleneck_report
        proposal = improvement_proposal or {}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stage = bottleneck.get("bottleneck_stage", "unknown")
        path = _resolve_path(today, stage)

        if _LLM_IMPORTED:
            try:
                result = self._try_llm_runbook(path, bottleneck, proposal)
                if result:
                    process_audit_runbooks_total.labels(method="llm").inc()
                    logger.info(
                        "[{}] Runbook written (LLM): {}",
                        self._correlation_id,
                        path,
                    )
                    return {"status": "done", "path": str(path), "method": "llm"}
            except Exception as exc:
                logger.warning(
                    "[{}] LLM runbook failed: {}",
                    self._correlation_id,
                    exc,
                )

        _fallback_runbook(path, bottleneck, proposal)
        process_audit_runbooks_total.labels(method="fallback").inc()
        logger.info(
            "[{}] Runbook written (fallback): {}",
            self._correlation_id,
            path,
        )
        return {"status": "done", "path": str(path), "method": "fallback"}

    def _try_llm_runbook(
        self, path: Path, bottleneck: dict[str, Any], proposal: dict[str, Any]
    ) -> Path | None:
        llm = _get_light_llm()

        def _do_llm_call():
            return llm.invoke(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Write a runbook/SOP document in Markdown for the following issue:\n\n"
                            f"Bottleneck: {json.dumps(bottleneck, default=str)}\n\n"
                            f"Proposal: {json.dumps(proposal, default=str)}\n\n"
                            "Include sections: Problem Type, Tags, Description, "
                            "Recommended Action, Target File, Priority, Estimated Impact, "
                            "and numbered Solution Steps.\n"
                            "Start with '# ' — Markdown only, no code fences."
                        ),
                    },
                ]
            )

        response = retry_with_backoff(
            lambda: run_with_timeout(_do_llm_call, _LLM_TIMEOUT, "runbook_doc_llm"),
            max_retries=LLM_RETRY_MAX,
            context="runbook_doc_llm",
        )
        if response is None:
            process_audit_llm_calls_total.labels(
                agent="runbook_doc", result="failed"
            ).inc()
            return None

        raw = ""
        if hasattr(response, "content"):
            raw = response.content or ""
        elif isinstance(response, str):
            raw = response
        else:
            raw = str(response)

        if len(raw) > _LLM_RESPONSE_MAX_BYTES:
            logger.warning(
                "[{}] LLM response too large ({} bytes), using fallback",
                self._correlation_id,
                len(raw),
            )
            return None

        if not _validate_runbook_content(raw):
            logger.warning(
                "[{}] LLM runbook validation failed, using fallback",
                self._correlation_id,
            )
            return None

        path.write_text(raw, encoding="utf-8")
        return path
