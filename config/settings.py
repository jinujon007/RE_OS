"""
RE_OS — Central Configuration
All environment variables and constants in one place.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── DATABASE ──────────────────────────────────────────────────────────────────
_db_password = os.getenv("DB_PASSWORD")
if not _db_password:
    raise ValueError(
        "DB_PASSWORD is not set. Add it to your .env file (see .env.example). "
        "Example: DB_PASSWORD=your_secure_password_here"
    )

DATABASE_URL = os.getenv(
    "DATABASE_URL", f"postgresql://re_os_user:{_db_password}@localhost:5432/re_os"
)

# ── LLM ENGINES ───────────────────────────────────────────────────────────────
# Tier 1 — Ollama: free, local, runs in Docker
# Used by: Scraper, Parser, Organizer agents (structured extraction, no deep reasoning)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# Tier 1b — Cerebras: FREE, 1M tokens/day, 60-100k TPM, fastest inference available
# No credit card. Instant API key. llama3.1-8b at 1,800+ tok/s.
# LIMIT: 8,192 token context cap — fine for Light + Analysis (structured tasks, short prompts)
# Sign up: cloud.cerebras.ai
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "llama3.1-8b")

# Tier 2 — Groq: free tier, 1,000 req/day, fast cloud inference
# CEO uses llama-4-scout: 30,000 TPM (2.5× better than 70B's 12k)
# Analyst uses llama-4-scout too — separate call, same 30k bucket shared with CEO
# Sign up: console.groq.com — no card required for free tier
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_CEO_MODEL = os.getenv(
    "GROQ_CEO_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
)
GROQ_ANALYST_MODEL = os.getenv(
    "GROQ_ANALYST_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
)
GROQ_LIGHT_MODEL = os.getenv("GROQ_LIGHT_MODEL", "llama-3.1-8b-instant")

# Tier 2b — Google AI Studio (Gemini): free tier
# Gemma 3 27B: 15k TPM, 14,400 req/day — unlimited for practical purposes (Light fallback)
# Gemini 2.5 Flash: 250k TPM, 20 req/day — huge context, CEO fallback
# Sign up: aistudio.google.com → Get API Key (instant, free Google account)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_CEO_MODEL = os.getenv("GEMINI_CEO_MODEL", "gemini/gemini-2.5-flash")
GEMINI_LIGHT_MODEL = os.getenv("GEMINI_LIGHT_MODEL", "gemini/gemma-3-27b-it")

# Tier 2c — NVIDIA NIM: free tier, 40 req/min, phone verification required
# Sign up: build.nvidia.com → API Keys
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_CEO_MODEL = os.getenv("NVIDIA_CEO_MODEL", "meta/llama-3.1-405b-instruct")
NVIDIA_ANALYST_MODEL = os.getenv(
    "NVIDIA_ANALYST_MODEL", "nvidia/llama-3.1-nemotron-70b-instruct"
)
NVIDIA_LIGHT_MODEL = os.getenv("NVIDIA_LIGHT_MODEL", "meta/llama-3.3-70b-instruct")

# Tier 3 — OpenRouter: free tier backup (50 req/day base, 1,000/day with $10 lifetime topup)
# All free models use the :free suffix
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
)

# ── REDIS ────────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ── MARKETS ──────────────────────────────────────────────────────────────────
TARGET_MARKETS = os.getenv("TARGET_MARKETS", "Yelahanka,Devanahalli,Hebbal").split(",")

# RERA Karnataka portal — confirmed live via browser inspection 2026-05-14
# Form: POST https://rera.karnataka.gov.in/projectViewDetails
# Fields: project, firm, appNo, regNo, district, subdistrict, btn1=Search
# Response: server-rendered HTML, all rows in one response, no JS needed
MARKET_RERA_CONFIG = {
    "Yelahanka": {
        "district": "Bengaluru Urban",
        "subdistrict": "Yelahanka",
        "expected_rows": 165,
    },
    "Hebbal": {
        "district": "Bengaluru Urban",
        "subdistrict": "Bengaluru North",
        "expected_rows": 734,
    },
    "Devanahalli": {
        "district": "Bengaluru  Rural",  # two spaces — exact portal value
        "subdistrict": "Devanahalli",
        "expected_rows": 317,
    },
}

# Legacy keyword map — kept for backwards compat, superseded by MARKET_RERA_CONFIG
MARKET_RERA_KEYWORDS = {
    "Yelahanka": ["Yelahanka", "Yelahanka New Town", "Yelahanka Satellite Town"],
    "Devanahalli": ["Devanahalli", "Kempegowda International Airport", "KIAL"],
    "Hebbal": ["Hebbal", "Bellary Road", "Nagawara"],
}

# ── SCRAPING ─────────────────────────────────────────────────────────────────
RERA_BASE_URL = "https://rera.karnataka.gov.in"
KAVERI_BASE_URL = "https://kaveri.karnataka.gov.in"

# ── OBSIDIAN VAULT ─────────────────────────────────────────────────────────────────
OBSIDIAN_VAULT_PATH = os.getenv(
    "OBSIDIAN_VAULT_PATH",
    r"D:\\Brain\\JINU JOSHI\\03 LLS\\01 Wiki"
)
# ── TELEGRAM ALERTS ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Scraping intervals (seconds)
RERA_SCRAPE_INTERVAL = int(os.getenv("RERA_SCRAPE_INTERVAL", "24")) * 3600
LISTINGS_SCRAPE_INTERVAL = int(os.getenv("LISTINGS_SCRAPE_INTERVAL", "6")) * 3600

# ── LOGGING ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ── DEVELOPER GRADE CRITERIA ─────────────────────────────────────────────────
# Grade A: 500+ units launched OR known national brand
GRADE_A_DEVELOPERS = [
    "prestige",
    "brigade",
    "sobha",
    "puravankara",
    "godrej",
    "mahindra",
    "lodha",
    "dl",
    "dlf",
    "shapoorji",
    "embassy",
    "mantri",
    "salarpuria",
    "total environment",
    "adarsh",
]
GRADE_A_MIN_UNITS = 500

# Grade B: 100-499 units
GRADE_B_MIN_UNITS = 100

# ── AGENT RUN STATUSES ────────────────────────────────────────────────────────
AGENT_RUN_STATUSES = ["in_progress", "completed", "failed", "skipped"]
