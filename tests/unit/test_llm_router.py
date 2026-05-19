"""
Unit tests for config/llm_router.py

Strategy: patch crewai.LLM (no actual API calls), patch settings constants
to control which providers appear available, then assert the right model
string is passed to LLM().
"""
import importlib
import sys
from unittest.mock import MagicMock, patch, call


def _fresh_router(monkeypatch, *, groq="", cerebras="", gemini="", nvidia="", openrouter=""):
    """
    Return a freshly-imported llm_router with API keys set as specified.
    Patches crewai.LLM to a MagicMock so no HTTP calls are made.
    """
    mock_llm_cls = MagicMock()

    # Patch settings keys inside the router module after import
    patches = {
        "config.llm_router.GROQ_API_KEY": groq,
        "config.llm_router.CEREBRAS_API_KEY": cerebras,
        "config.llm_router.GEMINI_API_KEY": gemini,
        "config.llm_router.NVIDIA_API_KEY": nvidia,
        "config.llm_router.OPENROUTER_API_KEY": openrouter,
        "config.llm_router.LLM": mock_llm_cls,
    }
    return mock_llm_cls, patches


# ── get_heavy_llm ─────────────────────────────────────────────────────────────

def test_heavy_uses_groq_when_key_set():
    mock_llm_cls = MagicMock()
    with patch.multiple(
        "config.llm_router",
        GROQ_API_KEY="test-groq",
        CEREBRAS_API_KEY="",
        GEMINI_API_KEY="",
        NVIDIA_API_KEY="",
        OPENROUTER_API_KEY="",
        LLM=mock_llm_cls,
        _EXCLUDED=set(),
    ):
        import config.llm_router as router
        router.get_heavy_llm()

    mock_llm_cls.assert_called_once()
    model_arg = mock_llm_cls.call_args[1]["model"]
    assert model_arg.startswith("groq/"), f"Expected groq/ model, got: {model_arg}"


def test_heavy_falls_back_to_gemini_when_groq_excluded():
    mock_llm_cls = MagicMock()
    with patch.multiple(
        "config.llm_router",
        GROQ_API_KEY="test-groq",
        GEMINI_API_KEY="test-gemini",
        NVIDIA_API_KEY="",
        OPENROUTER_API_KEY="",
        LLM=mock_llm_cls,
        _EXCLUDED={"groq"},
    ):
        import config.llm_router as router
        router.get_heavy_llm()

    mock_llm_cls.assert_called_once()
    model_arg = mock_llm_cls.call_args[1]["model"]
    assert "gemini" in model_arg.lower(), f"Expected gemini model, got: {model_arg}"


def test_heavy_falls_back_to_ollama_when_all_excluded():
    mock_llm_cls = MagicMock()
    with patch.multiple(
        "config.llm_router",
        GROQ_API_KEY="test-groq",
        GEMINI_API_KEY="test-gemini",
        NVIDIA_API_KEY="test-nvidia",
        OPENROUTER_API_KEY="test-openrouter",
        LLM=mock_llm_cls,
        _EXCLUDED={"groq", "gemini", "nvidia", "openrouter"},
    ):
        import config.llm_router as router
        router.get_heavy_llm()

    mock_llm_cls.assert_called_once()
    model_arg = mock_llm_cls.call_args[1]["model"]
    assert model_arg.startswith("ollama/"), f"Expected ollama/ model, got: {model_arg}"


def test_heavy_uses_ollama_when_no_keys():
    mock_llm_cls = MagicMock()
    with patch.multiple(
        "config.llm_router",
        GROQ_API_KEY="",
        GEMINI_API_KEY="",
        NVIDIA_API_KEY="",
        OPENROUTER_API_KEY="",
        LLM=mock_llm_cls,
        _EXCLUDED=set(),
    ):
        import config.llm_router as router
        router.get_heavy_llm()

    mock_llm_cls.assert_called_once()
    model_arg = mock_llm_cls.call_args[1]["model"]
    assert model_arg.startswith("ollama/"), f"Expected ollama/ model, got: {model_arg}"


# ── get_analysis_llm ──────────────────────────────────────────────────────────

def test_analysis_uses_cerebras_when_key_set():
    mock_llm_cls = MagicMock()
    with patch.multiple(
        "config.llm_router",
        CEREBRAS_API_KEY="test-cerebras",
        GROQ_API_KEY="",
        GEMINI_API_KEY="",
        NVIDIA_API_KEY="",
        LLM=mock_llm_cls,
        _EXCLUDED=set(),
    ):
        import config.llm_router as router
        router.get_analysis_llm()

    mock_llm_cls.assert_called_once()
    # Cerebras uses openai/ prefix in LiteLLM
    model_arg = mock_llm_cls.call_args[1]["model"]
    assert model_arg.startswith("openai/"), f"Expected openai/ Cerebras model, got: {model_arg}"
    base_url = mock_llm_cls.call_args[1].get("base_url", "")
    assert "cerebras" in base_url, f"Expected cerebras base_url, got: {base_url}"


def test_analysis_falls_back_to_ollama_when_all_excluded():
    mock_llm_cls = MagicMock()
    with patch.multiple(
        "config.llm_router",
        CEREBRAS_API_KEY="test-cerebras",
        GROQ_API_KEY="test-groq",
        GEMINI_API_KEY="test-gemini",
        NVIDIA_API_KEY="test-nvidia",
        LLM=mock_llm_cls,
        _EXCLUDED={"cerebras", "groq", "gemini", "nvidia"},
    ):
        import config.llm_router as router
        router.get_analysis_llm()

    mock_llm_cls.assert_called_once()
    model_arg = mock_llm_cls.call_args[1]["model"]
    assert model_arg.startswith("ollama/"), f"Expected ollama/ fallback, got: {model_arg}"


# ── get_light_llm ─────────────────────────────────────────────────────────────

def test_light_uses_cerebras_when_key_set():
    mock_llm_cls = MagicMock()
    with patch.multiple(
        "config.llm_router",
        CEREBRAS_API_KEY="test-cerebras",
        GEMINI_API_KEY="",
        NVIDIA_API_KEY="",
        LLM=mock_llm_cls,
        _EXCLUDED=set(),
    ):
        import config.llm_router as router
        router.get_light_llm()

    mock_llm_cls.assert_called_once()
    base_url = mock_llm_cls.call_args[1].get("base_url", "")
    assert "cerebras" in base_url


def test_light_falls_back_to_ollama_when_no_keys():
    mock_llm_cls = MagicMock()
    with patch.multiple(
        "config.llm_router",
        CEREBRAS_API_KEY="",
        GEMINI_API_KEY="",
        NVIDIA_API_KEY="",
        LLM=mock_llm_cls,
        _EXCLUDED=set(),
    ):
        import config.llm_router as router
        router.get_light_llm()

    mock_llm_cls.assert_called_once()
    model_arg = mock_llm_cls.call_args[1]["model"]
    assert model_arg.startswith("ollama/"), f"Expected ollama/ fallback, got: {model_arg}"
