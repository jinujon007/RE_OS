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
    PRIMARY:   Cerebras  llama3.1-8b                            — 60-100k TPM, 1M tok/day
    BACKUP 1:  Groq  meta-llama/llama-4-scout-17b-16e-instruct  — 30,000 TPM (shared with CEO)
    BACKUP 2:  Ollama local

  LIGHT (Scraper + Parser + Organizer):
    PRIMARY:   Cerebras  llama3.1-8b                            — 60-100k TPM, 1M tok/day
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
from loguru import logger

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crewai import LLM
from config.settings import (
    OLLAMA_BASE_URL, OLLAMA_MODEL,
    GROQ_API_KEY, GROQ_CEO_MODEL, GROQ_ANALYST_MODEL, GROQ_LIGHT_MODEL,
    CEREBRAS_API_KEY, CEREBRAS_BASE_URL, CEREBRAS_MODEL,
    GEMINI_API_KEY, GEMINI_CEO_MODEL, GEMINI_LIGHT_MODEL,
    NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_CEO_MODEL, NVIDIA_LIGHT_MODEL,
    OPENROUTER_API_KEY, OPENROUTER_MODEL,
)

# Runtime provider exclusion — populated by market_intel_crew on provider failure.
# Cleared after each market run. Thread-unsafe but single-threaded runs are fine.
_EXCLUDED: set = set()


def get_heavy_llm(temperature: float = 0.1) -> LLM:
    """
    CEO Agent — orchestration and final synthesis.
    Groq Scout (30k TPM) primary. Gemini fallback for long-context synthesis.
    """
    if GROQ_API_KEY and "groq" not in _EXCLUDED:
        logger.info(f"[Router] HEAVY tier → Groq {GROQ_CEO_MODEL} (30k TPM)")
        return LLM(
            model=f"groq/{GROQ_CEO_MODEL}",
            api_key=GROQ_API_KEY,
            temperature=temperature,
            max_tokens=512,
            num_retries=3,
        )
    if GEMINI_API_KEY and "gemini" not in _EXCLUDED:
        logger.info(f"[Router] HEAVY fallback → Google AI Studio {GEMINI_CEO_MODEL} (250k TPM)")
        return LLM(
            model=GEMINI_CEO_MODEL,
            api_key=GEMINI_API_KEY,
            temperature=temperature,
            max_tokens=512,
            num_retries=3,
        )
    if NVIDIA_API_KEY and "nvidia" not in _EXCLUDED:
        logger.info("[Router] HEAVY fallback → NVIDIA NIM 405B")
        return LLM(
            model=f"openai/{NVIDIA_CEO_MODEL}",
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_BASE_URL,
            temperature=temperature,
            max_tokens=512,
            num_retries=3,
        )
    if OPENROUTER_API_KEY and "openrouter" not in _EXCLUDED:
        logger.info("[Router] HEAVY fallback → OpenRouter")
        return LLM(
            model=f"openrouter/{OPENROUTER_MODEL}",
            api_key=OPENROUTER_API_KEY,
            temperature=temperature,
            max_tokens=512,
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
    """
    if CEREBRAS_API_KEY and "cerebras" not in _EXCLUDED:
        logger.info(f"[Router] ANALYSIS tier → Cerebras {CEREBRAS_MODEL} (1M tok/day)")
        return LLM(
            model=f"openai/{CEREBRAS_MODEL}",
            api_key=CEREBRAS_API_KEY,
            base_url=CEREBRAS_BASE_URL,
            temperature=temperature,
            max_tokens=1000,
            num_retries=3,
        )
    if GROQ_API_KEY and "groq" not in _EXCLUDED:
        logger.info(f"[Router] ANALYSIS fallback → Groq {GROQ_ANALYST_MODEL} (shares CEO 30k TPM)")
        return LLM(
            model=f"groq/{GROQ_ANALYST_MODEL}",
            api_key=GROQ_API_KEY,
            temperature=temperature,
            max_tokens=1000,
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
    if CEREBRAS_API_KEY and "cerebras" not in _EXCLUDED:
        logger.info(f"[Router] LIGHT tier → Cerebras {CEREBRAS_MODEL} (1M tok/day, fastest)")
        return LLM(
            model=f"openai/{CEREBRAS_MODEL}",
            api_key=CEREBRAS_API_KEY,
            base_url=CEREBRAS_BASE_URL,
            temperature=temperature,
            max_tokens=512,
            num_retries=3,
        )
    if GEMINI_API_KEY and "gemini" not in _EXCLUDED:
        logger.info(f"[Router] LIGHT fallback → Google AI Studio {GEMINI_LIGHT_MODEL} (15k TPM)")
        return LLM(
            model=GEMINI_LIGHT_MODEL,
            api_key=GEMINI_API_KEY,
            temperature=temperature,
            max_tokens=512,
            num_retries=3,
        )
    if NVIDIA_API_KEY and "nvidia" not in _EXCLUDED:
        logger.info(f"[Router] LIGHT fallback → NVIDIA NIM {NVIDIA_LIGHT_MODEL} (40 req/min)")
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
    excl = _EXCLUDED or "none"
    return {
        "providers": {
            "groq": g,
            "cerebras": c,
            "gemini": gem,
            "nvidia": n,
            "openrouter": o,
            "ollama": True,
        },
        "excluded": excl,
        "heavy_chain":    f"Groq({GROQ_CEO_MODEL}, 30k TPM)" if g else ("Gemini(250k TPM)" if gem else "NVIDIA→OpenRouter→Ollama"),
        "analysis_chain": f"Cerebras({CEREBRAS_MODEL}, 8k ctx, 1M tok/day)" if c else (f"Groq({GROQ_ANALYST_MODEL})" if g else "Ollama"),
        "light_chain":    f"Cerebras({CEREBRAS_MODEL}, 8k ctx, 1M tok/day)" if c else (f"Gemini({GEMINI_LIGHT_MODEL})" if gem else ("NVIDIA" if n else "Ollama(slow)")),
    }
