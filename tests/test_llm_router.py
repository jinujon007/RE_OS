"""
Tests for config/llm_router.py

Covers: _exclude, _is_excluded, _clear_excluded, get_heavy_llm (all provider
fallback paths), get_analysis_llm, get_light_llm, get_router_status structure.

Strategy: monkeypatch module-level key constants so the router thinks a provider
is available/unavailable without touching the real environment. LLM is replaced
with a MagicMock that records constructor calls.
"""

import pytest
import config.llm_router as r

pytestmark = pytest.mark.unit


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_excluded():
    """Ensure _EXCLUDED + _CIRCUIT_STATE are clean before and after every test."""
    r._clear_excluded()
    r._reset_circuit_state()
    yield
    r._clear_excluded()
    r._reset_circuit_state()


@pytest.fixture
def mock_llm(monkeypatch):
    """Replace crewai.LLM with a MagicMock so no real HTTP calls happen."""
    from unittest.mock import MagicMock

    mock = MagicMock()
    monkeypatch.setattr(r, "LLM", mock)
    return mock


# ── Exclusion helpers ──────────────────────────────────────────────────────────


def test_exclude_adds_provider():
    r._exclude("cerebras")
    assert r._is_excluded("cerebras")


def test_is_excluded_false_for_unknown():
    assert not r._is_excluded("unknown_provider")


def test_clear_excluded_empties_set():
    r._exclude("groq")
    r._exclude("nvidia")
    r._clear_excluded()
    assert not r._is_excluded("groq")
    assert not r._is_excluded("nvidia")


def test_exclude_multiple_providers():
    r._exclude("groq")
    r._exclude("cerebras")
    assert r._is_excluded("groq")
    assert r._is_excluded("cerebras")
    assert not r._is_excluded("ollama")


# ── get_heavy_llm ──────────────────────────────────────────────────────────────


def test_heavy_uses_groq_when_key_present(monkeypatch, mock_llm):
    monkeypatch.setattr(r, "GROQ_API_KEY", "test-groq-key")
    r.get_heavy_llm()
    call_kwargs = mock_llm.call_args
    assert "groq/" in call_kwargs.kwargs.get("model", "") or (
        call_kwargs.args and "groq/" in call_kwargs.args[0]
    )


def test_heavy_falls_back_to_gemini_when_groq_excluded(monkeypatch, mock_llm):
    monkeypatch.setattr(r, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(r, "GEMINI_API_KEY", "test-gemini-key")
    r._exclude("groq")
    r.get_heavy_llm()
    call_kwargs = mock_llm.call_args
    model = call_kwargs.kwargs.get("model", "") or (
        call_kwargs.args[0] if call_kwargs.args else ""
    )
    assert "gemini" in model.lower()


def test_heavy_falls_back_to_nvidia_when_groq_gemini_excluded(monkeypatch, mock_llm):
    monkeypatch.setattr(r, "GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(r, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(r, "NVIDIA_API_KEY", "test-nvidia-key")
    r._exclude("groq")
    r._exclude("gemini_flash")  # T-314: split key
    r.get_heavy_llm()
    call_kwargs = mock_llm.call_args
    model = call_kwargs.kwargs.get("model", "") or (
        call_kwargs.args[0] if call_kwargs.args else ""
    )
    assert "nvidia" in model.lower() or "openai/" in model.lower()


def test_heavy_falls_back_to_openrouter(monkeypatch, mock_llm):
    monkeypatch.setattr(r, "GROQ_API_KEY", "")
    monkeypatch.setattr(r, "GEMINI_API_KEY", "")
    monkeypatch.setattr(r, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(r, "SAMBANOVA_API_KEY", "")  # skip SambaNova
    monkeypatch.setattr(r, "OPENROUTER_API_KEY", "test-or-key")
    r.get_heavy_llm()
    call_kwargs = mock_llm.call_args
    model = call_kwargs.kwargs.get("model", "") or (
        call_kwargs.args[0] if call_kwargs.args else ""
    )
    assert "openrouter" in model.lower()


def test_heavy_falls_back_to_ollama_when_no_keys(monkeypatch, mock_llm):
    monkeypatch.setattr(r, "GROQ_API_KEY", "")
    monkeypatch.setattr(r, "GEMINI_API_KEY", "")
    monkeypatch.setattr(r, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(r, "SAMBANOVA_API_KEY", "")  # skip SambaNova
    monkeypatch.setattr(r, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(r, "CLOUDFLARE_API_KEY", "")  # skip Cloudflare
    r.get_heavy_llm()
    call_kwargs = mock_llm.call_args
    model = call_kwargs.kwargs.get("model", "") or (
        call_kwargs.args[0] if call_kwargs.args else ""
    )
    assert "ollama" in model.lower()


# ── get_analysis_llm ───────────────────────────────────────────────────────────


def test_analysis_uses_cerebras_primary(monkeypatch, mock_llm):
    monkeypatch.setattr(r, "CEREBRAS_API_KEY", "test-cerebras-key")
    r.get_analysis_llm()
    call_kwargs = mock_llm.call_args
    model = call_kwargs.kwargs.get("model", "") or (
        call_kwargs.args[0] if call_kwargs.args else ""
    )
    # T-312: Cerebras model changed from llama3.1-8b to gpt-oss-120b
    assert (
        "cerebras" in model.lower()
        or "llama3" in model.lower()
        or "gpt-oss" in model.lower()
    )


def test_analysis_falls_back_to_groq_when_cerebras_excluded(monkeypatch, mock_llm):
    monkeypatch.setattr(r, "CEREBRAS_API_KEY", "test-cerebras-key")
    monkeypatch.setattr(r, "GROQ_API_KEY", "test-groq-key")
    r._exclude("cerebras")
    r.get_analysis_llm()
    call_kwargs = mock_llm.call_args
    model = call_kwargs.kwargs.get("model", "") or (
        call_kwargs.args[0] if call_kwargs.args else ""
    )
    assert "groq/" in model


def test_analysis_falls_back_to_ollama_when_all_excluded(monkeypatch, mock_llm):
    monkeypatch.setattr(r, "CEREBRAS_API_KEY", "")
    monkeypatch.setattr(r, "GROQ_API_KEY", "")
    monkeypatch.setattr(r, "GEMINI_API_KEY", "")
    monkeypatch.setattr(r, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(r, "SAMBANOVA_API_KEY", "")  # skip SambaNova
    monkeypatch.setattr(r, "CLOUDFLARE_API_KEY", "")  # skip Cloudflare
    r.get_analysis_llm()
    call_kwargs = mock_llm.call_args
    model = call_kwargs.kwargs.get("model", "") or (
        call_kwargs.args[0] if call_kwargs.args else ""
    )
    assert "ollama" in model.lower()


# ── get_light_llm ──────────────────────────────────────────────────────────────


def test_light_uses_cerebras_primary(monkeypatch, mock_llm):
    monkeypatch.setattr(r, "CEREBRAS_API_KEY", "test-cerebras-key")
    r.get_light_llm()
    call_kwargs = mock_llm.call_args
    model = call_kwargs.kwargs.get("model", "") or (
        call_kwargs.args[0] if call_kwargs.args else ""
    )
    # T-312: Cerebras model changed from llama3.1-8b to gpt-oss-120b
    assert (
        "cerebras" in model.lower()
        or "llama3" in model.lower()
        or "gpt-oss" in model.lower()
    )


def test_light_falls_back_to_gemini_when_cerebras_excluded(monkeypatch, mock_llm):
    monkeypatch.setattr(r, "CEREBRAS_API_KEY", "")
    monkeypatch.setattr(r, "GEMINI_API_KEY", "test-gemini-key")
    r.get_light_llm()
    call_kwargs = mock_llm.call_args
    model = call_kwargs.kwargs.get("model", "") or (
        call_kwargs.args[0] if call_kwargs.args else ""
    )
    assert "gemini" in model.lower()


# ── get_router_status ──────────────────────────────────────────────────────────


def test_router_status_has_required_keys(monkeypatch):
    monkeypatch.setattr(r, "GROQ_API_KEY", "key")
    monkeypatch.setattr(r, "CEREBRAS_API_KEY", "key")
    monkeypatch.setattr(r, "GEMINI_API_KEY", "key")
    monkeypatch.setattr(r, "NVIDIA_API_KEY", "key")
    monkeypatch.setattr(r, "OPENROUTER_API_KEY", "key")
    status = r.get_router_status()
    assert "providers" in status
    assert "excluded" in status
    assert "heavy_chain" in status
    assert "analysis_chain" in status
    assert "light_chain" in status


def test_router_status_ollama_always_true(monkeypatch):
    monkeypatch.setattr(r, "GROQ_API_KEY", "")
    status = r.get_router_status()
    assert status["providers"]["ollama"] is True
