# RE_OS — Free Model Reference
**Last updated: 2026-05-13**

Complete reference for every free provider used by RE_OS.
Routing logic lives in `config/llm_router.py`. Settings in `config/settings.py`.

---

## Routing Architecture

```
HEAVY (CEO agent)
  PRIMARY:   Groq  meta-llama/llama-4-scout-17b-16e-instruct  30k TPM
  BACKUP 1:  Google AI Studio  gemini-2.5-flash               250k TPM, 20 req/day
  BACKUP 2:  NVIDIA NIM  llama-3.1-405b-instruct              40 req/min
  BACKUP 3:  OpenRouter  llama-3.3-70b:free                   50-1000 req/day
  BACKUP 4:  Ollama local

ANALYSIS (Analyst agent)
  PRIMARY:   Cerebras  llama-3.3-70b                          60-100k TPM, 1M tok/day
  BACKUP 1:  Groq  meta-llama/llama-4-scout-17b-16e-instruct  shares CEO 30k bucket
  BACKUP 2:  Ollama local

LIGHT (Scraper + Parser + Organizer agents)
  PRIMARY:   Cerebras  llama-3.3-70b                          60-100k TPM, 1M tok/day
  BACKUP 1:  Google AI Studio  gemma-3-27b-it                 15k TPM, 14,400 req/day
  BACKUP 2:  NVIDIA NIM  llama-3.3-70b-instruct               40 req/min
  BACKUP 3:  Ollama local
```

---

## Provider 1 — Cerebras  `cloud.cerebras.ai`

**Sign up:** No card. Just email. API key instant.
**Key format:** `csk-...`
**Status in RE_OS:** ⚠️ KEY MISSING — add `CEREBRAS_API_KEY` to `.env`

| Model | RE_OS Use | Req/Min | Tok/Min | Tok/Day | Context |
|-------|-----------|---------|---------|---------|---------|
| `llama-3.3-70b` | **Light + Analysis (primary)** | 30 | 60,000–100,000 | 1,000,000 | **8,192** |

**Why Cerebras:** Fastest inference available anywhere (1,800+ tok/s on Llama 70B, 3× faster than Groq).
1M tokens/day completely separate from Groq budget — Light + Analysis never compete with CEO.

**Critical limit:** 8,192 token context cap. Fine for structured extraction and DB query results.
Do NOT use for CEO synthesis (can exceed 8k).

---

## Provider 2 — Groq  `console.groq.com`

**Sign up:** No card. No phone. Just email.
**Key format:** `gsk_...`
**Status in RE_OS:** ✅ Key set

| Model | RE_OS Use | Req/Day | Tok/Min | Context |
|-------|-----------|---------|---------|---------|
| `meta-llama/llama-4-scout-17b-16e-instruct` | **CEO primary** | 1,000 | **30,000** | 128k |
| `llama-3.3-70b-versatile` | CEO backup (old primary) | 1,000 | 12,000 | 128k |
| `llama-3.1-8b-instant` | Emergency light fallback | 14,400 | 6,000 | 128k |
| `openai/gpt-oss-120b` | Alternative heavy | 1,000 | 8,000 | 128k |
| `openai/gpt-oss-20b` | Alternative analysis | 1,000 | 8,000 | 128k |
| `qwen/qwen3-32b` | Alternative analysis | 1,000 | 6,000 | 128k |

**Why Scout for CEO:** 30,000 TPM vs 70B-versatile's 12,000 TPM. A CEO synthesis call (~2,500 tokens)
consumes only 8% of the per-minute budget vs 21% before. No more rate limit failures on CEO.

---

## Provider 3 — Google AI Studio  `aistudio.google.com`

**Sign up:** No card. Google account only. Instant.
**Key format:** `AIza...`
**Status in RE_OS:** ⚠️ KEY MISSING — add `GEMINI_API_KEY` to `.env`
**Note:** Data used for training if outside UK/CH/EEA/EU. India = data used for training. Acceptable for market intelligence data.

| Model | RE_OS Use | Req/Min | Tok/Min | Req/Day | Context |
|-------|-----------|---------|---------|---------|---------|
| `gemini/gemini-2.5-flash` | **CEO fallback** | 5 | 250,000 | 20 | 1M |
| `gemini/gemini-3.1-flash-lite` | CEO fallback alt | 15 | 250,000 | 500 | 1M |
| `gemini/gemma-3-27b-it` | **Light fallback** | 30 | 15,000 | 14,400 | 128k |

**Why Gemini for CEO backup:** 250k TPM on Flash — effectively unlimited for CEO synthesis calls.
Gemma 3 27B for light: 14,400 req/day is near-unlimited for daily market runs.

---

## Provider 4 — NVIDIA NIM  `build.nvidia.com`

**Sign up:** Phone verification required.
**Key format:** `nvapi-...`
**Status in RE_OS:** ✅ Key set

| Model | RE_OS Use | Req/Min | Context |
|-------|-----------|---------|---------|
| `meta/llama-3.1-405b-instruct` | CEO backup | 40 | 128k |
| `meta/llama-3.3-70b-instruct` | Light backup | 40 | 128k |
| `nvidia/llama-3.1-nemotron-70b-instruct` | Analyst backup | 40 | 128k |

---

## Provider 5 — OpenRouter  `openrouter.ai`

**Sign up:** No card.
**Key format:** `sk-or-v1-...`
**Status in RE_OS:** ✅ Key set
**Limits:** 50 req/day base · 1,000/day with $10 one-time topup

| Model | RE_OS Use |
|-------|-----------|
| `meta-llama/llama-3.3-70b-instruct:free` | CEO last resort |
| `google/gemma-4-26b-a4b-it:free` | Alternate |
| `nvidia/nemotron-3-super-120b-a12b:free` | Alternate |

---

## Provider 6 — Ollama (Local Docker)  `localhost:11434`

**No API key. Runs in Docker.**
**Limits:** None. Final fallback for all tiers.

| Model | Pull Command | RAM | Best For |
|-------|-------------|-----|---------|
| `llama3.1:8b` | `ollama pull llama3.1:8b` | ~5GB | Current default — structured extraction |
| `llama3.2:3b` | `ollama pull llama3.2:3b` | ~2GB | Faster, lighter |
| `qwen2.5:7b` | `ollama pull qwen2.5:7b` | ~4GB | Excellent JSON output — Parser agent |

---

## Daily Capacity Summary (after 2026-05-13 routing changes)

Per full 3-market run (Yelahanka + Devanahalli + Hebbal):

| Tier | Provider | Tokens Used | Daily Budget | Runs/Day |
|------|----------|-------------|--------------|----------|
| Light (3 agents × 3 markets) | Cerebras | ~27k tokens | 1,000,000 | 37 full sweeps |
| Analysis (1 agent × 3 markets) | Cerebras | ~9k tokens | shared above | ↑ same pool |
| CEO (1 agent × 3 markets) | Groq Scout | ~7.5k tokens | 30k TPM, 1k req/day | >100 runs/day |

**Bottom line:** With Cerebras + Groq Scout, RE_OS can run **30+ full 3-market sweeps per day** with zero cost, no credit card.

---

## Setup Checklist

### Step 1 — Cerebras (5 min, no card)
1. Go to `cloud.cerebras.ai`
2. Sign up with email → confirm email
3. Go to **API Keys** → **Create**
4. Copy key (`csk-...`)
5. Paste into `.env`: `CEREBRAS_API_KEY=csk-your-key`

### Step 2 — Google AI Studio (5 min, Google account)
1. Go to `aistudio.google.com`
2. Sign in with Google account
3. Click **Get API Key** → **Create API key**
4. Copy key (`AIza...`)
5. Paste into `.env`: `GEMINI_API_KEY=AIza-your-key`

### Step 3 — Restart agents container (no rebuild)
```powershell
docker compose restart agents scheduler
```

### Step 4 — Verify routing
```powershell
docker compose exec agents python -c "
from config.llm_router import get_router_status
import json
print(json.dumps(get_router_status(), indent=2))
"
```

Expected output with all keys set:
```json
{
  "providers": { "groq": true, "cerebras": true, "gemini": true, "nvidia": true, "openrouter": true, "ollama": true },
  "heavy_chain":    "Groq(meta-llama/llama-4-scout-17b-16e-instruct, 30k TPM)",
  "analysis_chain": "Cerebras(llama-3.3-70b, 1M tok/day)",
  "light_chain":    "Cerebras(llama-3.3-70b, 1M tok/day)"
}
```

### Step 5 — Run a test
```powershell
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
```

Watch `logs/crew.log` for `[Router] LIGHT tier → Cerebras` — confirms routing is live.
