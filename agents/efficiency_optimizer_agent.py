"""
RE_OS — Efficiency Optimizer Agent (T-1009, Sprint 61)
Takes BottleneckReport + OptimizerReport, produces a single ImprovementProposal.
LIGHT LLM tier. Falls back to template-based proposal when LLM unavailable.
"""

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from threading import Lock
from typing import Any
from loguru import logger

from utils.process_automation import (
    ValidationError, retry_with_backoff, run_with_timeout,
    safe_extract_json, validate_bottleneck_report, validate_proposal_data,
    LLM_TIMEOUT_S as _LLM_TIMEOUT, LLM_RETRY_MAX, HTTP_TIMEOUT_S,
    HTTP_RETRY_MAX,
)
from config.metrics import (
    process_audit_reports_total, process_audit_llm_calls_total,
    process_audit_tasks_created_total,
)

__all__ = ["ImprovementProposal", "EfficiencyOptimizerAgent"]

_LLM_IMPORTED = False
try:
    import httpx as _httpx
except ImportError:
    _httpx = None
_LLM_LOCK = Lock()
try:
    from config.llm_router import get_light_llm as _get_light_llm
    _LLM_IMPORTED = True
except ImportError:
    logger.warning("[EfficiencyOpt] config.llm_router not available — will use fallback only")

_API_BASE_URL = os.environ.get("RE_OS_API_BASE_URL", "http://localhost:8050")


@dataclass
class ImprovementProposal:
    proposal_id: str = ""
    title: str = ""
    description: str = ""
    target_file: str = ""
    priority: str = "LOW"
    estimated_token_saving_pct: float = 0.0
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


_PRIORITIES = ("HIGH", "MEDIUM", "LOW")


def _fallback_proposal() -> ImprovementProposal:
    return ImprovementProposal(
        proposal_id=str(uuid.uuid4()),
        title="Review LLM token usage",
        description="Run token budget audit against agent_runs.",
        target_file="config/llm_router.py",
        priority="LOW",
        estimated_token_saving_pct=0.0,
        confidence=0.5,
    )


def _auto_create_task(proposal: ImprovementProposal) -> bool:
    if proposal.priority not in ("HIGH", "MEDIUM"):
        return False
    if _httpx is None:
        return False

    def _do_post():
        resp = _httpx.post(
            f"{_API_BASE_URL}/api/projects/system/tasks",
            json={
                "title": proposal.title,
                "dept": "engineering",
                "notes": proposal.description,
                "due_days": 14,
            },
            timeout=HTTP_TIMEOUT_S,
        )
        return resp.status_code in (200, 201)

    result = retry_with_backoff(
        _do_post, max_retries=HTTP_RETRY_MAX, context="auto_create_task",
    )
    if result:
        process_audit_tasks_created_total.labels(priority=proposal.priority).inc()
        return True
    logger.warning("[EfficiencyOpt] Failed to auto-create task after {} retries", HTTP_RETRY_MAX)
    return False


_SYSTEM_PROMPT = (
    "You are the Efficiency Optimizer for RE_OS, a real estate intelligence system. "
    "Your job is to propose one specific, actionable improvement per run. "
    "Focus on: reducing redundant LLM calls, improving cache hit rates, "
    "or parallelizing slow stages. Be specific — name the file and line if possible.\n\n"
    "Return ONLY valid JSON with these keys:\n"
    '  "title": str (≤100 chars),\n'
    '  "description": str (200–500 words),\n'
    '  "target_file": str (file path),\n'
    '  "priority": "HIGH"|"MEDIUM"|"LOW",\n'
    '  "estimated_token_saving_pct": float (0–100),\n'
    '  "confidence": float (0–1).\n'
    "No markdown, no code fences, no explanatory wrapper."
)


class EfficiencyOptimizerAgent:
    _CORRELATION_PREFIX = "efficiency_opt"

    def __init__(self):
        self._correlation_id = f"{self._CORRELATION_PREFIX}_{uuid.uuid4().hex[:8]}"

    def run(self, bottleneck_report: dict[str, Any],
            optimizer_report: dict[str, Any] | None = None) -> dict[str, Any]:
        validation_errors = validate_bottleneck_report(bottleneck_report)
        if validation_errors:
            logger.warning("[{}] Input validation errors: {}", self._correlation_id, validation_errors)

        proposal = self._generate_proposal(bottleneck_report, optimizer_report or {})
        task_created = _auto_create_task(proposal) if proposal.priority in ("HIGH", "MEDIUM") else False

        process_audit_reports_total.labels(
            agent="efficiency_optimizer",
            method="llm" if _LLM_IMPORTED else "fallback",
        ).inc()

        logger.info(
            "[{}] Proposal — title=\"{}\", priority={}, confidence={:.2f}, task_created={}",
            self._correlation_id, proposal.title[:60], proposal.priority,
            proposal.confidence, task_created,
        )
        return {
            "status": "done",
            "proposal": proposal.to_dict(),
            "task_created": task_created,
            "correlation_id": self._correlation_id,
        }

    def _generate_proposal(self, bottleneck: dict[str, Any],
                           optimizer: dict[str, Any]) -> ImprovementProposal:
        if _LLM_IMPORTED:
            try:
                llm_proposal = self._try_llm_proposal(bottleneck, optimizer)
                if llm_proposal:
                    return llm_proposal
            except Exception as exc:
                logger.warning("[{}] LLM proposal failed: {}", self._correlation_id, exc)
        return self._template_proposal(bottleneck)

    def _try_llm_proposal(self, bottleneck: dict[str, Any],
                          optimizer: dict[str, Any]) -> ImprovementProposal | None:
        llm = _get_light_llm()

        def _do_llm_call():
            return llm.invoke([
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Propose ONE concrete improvement to reduce token usage or runtime.\n\n"
                        f"Bottleneck Report: {json.dumps(bottleneck, default=str)}\n\n"
                        f"Optimizer Report: {json.dumps(optimizer, default=str)}\n\n"
                        "Return JSON only with keys: title, description, target_file, "
                        "priority, estimated_token_saving_pct, confidence."
                    ),
                },
            ])

        response = retry_with_backoff(
            lambda: run_with_timeout(_do_llm_call, _LLM_TIMEOUT, "efficiency_opt_llm"),
            max_retries=LLM_RETRY_MAX,
            context="efficiency_opt_llm",
        )
        if response is None:
            process_audit_llm_calls_total.labels(
                agent="efficiency_optimizer", result="failed",
            ).inc()
            return None

        raw = response.content if hasattr(response, "content") else str(response)
        data = safe_extract_json(raw)
        if data is None:
            process_audit_llm_calls_total.labels(
                agent="efficiency_optimizer", result="parse_error",
            ).inc()
            return None

        process_audit_llm_calls_total.labels(
            agent="efficiency_optimizer", result="success",
        ).inc()

        priority = str(data.get("priority", "LOW"))
        if priority not in _PRIORITIES:
            priority = "LOW"

        return ImprovementProposal(
            proposal_id=str(uuid.uuid4()),
            title=str(data.get("title", ""))[:100],
            description=str(data.get("description", "")),
            target_file=str(data.get("target_file", "")),
            priority=priority,
            estimated_token_saving_pct=min(100.0, max(0.0, float(data.get("estimated_token_saving_pct", 0.0)))),
            confidence=min(1.0, max(0.0, float(data.get("confidence", 0.0)))),
        )

    def _template_proposal(self, bottleneck: dict[str, Any]) -> ImprovementProposal:
        bn_stage = bottleneck.get("bottleneck_stage", "unknown")
        fr_pct = bottleneck.get("failure_rate_pct", 0.0)
        avg_s3 = bottleneck.get("avg_stage3_s", 0.0)

        if bn_stage == "scraping":
            return ImprovementProposal(
                proposal_id=str(uuid.uuid4()),
                title="Add rate-limit backoff to scraping stage",
                description=(
                    f"Scraping stage averages {bottleneck.get('avg_stage1_s', 0)}s. "
                    "Add exponential backoff and parallelize independent portal requests. "
                    "Target: reduce scraping time by 40%."
                ),
                target_file="scrapers/portal_scout.py",
                priority="HIGH",
                estimated_token_saving_pct=0.0,
                confidence=0.7,
            )
        elif bn_stage == "llm_synthesis":
            return ImprovementProposal(
                proposal_id=str(uuid.uuid4()),
                title="Cache LLM synthesis outputs by survey_no+market hash",
                description=(
                    f"LLM synthesis averages {avg_s3}s. "
                    "Many evaluate calls reuse the same IntelPackage. "
                    "Cache the investor brief and deal memo by content hash to avoid regeneration."
                ),
                target_file="crews/evaluate_pipeline.py",
                priority="HIGH",
                estimated_token_saving_pct=max(0.0, min(100.0, 60.0)),
                confidence=0.8,
            )
        elif fr_pct > 20:
            return ImprovementProposal(
                proposal_id=str(uuid.uuid4()),
                title=f"Investigate {fr_pct}% pipeline failure rate",
                description=(
                    f"Pipeline failure rate is {fr_pct}%. "
                    "Review error type distribution in run history. "
                    "Focus on recurring error types."
                ),
                target_file="config/run_logger.py",
                priority="MEDIUM",
                estimated_token_saving_pct=15.0,
                confidence=0.6,
            )
        return _fallback_proposal()
