"""
T-303 — Intel output parsing tests.

Tests _extract_report_body() — the extracted helper that decides whether to use
the CEO output or fall back to analyst output. No LLM calls.
"""

from unittest.mock import MagicMock

import pytest

from crews.market_intel_crew import _extract_report_body


def _make_result(analyst_raw: str, ceo_raw: str):
    """Build a mock crew result with two task outputs."""
    result = MagicMock()
    analyst_task = MagicMock()
    analyst_task.raw = analyst_raw
    ceo_task = MagicMock()
    ceo_task.raw = ceo_raw
    result.tasks_output = [analyst_task, ceo_task]
    result.raw = ceo_raw
    return result


# ── CEO output long enough → use it ───────────────────────────────────────────

def test_valid_ceo_output_used_as_report_body():
    ceo_text = "A" * 150
    result = _make_result("analyst brief", ceo_text)
    analyst_raw, ceo_raw, report_body, ceo_section = _extract_report_body(result)
    assert report_body == ceo_text
    assert ceo_section == ""


def test_valid_ceo_output_exact_100_chars():
    ceo_text = "X" * 100
    result = _make_result("analyst brief", ceo_text)
    _, _, report_body, ceo_section = _extract_report_body(result)
    assert report_body == ceo_text
    assert ceo_section == ""


def test_analyst_raw_correct_with_valid_ceo():
    result = _make_result("The analyst says Devanahalli PSF 9666.", "CEO says: buy Devanahalli now at 9666 PSF, 18% above GV. Strong absorption. Full go.")
    analyst_raw, _, _, _ = _extract_report_body(result)
    assert analyst_raw == "The analyst says Devanahalli PSF 9666."


# ── CEO output too short → fall back to analyst ───────────────────────────────

def test_short_ceo_output_triggers_fallback():
    result = _make_result("analyst brief here", "X" * 99)
    _, _, report_body, ceo_section = _extract_report_body(result)
    assert report_body == "analyst brief here"
    assert "unavailable" in ceo_section


def test_empty_ceo_output_triggers_fallback():
    result = _make_result("full analyst report " * 5, "")
    _, _, report_body, ceo_section = _extract_report_body(result)
    assert report_body.startswith("full analyst report")
    assert "unavailable" in ceo_section


def test_whitespace_only_ceo_triggers_fallback():
    result = _make_result("analyst output", "   \n\t  ")
    _, _, report_body, ceo_section = _extract_report_body(result)
    assert report_body == "analyst output"
    assert ceo_section != ""


# ── Only one task output (analyst only) ───────────────────────────────────────

def test_single_task_output_uses_analyst_as_fallback():
    result = MagicMock()
    task = MagicMock()
    task.raw = "analyst only output — short"
    result.tasks_output = [task]
    result.raw = "analyst only output — short"
    _, _, report_body, ceo_section = _extract_report_body(result)
    assert "unavailable" in ceo_section


# ── No tasks_output attribute ─────────────────────────────────────────────────

def test_no_tasks_output_attr_uses_raw():
    result = MagicMock(spec=[])  # no tasks_output attribute
    result.raw = "C" * 150
    _, ceo_raw, report_body, ceo_section = _extract_report_body(result)
    assert report_body == "C" * 150
    assert ceo_section == ""


def test_tasks_output_none_falls_back_to_raw():
    result = MagicMock()
    result.tasks_output = None
    result.raw = "D" * 150
    _, _, report_body, ceo_section = _extract_report_body(result)
    assert report_body == "D" * 150
    assert ceo_section == ""


# ── Return types ──────────────────────────────────────────────────────────────

def test_returns_four_tuple():
    result = _make_result("analyst", "CEO output with enough content to be valid here " * 3)
    out = _extract_report_body(result)
    assert len(out) == 4


def test_all_strings_returned():
    result = _make_result("analyst brief", "CEO " * 30)
    analyst_raw, ceo_raw, report_body, ceo_section = _extract_report_body(result)
    for val in (analyst_raw, ceo_raw, report_body, ceo_section):
        assert isinstance(val, str)


# ── Whitespace handling ───────────────────────────────────────────────────────

def test_ceo_output_with_leading_whitespace_still_valid():
    ceo_text = "\n\n" + "Valid CEO synthesis content " * 5
    result = _make_result("analyst", ceo_text)
    _, _, report_body, ceo_section = _extract_report_body(result)
    assert report_body == ceo_text
    assert ceo_section == ""


def test_exactly_99_chars_is_fallback():
    result = _make_result("analyst fallback", "X" * 99)
    _, _, report_body, ceo_section = _extract_report_body(result)
    assert report_body == "analyst fallback"
    assert ceo_section != ""
