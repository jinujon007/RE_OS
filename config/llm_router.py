"""
RE_OS — LLM Router (CrewAI 0.80 / LiteLLM)
────────────────────────────────────────────
THREE TIERS — deliberately separated to eliminate TPM conflicts:

  HEAVY (CEO):
    PRIMARY:   Groq  meta-llama/llama-4-scout-17b-16e-instruct  — 30,000 TPM (was 12k)
    BACKUP 1:  Google AI Studio  gemini-2.5-flash                — 250,000 TPM, 20 req/day
    BACKUP 2:  NVIDIA NIM  llama-3.1-405b                       — 40 req/min, no TPM cap
    BACKUP 3:  OpenRouter  llama-3.3-70b:free                   — 50-1000 req/day
    BACKUP 4:  Ollama local

  ANALYSIS (Analyst):
    PRIMARY:   Cerebras  gpt-oss-120b                            — 60-100k TPM, 1M tok/day
    BACKUP 1:  Groq  meta-llama/llama-4-scout-17b-16e-instruct  — 30,000 TPM (shared with CEO)
    BACKUP 2:  Ollama local

  LIGHT (Scraper + Parser + Organizer):
    PRIMARY:   Cerebras  gpt-oss-120b                            — 60-100k TPM, 1M tok/day
    BACKUP 1:  Google AI Studio  gemma-3-27b-it                 — 15,000 TPM, 14,400 req/day
    BACKUP 2:  NVIDIA NIM  llama-3.3-70b                       — 40 req/min
    BACKUP 3:  Ollama local

Why this works:
  - Cerebras handles Light + Analysis: 1M tokens/day, completely separate from Groq budget
  - CEO on Groq Scout: 30k TPM vs old 12k — 2.5x headroom, correct model name
  - Google Gemini backup for CEO: 250k TPM when Groq Scout runs dry
  - No TPM sharing between CEO tier and Light/Analysis tier

Cerebras caveat: 8,192 token context cap. Fine for Light (structured extraction) and Analysis
(DB query results). NOT used for CEO (synthesis prompt can exceed 8k).

Runtime fallback:
  _EXCLUDED is a module-level set populated by market_intel_crew.py when a provider fails
  at runtime. Each get_*_llm() skips any provider in _EXCLUDED, enabling real cross-provider
  fallback without reconstructing agents.
"""

import os
import sys
import threading
from datetime import datetime, UTC
from loguru import logger

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crewai import LLM
from config.settings import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    GROQ_API_KEY,
    GROQ_CEO_MODEL,
    GROQ_ANALYST_MODEL,
    CEREBRAS_API_KEY,
    CEREBRAS_BASE_URL,
    CEREBRAS_MODEL,
    GEMINI_API_KEY,
    GEMINI_CEO_MODEL,
    GEMINI_LIGHT_MODEL,
    NVIDIA_API_KEY,
    NVIDIA_BASE_URL,
    NVIDIA_CEO_MODEL,
    NVIDIA_ANALYST_MODEL,
    NVIDIA_LIGHT_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
)

# Register litellm callback for token tracking
import litellm
def _litellm_usage_callback(kwargs, completion_response, start_time, end_time):
    try:
        api_key = kwargs.get("api_key")
        base_url = kwargs.get("base_url")
        model = kwargs.get("model", "")
        provider = None
        if api_key == CEREBRAS_API_KEY:
            provider = "cerebras"
        elif base_url and "groq" in base_url:
            provider = "groq"
        elif base_url and "nvidia" in base_url:
            provider = "nvidia"
        elif base_url and ("google" in base_url or "aistudio" in base_url):
            provider = "gemini_flash"
            if "gemma" in model.lower():
                provider = "gemini_gemma"
        elif base_url and "openrouter" in base_url:
            provider = "openrouter"
        else:
            provider_part = model.split("/")[0].lower()
            provider_map = {
                "openai": "cerebras",
                "groq": "groq",
                "google": "gemini_flash",
                "nvidia": "nvidia",
                "openrouter": "openrouter",
                "ollama": "ollama"
            }
            provider = provider_map.get(provider_part, provider_part)
        tokens = completion_response.usage.total_tokens if completion_response.usage else 0
        record_token_usage(provider, tokens)
        logger.debug(f"[Router] Token usage recorded: {provider} {tokens}")
    except Exception:
        pass

litellm.success_callback = [_litellm_usage_callback]

# Runtime provider exclusion — thread-safe shared set.
# All reads and writes go through helpers below so parallel market runs don't race.
_EXCLUDED: set = set()
_EXCLUDED_LOCK = threading.Lock()

# DAILY_LIMITS config — limits are per calendar day UTC, reset at midnight
DAILY_LIMITS = {
    "cerebras": 1_000_000,
    "groq": 500_000,
    "gemini_flash": 1_000_000,
    "gemini_gemma": 500_000,
    "nvidia": 2_000_000,
    "openrouter": 500_000
}

# In-process daily token counters — reset automatically at UTC midnight
_daily_counts: dict[str, int] = {}
_last_counts_date: str = None
_counts_lock = threading.Lock()


def _is_excluded(provider: str) -> bool:
    with _EXCLUDED_LOCK:
        return provider in _EXCLUDED


def _exclude(provider: str) -> None:
    with _EXCLUDED_LOCK:
        _EXCLUDED.add(provider)


def _clear_excluded() -> None:
    with _EXCLUDED_LOCK:
        _EXCLUDED.clear()


def _reset_daily_counts_if_needed() -> None:
    """Reset daily token counters at UTC midnight."""
    global _last_counts_date, _daily_counts
    with _counts_lock:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if _last_counts_date != today:
            _daily_counts = {}
            _last_counts_date = today
            logger.info("[Router] Daily token counters reset for {} UTC", today)


def record_token_usage(provider: str, tokens: int) -> None:
    """Record token usage for a provider. Call after each LLM invocation."""
    _reset_daily_counts_if_needed()
    with _counts_lock:
        _daily_counts[provider] = _daily_counts.get(provider, 0) + tokens


def is_near_quota(provider: str) -> bool:
    """Return True if provider has used >90% of daily limit."""
    _reset_daily_counts_if_needed()
    with _counts_lock:
        limit = DAILY_LIMITS.get(provider, 0)
        used = _daily_counts.get(provider, 0)
        return used >= limit * 0.9 if limit > 0 else False


def get_heavy_llm(temperature: float = 0.1) -> LLM:
    """
    CEO Agent — orchestration and final synthesis.
    Groq Scout (30k TPM) primary. Gemini fallback for long-context synthesis.
    """
    if GROQ_API_KEY and not _is_excluded("groq") and not is_near_quota("groq"):
        logger.info(f"[Router] HEAVY tier → Groq {GROQ_CEO_MODEL} (30k TPM)")
        return LLM(
            model=f"groq/{GROQ_CEO_MODEL}",
            api_key=GROQ_API_KEY,
            temperature=temperature,
            max_tokens=4096,
            num_retries=3,
        )
    if GEMINI_API_KEY and not _is_excluded("gemini_flash") and not is_near_quota("gemini_flash"):
        logger.info(
            f"[Router] HEAVY fallback → Google AI Studio {GEMINI_CEO_MODEL} (250k TPM)"
        )
        return LLM(
            model=GEMINI_CEO_MODEL,
            api_key=GEMINI_API_KEY,
            temperature=temperature,
            max_tokens=4096,
            num_retries=3,
        )
    if NVIDIA_API_KEY and not _is_excluded("nvidia") and not is_near_quota("nvidia"):
        logger.info("[Router] HEAVY fallback → NVIDIA NIM 405B")
        return LLM(
            model=f"openai/{NVIDIA_CEO_MODEL}",
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_BASE_URL,
            temperature=temperature,
            max_tokens=4096,
            num_retries=3,
        )
    if OPENROUTER_API_KEY and not _is_excluded("openrouter") and not is_near_quota("openrouter"):
        logger.info("[Router] HEAVY fallback → OpenRouter")
        return LLM(
            model=f"openrouter/{OPENROUTER_MODEL}",
            api_key=OPENROUTER_API_KEY,
            temperature=temperature,
            max_tokens=4096,
            num_retries=3,
        )
    logger.warning("[Router] HEAVY fallback → Ollama (slow, no cloud keys set)")
    return LLM(
        model=f"ollama/{OLLAMA_MODEL}",
        base_url=OLLAMA_BASE_URL,
        temperature=temperature,
    )


def get_analysis_llm(temperature: float = 0.2) -> LLM:
    """
    Analyst Agent — market intelligence synthesis.
    Cerebras primary: 1M tokens/day, 60-100k TPM, completely separate from CEO's Groq budget.
    Groq Scout backup: shares CEO's 30k TPM bucket only if Cerebras unavailable.
    Gemini 2.5 Flash backup: 250k TPM if Groq also exhausted.
    """
    if CEREBRAS_API_KEY and not _is_excluded("cerebras") and not is_near_quota("cerebras"):
        logger.info(f"[Router] ANALYSIS tier → Cerebras {CEREBRAS_MODEL} (1M tok/day)")
        return LLM(
            model=f"openai/{CEREBRAS_MODEL}",
            api_key=CEREBRAS_API_KEY,
            base_url=CEREBRAS_BASE_URL,
            temperature=temperature,
            max_tokens=4096,
            num_retries=3,
        )
    if GROQ_API_KEY and not _is_excluded("groq") and not is_near_quota("groq"):
        logger.info(
            f"[Router] ANALYSIS fallback → Groq {GROQ_ANALYST_MODEL} (shares CEO 30k TPM)"
        )
        return LLM(
            model=f"groq/{GROQ_ANALYST_MODEL}",
            api_key=GROQ_API_KEY,
            temperature=temperature,
            max_tokens=4096,
            num_retries=3,
        )
    if GEMINI_API_KEY and not _is_excluded("gemini_flash") and not is_near_quota("gemini_flash"):
        logger.info(
            f"[Router] ANALYSIS fallback → Google AI Studio {GEMINI_CEO_MODEL} (250k TPM)"
        )
        return LLM(
            model=GEMINI_CEO_MODEL,
            api_key=GEMINI_API_KEY,
            temperature=temperature,
            max_tokens=4096,
            num_retries=3,
        )
    if NVIDIA_API_KEY and not _is_excluded("nvidia") and not is_near_quota("nvidia"):
        logger.info(
            f"[Router] ANALYSIS fallback → NVIDIA NIM {NVIDIA_ANALYST_MODEL} (40 req/min)"
        )
        return LLM(
            model=f"openai/{NVIDIA_ANALYST_MODEL}",
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_BASE_URL,
            temperature=temperature,
            max_tokens=4096,
            num_retries=3,
        )
    logger.warning("[Router] ANALYSIS fallback → Ollama (slow)")
    return LLM(
        model=f"ollama/{OLLAMA_MODEL}",
        base_url=OLLAMA_BASE_URL,
        temperature=temperature,
    )


def get_light_llm(temperature: float = 0.0) -> LLM:
    """
    Scraper / Parser / Organizer — structured extraction and DB writes.
    Cerebras primary: 1M tokens/day, ultra-fast (1800+ tok/s), zero TPM pressure.
    Google Gemma 3 27B backup: 15k TPM, 14,400 req/day — near-unlimited daily quota.
    NVIDIA backup: 40 req/min, no TPM cap.
    """
    if CEREBRAS_API_KEY and not _is_excluded("cerebras") and not is_near_quota("cerebras"):
        logger.info(
            f"[Router] LIGHT tier → Cerebras {CEREBRAS_MODEL} (1M tok/day, fastest)"
        )
        return LLM(
            model=f"openai/{CEREBRAS_MODEL}",
            api_key=CEREBRAS_API_KEY,
            base_url=CEREBRAS_BASE_URL,
            temperature=temperature,
            max_tokens=512,
            num_retries=3,
        )
    if GEMINI_API_KEY and not _is_excluded("gemini_gemma") and not is_near_quota("gemini_gemma"):
        logger.info(
            f"[Router] LIGHT fallback → Google AI Studio {GEMINI_LIGHT_MODEL} (15k TPM)"
        )
        return LLM(
            model=GEMINI_LIGHT_MODEL,
            api_key=GEMINI_API_KEY,
            temperature=temperature,
            max_tokens=512,
            num_retries=3,
        )
    if NVIDIA_API_KEY and not _is_excluded("nvidia") and not is_near_quota("nvidia"):
        logger.info(
            f"[Router] LIGHT fallback → NVIDIA NIM {NVIDIA_LIGHT_MODEL} (40 req/min)"
        )
        return LLM(
            model=f"openai/{NVIDIA_LIGHT_MODEL}",
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_BASE_URL,
            temperature=temperature,
            max_tokens=512,
            num_retries=3,
        )
    logger.warning("[Router] LIGHT fallback → Ollama (CPU-only, slow)")
    return LLM(
        model=f"ollama/{OLLAMA_MODEL}",
        base_url=OLLAMA_BASE_URL,
        temperature=temperature,
    )


def get_router_status() -> dict:
    """Print which providers are live. Call at startup to verify config."""
    g = bool(GROQ_API_KEY)
    c = bool(CEREBRAS_API_KEY)
    gem = bool(GEMINI_API_KEY)
    n = bool(NVIDIA_API_KEY)
    o = bool(OPENROUTER_API_KEY)
    with _EXCLUDED_LOCK:
        excl = set(_EXCLUDED) or "none"
    return {
        "providers": {
            "groq": g,
            "cerebras": c,
            "gemini_flash": gem,
            "gemini_gemma": gem,
            "nvidia": n,
            "openrouter": o,
            "ollama": True,
        },
        "excluded": excl,
        "heavy_chain": f"Groq({GROQ_CEO_MODEL}, 30k TPM)"
        if g
        else ("Gemini Flash(250k TPM)" if gem else "NVIDIA→OpenRouter→Ollama"),
        "analysis_chain": f"Cerebras({CEREBRAS_MODEL}, 8k ctx, 1M tok/day)"
        if c
        else (f"Groq({GROQ_ANALYST_MODEL})" if g else "Ollama"),
        "light_chain": f"Cerebras({CEREBRAS_MODEL}, 8k ctx, 1M tok/day)"
        if c
        else (
            f"Gemma({GEMINI_LIGHT_MODEL})"
            if gem
            else ("NVIDIA" if n else "Ollama(slow)")
        ),
    }
