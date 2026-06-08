"""
RE_OS — LLM Router (CrewAI 0.80 / LiteLLM)
────────────────────────────────────────────
SEVEN-PROVIDER FALLBACK CHAIN — all free tiers, zero cost.

  HEAVY (CEO):
    1. Groq       llama-4-scout-17b        — 30,000 TPM, primary
    2. Gemini     gemini-2.5-flash         — 250,000 TPM, 20 req/day
    3. NVIDIA     llama-3.1-405b           — 40 req/min
    4. SambaNova  llama-3.3-70b            — 20M tok/day, 20 RPM  ← NEW
    5. OpenRouter llama-3.3-70b:free       — 50-1000 req/day
    6. Cloudflare llama-3.3-70b-fp8-fast   — 10K neurons/day last-resort  ← NEW
    7. Ollama     qwen2.5:7b               — local CPU, always available

  ANALYSIS (Analyst):
    1. Cerebras   gpt-oss-120b             — 1M tok/day, 60-100k TPM, primary
    2. Groq       llama-4-scout-17b        — shares CEO bucket
    3. Gemini     gemini-2.5-flash         — 250k TPM fallback
    4. NVIDIA     llama-3.1-nemotron-70b   — 40 req/min
    5. SambaNova  llama-3.3-70b            — 20M tok/day  ← NEW
    6. Cloudflare llama-3.1-8b             — last-resort  ← NEW
    7. Ollama     qwen2.5:7b               — local CPU

  LIGHT (Scraper):
    1. Cerebras   gpt-oss-120b             — 1M tok/day, fastest, primary
    2. Gemini     gemma-3-27b-it           — 15k TPM, 14.4k req/day
    3. NVIDIA     llama-3.3-70b            — 40 req/min
    4. SambaNova  llama-3.3-70b            — 20M tok/day  ← NEW
    5. Cloudflare llama-3.1-8b             — last-resort  ← NEW
    6. Ollama     qwen2.5:7b               — local CPU

SambaNova: OpenAI-compatible, 20 RPM hard ceiling — acceptable for pipeline cadence.
Cloudflare: 10K neurons/day ≈ 20-100 real requests. True last-resort only.
Cerebras caveat: 8,192 token context cap. Fine for Light + Analysis, NOT CEO.
"""

import threading
from datetime import datetime, UTC
from loguru import logger

from crewai import LLM
from config.metrics import llm_router_fallbacks_total
from config.settings import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_QWEN_MODEL,
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
    SAMBANOVA_API_KEY,
    SAMBANOVA_BASE_URL,
    SAMBANOVA_HEAVY_MODEL,
    CLOUDFLARE_API_KEY,
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_LIGHT_MODEL,
    CLOUDFLARE_HEAVY_MODEL,
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
        elif base_url and "sambanova" in base_url:
            provider = "sambanova"
        elif base_url and "cloudflare" in base_url:
            provider = "cloudflare"
        else:
            provider_part = model.split("/")[0].lower()
            provider_map = {
                "openai": "cerebras",
                "groq": "groq",
                "google": "gemini_flash",
                "nvidia": "nvidia",
                "sambanova": "sambanova",
                "openrouter": "openrouter",
                "cloudflare": "cloudflare",
                "ollama": "ollama",
            }
            provider = provider_map.get(provider_part, provider_part)
        tokens = completion_response.usage.total_tokens if completion_response.usage else 0
        record_token_usage(provider, tokens)
        _record_success(provider)
        logger.debug(f"[Router] Token usage recorded: {provider} {tokens}")
    except Exception:
        pass

_DAILY_LIMITS = {
    "groq": 1_000_000,
    "cerebras": 1_000_000,
    "gemini": 250_000,
    "nvidia": 100_000,
    "sambanova": 20_000_000,
    "gemini_flash": 1_000_000,
    "gemini_gemma": 500_000,
    "openrouter": 500_000,
    "cloudflare": 5_000,
}


_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis as _redis_mod
            from config.settings import REDIS_URL
            _redis_client = _redis_mod.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        except Exception as exc:
            logger.debug("[Router] Redis unavailable: {}", exc)
    return _redis_client


def _track_token_usage(provider: str, prompt_tokens: int, completion_tokens: int) -> None:
    try:
        from datetime import date
        r = _get_redis()
        if r is None:
            return
        key = "llm:tokens:{}:{}".format(provider, date.today().isoformat())
        total = prompt_tokens + completion_tokens
        new_val = r.incrby(key, total)
        r.expire(key, 86400 * 2)
        limit = _DAILY_LIMITS.get(provider)
        if limit and new_val > limit * 0.80:
            from utils.discord_notifier import send
            send("system", "LLM Quota Warning — {}".format(provider),
                 "{} at {}% daily quota ({:,} / {:,} tokens)".format(
                     provider, int(new_val / limit * 100), new_val, limit))
    except Exception as exc:
        logger.debug("[Router] Token tracking failed for {}: {}", provider, exc)


if not isinstance(litellm.success_callback, list):
    litellm.success_callback = []
if _litellm_usage_callback not in litellm.success_callback:
    litellm.success_callback.append(_litellm_usage_callback)

# Runtime provider exclusion — thread-safe shared set.
# All reads and writes go through helpers below so parallel market runs don't race.
_EXCLUDED: set = set()
_EXCLUDED_LOCK = threading.Lock()

# Circuit breaker state machine — per-provider health tracking.
# States: CLOSED (normal) → OPEN (after 3 failures in 5 min) → HALF_OPEN (after 60s)
# On HALF_OPEN: 1 trial call allowed. Success → CLOSED. Failure → OPEN again.
_CIRCUIT_STATE: dict[str, dict] = {}
_CIRCUIT_LOCK = threading.Lock()

_CIRCUIT_FAIL_THRESHOLD = 3
_CIRCUIT_WINDOW_SECONDS = 300
_CIRCUIT_HALF_OPEN_SECONDS = 60
# If a trial call never resolves (litellm callback never fires), re-open after this many seconds.
_CIRCUIT_HALF_OPEN_STALE_SECONDS = 120

import time as _time


def _get_circuit_state(provider: str) -> dict:
    now = _time.time()
    with _CIRCUIT_LOCK:
        if provider not in _CIRCUIT_STATE:
            return {"circuit": "CLOSED", "failures": [], "open_since": None, "half_open_since": None}
        state = _CIRCUIT_STATE[provider]
        if state["circuit"] == "OPEN":
            if state["open_since"] and (now - state["open_since"]) >= _CIRCUIT_HALF_OPEN_SECONDS:
                state["circuit"] = "HALF_OPEN"
                state["open_since"] = None
                state["half_open_since"] = now
        elif state["circuit"] == "HALF_OPEN":
            # Trial call never resolved — litellm success_callback never fired.
            # Re-open to prevent permanent HALF_OPEN on connection errors.
            ho_since = state.get("half_open_since")
            if ho_since and (now - ho_since) >= _CIRCUIT_HALF_OPEN_STALE_SECONDS:
                state["circuit"] = "OPEN"
                state["open_since"] = now
                state["half_open_since"] = None
                logger.warning("[CircuitBreaker] {} stale HALF_OPEN → OPEN (trial timed out after {}s)",
                               provider, _CIRCUIT_HALF_OPEN_STALE_SECONDS)
    return state


def _record_failure(provider: str) -> None:
    now = _time.time()
    with _CIRCUIT_LOCK:
        state = _CIRCUIT_STATE.setdefault(provider, {"circuit": "CLOSED", "failures": [], "open_since": None, "half_open_since": None})
        state["failures"] = [t for t in state["failures"] if now - t < _CIRCUIT_WINDOW_SECONDS]
        state["failures"].append(now)
        if len(state["failures"]) >= _CIRCUIT_FAIL_THRESHOLD and state["circuit"] != "OPEN":
            state["circuit"] = "OPEN"
            state["open_since"] = now
            logger.warning("[CircuitBreaker] {} → OPEN after {} failures in {}s",
                           provider, _CIRCUIT_FAIL_THRESHOLD, _CIRCUIT_WINDOW_SECONDS)
            try:
                from utils.discord_notifier import send
                send("ops", "LLM Circuit OPEN — {}".format(provider),
                     "{} circuit opened after {} failures in {}s. "
                     "Half-open in {}s. Auto-recovery enabled.".format(
                         provider, _CIRCUIT_FAIL_THRESHOLD, _CIRCUIT_WINDOW_SECONDS, _CIRCUIT_HALF_OPEN_SECONDS))
            except Exception:
                pass


def _record_success(provider: str) -> None:
    with _CIRCUIT_LOCK:
        state = _CIRCUIT_STATE.setdefault(provider, {"circuit": "CLOSED", "failures": [], "open_since": None, "half_open_since": None})
        prev = state["circuit"]
        state["circuit"] = "CLOSED"
        state["failures"] = []
        state["open_since"] = None
        state["half_open_since"] = None
        if prev != "CLOSED":
            logger.info("[CircuitBreaker] {} → CLOSED (was {})", provider, prev)


def get_circuit_states() -> dict[str, dict]:
    """Return per-provider circuit breaker state for health endpoint."""
    result = {}
    now = _time.time()
    with _CIRCUIT_LOCK:
        for provider, state in _CIRCUIT_STATE.items():
            result[provider] = {
                "circuit_state": state["circuit"],
                "failure_count": len([t for t in state["failures"] if now - t < _CIRCUIT_WINDOW_SECONDS]),
                "open_since": state.get("open_since"),
            }
    for p in ["groq", "cerebras", "gemini", "nvidia", "sambanova", "openrouter", "cloudflare"]:
        if p not in result:
            result[p] = {"circuit_state": "CLOSED", "failure_count": 0, "open_since": None}
    return result

# DAILY_LIMITS config — limits are per calendar day UTC, reset at midnight
DAILY_LIMITS = {
    "cerebras": 1_000_000,
    "groq": 500_000,
    "gemini_flash": 1_000_000,
    "gemini_gemma": 500_000,
    "nvidia": 2_000_000,
    "sambanova": 20_000_000,   # 20M tok/day free tier
    "openrouter": 500_000,
    "cloudflare": 5_000,       # conservative — 10K neurons, not raw tokens
}

# In-process daily token counters — reset automatically at UTC midnight
_daily_counts: dict[str, int] = {}
_last_counts_date: str = None
_counts_lock = threading.Lock()


def _is_excluded(provider: str) -> bool:
    with _EXCLUDED_LOCK:
        if provider in _EXCLUDED:
            return True
    state = _get_circuit_state(provider)
    if state["circuit"] == "OPEN":
        return True
    return False


def _exclude(provider: str) -> None:
    with _EXCLUDED_LOCK:
        _EXCLUDED.add(provider)
    _record_failure(provider)


def _clear_excluded() -> None:
    with _EXCLUDED_LOCK:
        _EXCLUDED.clear()


def _reset_circuit_state():
    """Reset ALL circuit breaker state (test helper, not production use)."""
    with _CIRCUIT_LOCK:
        _CIRCUIT_STATE.clear()


def _reset_daily_counts_if_needed() -> None:
    """Reset daily token counters at UTC midnight."""
    global _last_counts_date, _daily_counts
    with _counts_lock:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if _last_counts_date != today:
            _daily_counts = {}
            _last_counts_date = today
            logger.info("[Router] Daily token counters reset for {} UTC", today)


def record_token_usage(provider: str, tokens: int, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """Record token usage for a provider. Call after each LLM invocation."""
    if prompt_tokens or completion_tokens:
        _track_token_usage(provider, prompt_tokens, completion_tokens)
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


def get_heavy_llm(temperature: float = 0.1, excluded: set = None) -> LLM:
    """
    CEO Agent — orchestration and final synthesis.
    Groq Scout (30k TPM) primary. Gemini fallback for long-context synthesis.
    excluded: optional per-session exclusion set (board room sessions) — does NOT
    touch the global _EXCLUDED used by the pipeline.
    """
    def _excl(p): return _is_excluded(p) or (excluded is not None and p in excluded)
    if GROQ_API_KEY and not _excl("groq") and not is_near_quota("groq"):
        logger.info(f"[Router] HEAVY tier → Groq {GROQ_CEO_MODEL} (30k TPM)")
        return LLM(
            model=f"groq/{GROQ_CEO_MODEL}",
            api_key=GROQ_API_KEY,
            temperature=temperature,
            max_tokens=4096,
            num_retries=3,
        )
    llm_router_fallbacks_total.labels(tier="heavy", provider="groq").inc()
    if GEMINI_API_KEY and not _excl("gemini_flash") and not is_near_quota("gemini_flash"):
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
    llm_router_fallbacks_total.labels(tier="heavy", provider="gemini_flash").inc()
    if NVIDIA_API_KEY and not _excl("nvidia") and not is_near_quota("nvidia"):
        logger.info("[Router] HEAVY fallback → NVIDIA NIM 405B")
        return LLM(
            model=f"openai/{NVIDIA_CEO_MODEL}",
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_BASE_URL,
            temperature=temperature,
            max_tokens=4096,
            num_retries=3,
        )
    llm_router_fallbacks_total.labels(tier="heavy", provider="nvidia").inc()
    if SAMBANOVA_API_KEY and not _excl("sambanova") and not is_near_quota("sambanova"):
        logger.info(f"[Router] HEAVY fallback → SambaNova {SAMBANOVA_HEAVY_MODEL} (20M tok/day)")
        return LLM(
            model=f"openai/{SAMBANOVA_HEAVY_MODEL}",
            api_key=SAMBANOVA_API_KEY,
            base_url=SAMBANOVA_BASE_URL,
            temperature=temperature,
            max_tokens=4096,
            num_retries=2,
        )
    llm_router_fallbacks_total.labels(tier="heavy", provider="sambanova").inc()
    if OPENROUTER_API_KEY and not _excl("openrouter") and not is_near_quota("openrouter"):
        logger.info("[Router] HEAVY fallback → OpenRouter")
        return LLM(
            model=f"openrouter/{OPENROUTER_MODEL}",
            api_key=OPENROUTER_API_KEY,
            temperature=temperature,
            max_tokens=4096,
            num_retries=3,
        )
    llm_router_fallbacks_total.labels(tier="heavy", provider="openrouter").inc()
    if CLOUDFLARE_API_KEY and CLOUDFLARE_ACCOUNT_ID and not _excl("cloudflare") and not is_near_quota("cloudflare"):
        logger.warning("[Router] HEAVY last-resort → Cloudflare Workers AI (10K neurons/day)")
        cf_base = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1"
        return LLM(
            model=f"openai/{CLOUDFLARE_HEAVY_MODEL}",
            api_key=CLOUDFLARE_API_KEY,
            base_url=cf_base,
            temperature=temperature,
            max_tokens=2048,
            num_retries=1,
        )
    llm_router_fallbacks_total.labels(tier="heavy", provider="cloudflare").inc()
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
    llm_router_fallbacks_total.labels(tier="analysis", provider="cerebras").inc()
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
    llm_router_fallbacks_total.labels(tier="analysis", provider="groq").inc()
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
    llm_router_fallbacks_total.labels(tier="analysis", provider="gemini_flash").inc()
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
    llm_router_fallbacks_total.labels(tier="analysis", provider="nvidia").inc()
    if SAMBANOVA_API_KEY and not _is_excluded("sambanova") and not is_near_quota("sambanova"):
        logger.info(f"[Router] ANALYSIS fallback → SambaNova {SAMBANOVA_HEAVY_MODEL}")
        return LLM(
            model=f"openai/{SAMBANOVA_HEAVY_MODEL}",
            api_key=SAMBANOVA_API_KEY,
            base_url=SAMBANOVA_BASE_URL,
            temperature=temperature,
            max_tokens=4096,
            num_retries=2,
        )
    llm_router_fallbacks_total.labels(tier="analysis", provider="sambanova").inc()
    if CLOUDFLARE_API_KEY and CLOUDFLARE_ACCOUNT_ID and not _is_excluded("cloudflare") and not is_near_quota("cloudflare"):
        logger.warning("[Router] ANALYSIS last-resort → Cloudflare Workers AI")
        cf_base = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1"
        return LLM(
            model=f"openai/{CLOUDFLARE_LIGHT_MODEL}",
            api_key=CLOUDFLARE_API_KEY,
            base_url=cf_base,
            temperature=temperature,
            max_tokens=2048,
            num_retries=1,
        )
    llm_router_fallbacks_total.labels(tier="analysis", provider="cloudflare").inc()
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
    llm_router_fallbacks_total.labels(tier="light", provider="cerebras").inc()
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
    llm_router_fallbacks_total.labels(tier="light", provider="gemini_gemma").inc()
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
    llm_router_fallbacks_total.labels(tier="light", provider="nvidia").inc()
    if SAMBANOVA_API_KEY and not _is_excluded("sambanova") and not is_near_quota("sambanova"):
        logger.info(f"[Router] LIGHT fallback → SambaNova {SAMBANOVA_HEAVY_MODEL}")
        return LLM(
            model=f"openai/{SAMBANOVA_HEAVY_MODEL}",
            api_key=SAMBANOVA_API_KEY,
            base_url=SAMBANOVA_BASE_URL,
            temperature=temperature,
            max_tokens=512,
            num_retries=2,
        )
    llm_router_fallbacks_total.labels(tier="light", provider="sambanova").inc()
    if CLOUDFLARE_API_KEY and CLOUDFLARE_ACCOUNT_ID and not _is_excluded("cloudflare") and not is_near_quota("cloudflare"):
        logger.warning("[Router] LIGHT last-resort → Cloudflare Workers AI")
        cf_base = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1"
        return LLM(
            model=f"openai/{CLOUDFLARE_LIGHT_MODEL}",
            api_key=CLOUDFLARE_API_KEY,
            base_url=cf_base,
            temperature=temperature,
            max_tokens=512,
            num_retries=1,
        )
    llm_router_fallbacks_total.labels(tier="light", provider="cloudflare").inc()
    logger.warning("[Router] LIGHT fallback → Ollama Qwen2.5:1.5b (local, fast)")
    return LLM(
        model=f"ollama/{OLLAMA_QWEN_MODEL}",
        base_url=OLLAMA_BASE_URL,
        temperature=temperature,
        max_tokens=512,
    )


def get_router_status() -> dict:
    """Print which providers are live. Call at startup to verify config."""
    g = bool(GROQ_API_KEY)
    c = bool(CEREBRAS_API_KEY)
    gem = bool(GEMINI_API_KEY)
    n = bool(NVIDIA_API_KEY)
    sn = bool(SAMBANOVA_API_KEY)
    o = bool(OPENROUTER_API_KEY)
    cf = bool(CLOUDFLARE_API_KEY and CLOUDFLARE_ACCOUNT_ID)
    with _EXCLUDED_LOCK:
        excl = set(_EXCLUDED) or "none"
    return {
        "providers": {
            "groq": g,
            "cerebras": c,
            "gemini_flash": gem,
            "gemini_gemma": gem,
            "nvidia": n,
            "sambanova": sn,
            "openrouter": o,
            "cloudflare": cf,
            "ollama": True,
        },
        "excluded": excl,
        "heavy_chain": (
            f"Groq→Gemini→NVIDIA→SambaNova→OpenRouter→Cloudflare→Ollama"
            f" ({sum([g, gem, n, sn, o, cf])}/6 cloud providers active)"
        ),
        "analysis_chain": (
            f"Cerebras→Groq→Gemini→NVIDIA→SambaNova→Cloudflare→Ollama"
            f" ({sum([c, g, gem, n, sn, cf])}/6 cloud providers active)"
        ),
        "light_chain": (
            f"Cerebras→Gemini→NVIDIA→SambaNova→Cloudflare→Ollama"
            f" ({sum([c, gem, n, sn, cf])}/5 cloud providers active)"
        ),
    }


def record_agent_token_usage(agent_name: str, tokens_used: int, model: str, run_id: str) -> None:
    """Record token usage for an agent after LLM call.

    Called by agents after successful LLM invocation to track their token budget.
    Extracts from provider-level tracking; agents should call this with their
    agent_name and the run_id for audit correlation.
    """
    try:
        from utils.token_tracker import record
        record(agent_name, tokens_used, model, run_id)
    except Exception as e:
        logger.debug("[Router] Agent token recording failed: {}", e)
