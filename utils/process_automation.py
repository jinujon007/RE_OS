"""
RE_OS — Process Automation Shared Utilities (Sprint 61)
Retry logic, validation, error types, and bounded execution for all 3 agents.
"""

import os
import time
import random
from typing import Any, Callable, TypeVar
from loguru import logger

T = TypeVar("T")

# ── Configuration ──────────────────────────────────────────────────────────────

LLM_TIMEOUT_S = int(os.environ.get("PROCESS_AUTOMATION_LLM_TIMEOUT_S", "45"))
LLM_RETRY_MAX = int(os.environ.get("PROCESS_AUTOMATION_LLM_RETRY", "2"))
LLM_RETRY_BASE_DELAY_S = float(os.environ.get("PROCESS_AUTOMATION_RETRY_DELAY_S", "1.0"))
HTTP_TIMEOUT_S = int(os.environ.get("PROCESS_AUTOMATION_HTTP_TIMEOUT_S", "10"))
HTTP_RETRY_MAX = int(os.environ.get("PROCESS_AUTOMATION_HTTP_RETRY", "1"))

_THREAD_POOL_MAX_WORKERS = int(os.environ.get("PROCESS_AUTOMATION_POOL_WORKERS", "2"))

# ── Error types ────────────────────────────────────────────────────────────────


class ProcessAutomationError(Exception):
    """Base error for all process automation failures."""


class LLMTimeoutError(ProcessAutomationError):
    """LLM call exceeded timeout."""


class LLMResponseError(ProcessAutomationError):
    """LLM returned unparseable or invalid response."""


class HTTPCallError(ProcessAutomationError):
    """HTTP call (e.g. task creation) failed."""


class ValidationError(ProcessAutomationError):
    """Input data validation failed."""


# ── Retry ──────────────────────────────────────────────────────────────────────


def retry_with_backoff(
    fn: Callable[..., T],
    max_retries: int = LLM_RETRY_MAX,
    base_delay: float = LLM_RETRY_BASE_DELAY_S,
    context: str = "",
) -> T | None:
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                logger.debug(
                    "[Retry] {ctx} attempt {n}/{max} failed: {err} — retrying in {d:.1f}s",
                    ctx=context or "?", n=attempt + 1, max=max_retries + 1,
                    err=str(exc)[:100], d=delay,
                )
                time.sleep(delay)
            else:
                logger.warning(
                    "[Retry] {ctx} exhausted {n} attempts: {err}",
                    ctx=context or "?", n=max_retries + 1, err=str(exc)[:200],
                )
                return None
    return None


# ── Validation ─────────────────────────────────────────────────────────────────


def validate_bottleneck_report(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        errors.append("bottleneck_report must be a dict")
        return errors
    stage = data.get("bottleneck_stage", "")
    valid_stages = {"scraping", "llm_synthesis", "none", ""}
    if stage not in valid_stages:
        errors.append(f"Invalid bottleneck_stage: {stage!r}")
    for field in ("avg_stage1_s", "avg_stage2_s", "avg_stage3_s", "failure_rate_pct"):
        val = data.get(field)
        if val is not None and not isinstance(val, (int, float)):
            errors.append(f"{field} must be numeric, got {type(val).__name__}")
    return errors


def validate_proposal_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        errors.append("proposal must be a dict")
        return errors
    priority = data.get("priority", "")
    if priority and priority not in ("HIGH", "MEDIUM", "LOW"):
        errors.append(f"Invalid priority: {priority!r}")
    title = data.get("title", "")
    if title and len(title) > 100:
        errors.append(f"title exceeds 100 chars ({len(title)})")
    return errors


# ── Bounded thread pool execution ──────────────────────────────────────────────


def run_with_timeout(
    fn: Callable[..., T],
    timeout_s: float = LLM_TIMEOUT_S,
    context: str = "",
) -> T | None:
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TimeoutError
    with ThreadPoolExecutor(max_workers=_THREAD_POOL_MAX_WORKERS) as pool:
        future = pool.submit(fn)
        try:
            return future.result(timeout=timeout_s)
        except _TimeoutError:
            logger.warning("[Exec] {ctx} timed out after {t}s", ctx=context, t=timeout_s)
            return None
        except Exception as exc:
            logger.warning("[Exec] {ctx} failed: {err}", ctx=context, err=str(exc)[:200])
            return None


# ── JSON extraction with size bounds ───────────────────────────────────────────

_LLM_RESPONSE_MAX_BYTES = int(os.environ.get("PROCESS_AUTOMATION_RESPONSE_MAX", "100000"))
_JSON_EXTRACT_MAX_CHARS = int(os.environ.get("PROCESS_AUTOMATION_JSON_EXTRACT_MAX", "20000"))


def safe_extract_json(raw: str, max_chars: int = _JSON_EXTRACT_MAX_CHARS) -> dict[str, Any] | None:
    import json
    if not raw or len(raw) > _LLM_RESPONSE_MAX_BYTES:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    truncated = raw[:max_chars]
    try:
        start = truncated.index("{")
        end = truncated.rindex("}") + 1
        if end - start > max_chars:
            return None
        return json.loads(truncated[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
