"""
Tests for crews/market_intel_crew.py — pure helper functions + crew builders.

Covers: _detect_rate_limited_provider (all known providers + generic rate-limit
messages + None case), _log_event structure, _banner output, _header output,
_build_data_crew, _build_intel_crew (uses mocked crewai from conftest),
create_ceo_agent, create_analyst_agent.
"""

import io
import sys
from unittest.mock import MagicMock, patch

import pytest


# ── Import helpers without triggering Crew-level side effects ──────────────────
# conftest.py has already stubbed crewai, litellm, playwright, sqlalchemy.

from crews.market_intel_crew import (
    _detect_rate_limited_provider,
    _log_event,
    _banner,
    _header,
    _build_data_crew,
    _build_intel_crew,
)
from agents import create_ceo_agent, create_analyst_agent

import config.llm_router as r


# ── _detect_rate_limited_provider ──────────────────────────────────────────────


def test_detect_cerebras_by_attr():
    exc = MagicMock()
    exc.llm_provider = "cerebras"
    assert _detect_rate_limited_provider(exc) == "cerebras"


def test_detect_groq_by_attr():
    exc = MagicMock()
    exc.llm_provider = "groq"
    assert _detect_rate_limited_provider(exc) == "groq"


def test_detect_gemini_by_attr_google():
    exc = MagicMock()
    exc.llm_provider = "google"
    assert _detect_rate_limited_provider(exc) == "gemini"


def test_detect_nvidia_by_attr():
    exc = MagicMock()
    exc.llm_provider = "nvidia"
    assert _detect_rate_limited_provider(exc) == "nvidia"


def test_detect_openrouter_by_attr():
    exc = MagicMock()
    exc.llm_provider = "openrouter"
    assert _detect_rate_limited_provider(exc) == "openrouter"


def test_detect_cerebras_by_message_quota():
    exc = Exception("token_quota_exceeded for this account")
    exc.llm_provider = None
    assert _detect_rate_limited_provider(exc) == "cerebras"


def test_detect_cerebras_by_message_day():
    exc = Exception("tokens per day limit reached")
    exc.llm_provider = None
    assert _detect_rate_limited_provider(exc) == "cerebras"


def test_detect_groq_by_message():
    exc = Exception("groq API returned 429")
    exc.llm_provider = None
    assert _detect_rate_limited_provider(exc) == "groq"


def test_detect_nvidia_by_message():
    exc = Exception("nvidia endpoint error 404 page not found")
    exc.llm_provider = None
    assert _detect_rate_limited_provider(exc) == "nvidia"


def test_detect_generic_rate_limit_returns_first_active():
    """Generic 'rate limit' message → returns first non-excluded provider."""
    r._clear_excluded()
    exc = Exception("too many requests")
    exc.llm_provider = None
    result = _detect_rate_limited_provider(exc)
    # cerebras is first in the fallback list
    assert result == "cerebras"


def test_detect_generic_skips_excluded():
    """When cerebras is excluded, generic rate-limit returns next provider."""
    r._clear_excluded()
    r._exclude("cerebras")
    exc = Exception("requests per minute limit exceeded")
    exc.llm_provider = None
    result = _detect_rate_limited_provider(exc)
    assert result == "groq"
    r._clear_excluded()


def test_detect_returns_none_for_unrelated_error():
    exc = Exception("some unrelated runtime error with no provider info")
    exc.llm_provider = None
    result = _detect_rate_limited_provider(exc)
    assert result is None


# ── _log_event ─────────────────────────────────────────────────────────────────


def test_log_event_calls_logger(monkeypatch):
    logged = []
    monkeypatch.setattr("crews.market_intel_crew.logger", MagicMock(info=lambda x: logged.append(x)))
    _log_event("run123", "Yelahanka", "stage1", "start")
    assert len(logged) == 1
    payload = logged[0]
    assert payload["run_id"] == "run123"
    assert payload["market"] == "Yelahanka"
    assert payload["stage"] == "stage1"
    assert payload["status"] == "start"


def test_log_event_includes_extra_fields(monkeypatch):
    logged = []
    monkeypatch.setattr("crews.market_intel_crew.logger", MagicMock(info=lambda x: logged.append(x)))
    _log_event("run123", "Hebbal", "stage2", "done", projects=42)
    payload = logged[0]
    assert payload["projects"] == 42


def test_log_event_event_key_is_pipeline_stage(monkeypatch):
    logged = []
    monkeypatch.setattr("crews.market_intel_crew.logger", MagicMock(info=lambda x: logged.append(x)))
    _log_event("x", "Devanahalli", "s3", "ok")
    assert logged[0]["event"] == "pipeline_stage"


# ── _banner ────────────────────────────────────────────────────────────────────


def test_banner_prints_stage_and_description(capsys):
    _banner("STAGE 1", "Data Crew — 6 scouts")
    captured = capsys.readouterr()
    assert "STAGE 1" in captured.out
    assert "Data Crew" in captured.out


def test_banner_contains_separator(capsys):
    _banner("S", "desc")
    captured = capsys.readouterr()
    assert "─" in captured.out


# ── _header ────────────────────────────────────────────────────────────────────


def test_header_prints_market(capsys):
    _header("Yelahanka", "run_20260101_120000")
    captured = capsys.readouterr()
    assert "Yelahanka" in captured.out


def test_header_prints_run_id(capsys):
    _header("Hebbal", "run_test_id_42")
    captured = capsys.readouterr()
    assert "run_test_id_42" in captured.out


def test_header_contains_equals_separator(capsys):
    _header("Devanahalli", "run_xyz")
    captured = capsys.readouterr()
    assert "=" in captured.out


# ── _build_data_crew ───────────────────────────────────────────────────────────
# All crewai objects (Task, Crew, Process) are MagicMock from conftest.py,
# so no real agents/LLMs are constructed — only code paths are exercised.


def test_build_data_crew_returns_crew(monkeypatch):
    """_build_data_crew must return a Crew-like object for all 3 markets."""
    result = _build_data_crew("Yelahanka")
    assert result is not None


def test_build_data_crew_devanahalli(monkeypatch):
    result = _build_data_crew("Devanahalli")
    assert result is not None


def test_build_data_crew_hebbal(monkeypatch):
    result = _build_data_crew("Hebbal")
    assert result is not None


def test_build_data_crew_all_three_markets():
    """Ensure all 3 primary markets work without error."""
    for market in ("Yelahanka", "Devanahalli", "Hebbal"):
        assert _build_data_crew(market) is not None


# ── _build_intel_crew ──────────────────────────────────────────────────────────


def test_build_intel_crew_returns_crew():
    stats = {"inserted": 5, "updated": 2, "failed": 0}
    result = _build_intel_crew("Yelahanka", stats)
    assert result is not None


def test_build_intel_crew_zero_stats():
    result = _build_intel_crew("Hebbal", {})
    assert result is not None


def test_build_intel_crew_all_three_markets():
    stats = {"inserted": 5, "updated": 2}
    for market in ("Yelahanka", "Devanahalli", "Hebbal"):
        assert _build_intel_crew(market, stats) is not None


# ── Agent factory functions ────────────────────────────────────────────────────


def test_create_ceo_agent_returns_agent():
    agent = create_ceo_agent()
    assert agent is not None


def test_create_analyst_agent_returns_agent():
    agent = create_analyst_agent()
    assert agent is not None
