"""R3 — Process automation shared utilities tests."""

import pytest
from utils.process_automation import (
    validate_bottleneck_report, validate_proposal_data,
    safe_extract_json, retry_with_backoff,
    ProcessAutomationError, ValidationError,
)

pytestmark = pytest.mark.unit


def test_validate_bottleneck_report_valid():
    data = {
        "bottleneck_stage": "scraping",
        "avg_stage1_s": 65.0,
        "avg_stage2_s": 25.0,
        "avg_stage3_s": 10.0,
        "failure_rate_pct": 5.0,
    }
    errors = validate_bottleneck_report(data)
    assert errors == []


def test_validate_bottleneck_report_invalid_stage():
    errors = validate_bottleneck_report({"bottleneck_stage": "invalid"})
    assert len(errors) > 0


def test_validate_bottleneck_report_non_dict():
    errors = validate_bottleneck_report("not a dict")
    assert len(errors) > 0


def test_validate_proposal_data_valid():
    data = {"priority": "HIGH", "title": "Fix"}
    errors = validate_proposal_data(data)
    assert errors == []


def test_validate_proposal_data_invalid_priority():
    errors = validate_proposal_data({"priority": "URGENT"})
    assert len(errors) > 0


def test_safe_extract_json_oversized():
    big = "{" + "x" * 30000 + "}"
    result = safe_extract_json(big, max_chars=500)
    assert result is None


def test_retry_with_backoff_always_fails():
    calls = []

    def fail():
        calls.append(1)
        msg = f"Attempt {len(calls)} failed"
        raise ValueError(msg)

    result = retry_with_backoff(fail, max_retries=1, base_delay=0.01, context="test")
    assert result is None
    assert len(calls) == 2


def test_retry_with_backoff_succeeds():
    calls = []

    def succeed():
        calls.append(1)
        if len(calls) < 2:
            msg = f"Attempt {len(calls)} failed"
            raise ValueError(msg)
        return "ok"

    result = retry_with_backoff(succeed, max_retries=2, base_delay=0.01, context="test")
    assert result == "ok"
