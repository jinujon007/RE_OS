"""
RE_OS — Log Analyst Agent (T-1008, Sprint 61)
Reads run_history.jsonl, detects pipeline bottlenecks, generates BottleneckReport.
ANALYSIS LLM tier. Falls back to pure data analysis when LLM unavailable.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4
from loguru import logger

from utils.log_analyzer import PipelineRunAnalyzer
from utils.process_automation import (
    LLMTimeoutError,
    LLMResponseError,
    ValidationError,
    retry_with_backoff,
    run_with_timeout,
    safe_extract_json,
    LLM_TIMEOUT_S as _LLM_TIMEOUT,
    LLM_RETRY_MAX,
)
from config.metrics import (
    process_audit_reports_total,
    process_audit_bottlenecks_total,
    process_audit_llm_calls_total,
)

__all__ = [
    "BottleneckReport",
    "StageDurationTool",
    "FailureRateTool",
    "BottleneckFinderTool",
    "LogAnalystAgent",
]

_LLM_IMPORTED = False
_LLM_LOCK = Lock()
try:
    from config.llm_router import get_analysis_llm as _get_analysis_llm

    _LLM_IMPORTED = True
except ImportError:
    logger.warning(
        "[LogAnalyst] config.llm_router not available — will use fallback only"
    )

_MIN_RUNS_FOR_BOTTLENECK = 10


@dataclass
class BottleneckReport:
    report_id: str = ""
    report_date: str = ""
    bottleneck_stage: str = ""
    bottleneck_reason: str = ""
    avg_stage1_s: float = 0.0
    avg_stage2_s: float = 0.0
    avg_stage3_s: float = 0.0
    failure_rate_pct: float = 0.0
    top_finding: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def empty() -> "BottleneckReport":
        return BottleneckReport(
            report_id=str(uuid4()),
            report_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            bottleneck_stage="none",
            bottleneck_reason="No data available.",
            top_finding="Insufficient data to generate report.",
            recommendation="Run the pipeline at least 3 times to collect baseline data.",
        )


class StageDurationTool:
    name = "StageDurationTool"
    description = "Get per-stage durations for the last N pipeline runs."

    def __init__(self, analyzer: PipelineRunAnalyzer | None = None):
        self._analyzer = analyzer or PipelineRunAnalyzer()

    def run(self, n_runs: int = 10) -> str:
        n = max(1, min(n_runs, 1000))
        durations = self._analyzer.get_stage_durations(n)
        return json.dumps(durations, default=str)


class FailureRateTool:
    name = "FailureRateTool"
    description = "Get pipeline failure rate over the last N runs."

    def __init__(self, analyzer: PipelineRunAnalyzer | None = None):
        self._analyzer = analyzer or PipelineRunAnalyzer()

    def run(self, n_runs: int = 20) -> str:
        n = max(1, min(n_runs, 1000))
        rate = self._analyzer.get_failure_rate(n)
        return json.dumps(rate, default=str)


class BottleneckFinderTool:
    name = "BottleneckFinderTool"
    description = "Find pipeline bottleneck stage from last N runs."

    def __init__(self, analyzer: PipelineRunAnalyzer | None = None):
        self._analyzer = analyzer or PipelineRunAnalyzer()

    def run(self, n_runs: int = 10) -> str:
        n = max(1, min(n_runs, 1000))
        bn = self._analyzer.find_bottleneck(n)
        return json.dumps(bn or {}, default=str)


_SYSTEM_PROMPT_LOG_ANALYST = (
    "You are a Log Analyst responsible for identifying pipeline bottlenecks in RE_OS. "
    "You receive stage timing data, bottleneck analysis, and failure rates. "
    "Produce concise, actionable findings. Be specific about which stage is slow. "
    "If data is insufficient, say so clearly.\n\n"
    "You MUST return valid JSON only, with exactly these keys:\n"
    '  "top_finding": str (≤200 chars),\n'
    '  "recommendation": str (≤300 chars).\n'
    "No markdown, no code fences, no explanatory text outside the JSON."
)


class LogAnalystAgent:
    _CORRELATION_PREFIX = "log_analyst"

    def __init__(self, analyzer: PipelineRunAnalyzer | None = None):
        self._analyzer = analyzer or PipelineRunAnalyzer()
        self._stage_tool = StageDurationTool(self._analyzer)
        self._failure_tool = FailureRateTool(self._analyzer)
        self._bottleneck_tool = BottleneckFinderTool(self._analyzer)
        self._correlation_id = f"{self._CORRELATION_PREFIX}_{uuid4().hex[:8]}"

    def _build_analysis(self) -> BottleneckReport:
        durations = self._analyzer.get_stage_durations(20)
        valid = [d for d in durations if d.get("total_duration_s", 0) > 0]
        n_valid = len(valid)
        if not valid:
            return BottleneckReport.empty()

        avg_s1 = sum(d["stage1_duration_s"] for d in valid) / n_valid
        avg_s2 = sum(d["stage2_duration_s"] for d in valid) / n_valid
        avg_s3 = sum(d["stage3_duration_s"] for d in valid) / n_valid
        failure_rate = self._analyzer.get_failure_rate(20)
        bn = self._analyzer.find_bottleneck(10)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        report = BottleneckReport(
            report_id=str(uuid4()),
            report_date=today,
            bottleneck_stage=bn["bottleneck"] if bn else "none",
            bottleneck_reason=(
                bn["recommendation"] if bn else "No significant bottleneck detected."
            ),
            avg_stage1_s=round(avg_s1, 1),
            avg_stage2_s=round(avg_s2, 1),
            avg_stage3_s=round(avg_s3, 1),
            failure_rate_pct=failure_rate["failure_rate_pct"],
            top_finding="",
            recommendation="",
        )

        if n_valid < _MIN_RUNS_FOR_BOTTLENECK:
            report.top_finding = (
                f"Insufficient run history — only {n_valid} runs with timing data "
                f"(need ≥{_MIN_RUNS_FOR_BOTTLENECK})"
            )
            report.recommendation = (
                f"Run the pipeline {_MIN_RUNS_FOR_BOTTLENECK}+ times before "
                "Log Analyst can identify patterns."
            )
        elif bn:
            report.top_finding = (
                f"Bottleneck: {bn['bottleneck']} (avg {bn['avg_s']:.1f}s per run)"
            )
            report.recommendation = bn["recommendation"]
            process_audit_bottlenecks_total.labels(stage=bn["bottleneck"]).inc()
        else:
            report.top_finding = (
                "No bottleneck detected — stage durations are balanced."
            )
            report.recommendation = "Continue monitoring. Re-run analysis weekly."

        if failure_rate["failure_rate_pct"] > 20:
            report.top_finding += (
                f" | High failure rate: {failure_rate['failure_rate_pct']:.1f}%"
            )
            report.recommendation += (
                f" Investigate the {failure_rate['failed']} failed runs first."
            )

        return report

    def _try_llm_analysis(self) -> BottleneckReport | None:
        if not _LLM_IMPORTED:
            return None
        try:
            llm = _get_analysis_llm()
        except Exception as exc:
            logger.debug("[{}] LLM unavailable: {}", self._correlation_id, exc)
            return None

        durations_json = self._stage_tool.run(20)
        bn_json = self._bottleneck_tool.run(10)
        fr_json = self._failure_tool.run(20)

        def _do_llm_call():
            return llm.invoke(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT_LOG_ANALYST},
                    {
                        "role": "user",
                        "content": (
                            "You are a pipeline reliability analyst. Review the following "
                            "run data and produce a concise bottleneck report.\n\n"
                            f"Stage Durations (last 20 runs): {durations_json}\n\n"
                            f"Bottleneck Analysis: {bn_json}\n\n"
                            f"Failure Rate: {fr_json}\n\n"
                            "Return JSON only with keys: top_finding (≤200 chars), "
                            "recommendation (≤300 chars). If no bottleneck found, "
                            "set top_finding to 'Pipeline running within normal parameters.'"
                        ),
                    },
                ]
            )

        response = retry_with_backoff(
            lambda: run_with_timeout(_do_llm_call, _LLM_TIMEOUT, "log_analyst_llm"),
            max_retries=LLM_RETRY_MAX,
            context="log_analyst_llm",
        )
        if response is None:
            process_audit_llm_calls_total.labels(
                agent="log_analyst",
                result="failed",
            ).inc()
            return None

        raw = ""
        if hasattr(response, "content"):
            raw = response.content or ""
        elif isinstance(response, str):
            raw = response
        else:
            raw = str(response)

        data = safe_extract_json(raw)
        if data is None:
            process_audit_llm_calls_total.labels(
                agent="log_analyst",
                result="parse_error",
            ).inc()
            return None

        process_audit_llm_calls_total.labels(
            agent="log_analyst",
            result="success",
        ).inc()

        base = self._build_analysis()
        base.top_finding = data.get("top_finding", base.top_finding)
        base.recommendation = data.get("recommendation", base.recommendation)
        return base

    def run(self, n_runs: int = 10) -> dict[str, Any]:
        n = max(1, min(n_runs, 1000))
        report = self._build_analysis()
        if _LLM_IMPORTED:
            try:
                llm_report = self._try_llm_analysis()
                if llm_report:
                    report = llm_report
            except Exception as exc:
                logger.warning(
                    "[{}] LLM enrichment failed: {}",
                    self._correlation_id,
                    exc,
                )

        process_audit_reports_total.labels(
            agent="log_analyst", method="llm" if _LLM_IMPORTED else "fallback"
        ).inc()
        logger.info(
            '[{}] Report — bottleneck={}, failure_rate={}%, finding="{}"',
            self._correlation_id,
            report.bottleneck_stage,
            report.failure_rate_pct,
            report.top_finding[:80],
        )
        return {
            "status": "done",
            "report": report.to_dict(),
            "correlation_id": self._correlation_id,
        }
