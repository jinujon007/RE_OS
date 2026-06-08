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
OLLAMA_QWEN_MODEL = os.getenv("OLLAMA_QWEN_MODEL", "qwen2.5:1.5b")

# Tier 1b — Cerebras: FREE, 1M tokens/day, 60-100k TPM, fastest inference available
# No credit card. Instant API key. llama3.1-8b at 1,800+ tok/s.
# LIMIT: 8,192 token context cap — fine for Light + Analysis (structured tasks, short prompts)
# Sign up: cloud.cerebras.ai
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")

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

# ── TIER 4 — SambaNova (free, ongoing — 20M tok/day, 20 RPM) ─────────────────
# Models: Llama 3.3 70B, DeepSeek-R1 671B, DeepSeek-V3, Qwen 2.5 72B
# Sign up: cloud.sambanova.ai — no card required
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY", "")
SAMBANOVA_BASE_URL = "https://api.sambanova.ai/v1"
SAMBANOVA_HEAVY_MODEL = os.getenv(
    "SAMBANOVA_HEAVY_MODEL", "Meta-Llama-3.3-70B-Instruct"
)

# ── TIER 5 — Cloudflare Workers AI (free, last-resort — 10K neurons/day) ─────
# 10K neurons/day ≈ 20-100 requests. Fires only when all other providers excluded.
# Sign up: cloudflare.com — free account → Workers & Pages → Account ID
CLOUDFLARE_API_KEY = os.getenv("CLOUDFLARE_API_KEY", "")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_LIGHT_MODEL = os.getenv(
    "CLOUDFLARE_LIGHT_MODEL", "@cf/meta/llama-3.1-8b-instruct"
)
CLOUDFLARE_HEAVY_MODEL = os.getenv(
    "CLOUDFLARE_HEAVY_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
)

# ── JINA AI — Reader + Embeddings ─────────────────────────────────────────────
# Reader: free without key (rate-limited) | with key: 100 RPM, JS-rendered pages
# Embeddings: 1M token one-time free bucket (jina-embeddings-v3, multilingual, 8K ctx)
# Sign up: jina.ai — no card required
JINA_API_KEY = os.getenv("JINA_API_KEY", "")
JINA_READER_BASE = "https://r.jina.ai"

# ── HUGGING FACE — Inference API (FinBERT sentiment, free warm tier) ──────────
# Classification models (BERT-class) are always warm on free tier — no cold start.
# Used for: FinBERT real estate news sentiment scoring (nightly batch).
# sign up: huggingface.co → Settings → Access Tokens → New token (read scope)
HF_API_KEY = os.getenv("HF_API_KEY", "")
FINBERT_MODEL_ID = "ProsusAI/finbert"
FINBERT_TONE_MODEL_ID = "ProsusAI/finbert-tone"
FINBERT_TONE_6LABEL_MODEL_ID = "yiyanghkust/finbert-tone"

# ── INTELLIGENCE LAYER (Phase 8.5) ────────────────────────────────────────────
# ChromaDB persistent path for intel report embeddings (maps to chroma_data volume)
CHROMA_DB_PATH = os.environ.get("CHROMA_DB_PATH", "/app/data/chroma")

# ── REDIS ────────────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ── RERA PLAYWRIGHT FALLBACK ─────────────────────────────────────────────────
# Markets where HTTP POST fails and Playwright form-interaction fallback is used.
RERA_USE_PLAYWRIGHT_MARKETS: list[str] = ["Yelahanka", "Hebbal"]
RERA_ALERT_COOLDOWN_SECONDS: int = 3600  # min interval between FALLBACK_SEED alerts per market

# Dropdown option values for Playwright form fill — portal may use different
# values than the POST payload for certain markets.
# Key: market name. Value: (district_option_value, subdistrict_option_value)
RERA_PLAYWRIGHT_LOCALITY_VALUES: dict[str, tuple[str, str]] = {
    "Yelahanka": ("Bengaluru Urban", "Yelahanka"),
    "Hebbal": ("Bengaluru Urban", "Bengaluru North"),
    "Devanahalli": ("Bengaluru  Rural", "Devanahalli"),
}

# ── MARKETS ──────────────────────────────────────────────────────────────────
TARGET_MARKETS = [m.strip() for m in os.getenv("TARGET_MARKETS", "Yelahanka,Devanahalli,Hebbal").split(",") if m.strip()]

# RERA Karnataka portal — confirmed live via browser inspection 2026-05-14
# Form: POST https://rera.karnataka.gov.in/projectViewDetails
# Fields: project, firm, appNo, regNo, district, subdistrict, btn1=Search
# Response: server-rendered HTML, all rows in one response, no JS needed
MARKET_RERA_CONFIG = {
    "Yelahanka": {
        "district": "Bengaluru  Urban",  # two spaces — mirrors Devanahalli Rural pattern
        "subdistrict": "Yelahanka",
        "expected_rows": 165,
    },
    "Hebbal": {
        "district": "Bengaluru  Urban",  # two spaces — mirrors Devanahalli Rural pattern
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
    "Hebbal": ["Hebbal", "Bellary Road", "Nagawara", "Bengaluru North"],
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
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

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
    "sattva",
    "total environment",
    "adarsh",
    "tata realty",
    "tata housing",
    "assetz",
    "century real estate",
    "century",
]
GRADE_A_MIN_UNITS = 500

# Grade B: 100-499 units
GRADE_B_MIN_UNITS = 100

# Grade B developer registry (T-1081 — GATE-80)
# Mapped to North Bengaluru project listing URLs.
# All Grade B sites use requests + BeautifulSoup (no Playwright needed).
GRADE_B_DEVELOPER_URLS: dict[str, str] = {
    "Ace Group": "https://www.acegroup.co.in/projects",
    "Godavari Developers": "https://www.godavaridevelopers.com/projects",
    "Concorde": "https://www.concorde.in/projects/bangalore",
    "HomeCity": "https://www.homecity.in/projects",
    "Nambiar Builders": "https://www.nambiarbuilders.com/projects/bangalore",
    "Shivaganga": "https://www.shivaganga.in/projects",
    "VSR Infra": "https://www.vsrinfra.com/projects",
    "Mahaveer Group": "https://www.mahaveergroup.in/projects",
    "Sumadhura Group": "https://www.sumadhura.com/projects/bangalore",
    "Aratt Developers": "https://www.arattdevelopers.com/projects",
}

# ── Discord (Phase 7 — Alerts) ────────────────────────────────────────────────
DISCORD_WEBHOOK_RERA_YELAHANKA   = os.environ.get("DISCORD_WEBHOOK_RERA_YELAHANKA", "")
DISCORD_WEBHOOK_RERA_DEVANAHALLI = os.environ.get("DISCORD_WEBHOOK_RERA_DEVANAHALLI", "")
DISCORD_WEBHOOK_RERA_HEBBAL      = os.environ.get("DISCORD_WEBHOOK_RERA_HEBBAL", "")
DISCORD_WEBHOOK_COMPETITOR       = os.environ.get("DISCORD_WEBHOOK_COMPETITOR", "")
DISCORD_WEBHOOK_PRICE            = os.environ.get("DISCORD_WEBHOOK_PRICE", "")
DISCORD_WEBHOOK_INTEL            = os.environ.get("DISCORD_WEBHOOK_INTEL", "")
DISCORD_WEBHOOK_SYSTEM           = os.environ.get("DISCORD_WEBHOOK_SYSTEM", "")
DISCORD_WEBHOOK_BD_OPPORTUNITIES = os.environ.get("DISCORD_WEBHOOK_BD_OPPORTUNITIES", "")
DISCORD_WEBHOOK_GOVT_POLICY = os.environ.get("DISCORD_WEBHOOK_GOVT_POLICY", "")

DISCORD_CHANNELS = {
    "rera_yelahanka":   DISCORD_WEBHOOK_RERA_YELAHANKA,
    "rera_devanahalli": DISCORD_WEBHOOK_RERA_DEVANAHALLI,
    "rera_hebbal":      DISCORD_WEBHOOK_RERA_HEBBAL,
    "competitor":       DISCORD_WEBHOOK_COMPETITOR,
    "price":            DISCORD_WEBHOOK_PRICE,
    "intel":            DISCORD_WEBHOOK_INTEL,
    "system":           DISCORD_WEBHOOK_SYSTEM,
    "bd_opportunities": DISCORD_WEBHOOK_BD_OPPORTUNITIES,
    "govt_policy_scout": DISCORD_WEBHOOK_GOVT_POLICY,
}

# ── INGEST ENGINE (Sprint 61) ─────────────────────────────────────────────────
# Per-plugin schedule overrides for IngestEngine.
# Keys are plugin_id; None means use the default (every day at 02:00 IST).
# Valid values: a crontab-style dict with day_of_week, hour, minute.
# Example: {"kaveri_bhoomi": {"day_of_week": "sun", "hour": 5, "minute": 0}}
PLUGIN_SCHEDULES: dict[str, dict | None] = {
    "rera_karnataka": None,          # daily at 02:00 IST
    "igr_karnataka": {"day_of_week": "sun", "hour": 5, "minute": 30},
    "kaveri_bhoomi": {"day_of_week": "sun", "hour": 5, "minute": 0},
    "portal_scout": None,            # daily at 02:00 IST
    "developer_scout": None,  # daily at 02:00 IST — vigorous monitoring for all 15 developers
    "news_scout": None,              # daily at 02:00 IST
    "distressed_scan": None,         # daily at 02:00 IST
    "bbmp_khata": {"day_of_week": "wed", "hour": 4, "minute": 0},
}

# ── AGENT TOKEN BUDGETS (Phase 9 - Sprint 60) ───────────────────────────────
TOKEN_BUDGETS: dict[str, int] = {
    "CEO": int(os.getenv("CEO_TOKEN_BUDGET", "4000")),
    "ANALYST": int(os.getenv("ANALYST_TOKEN_BUDGET", "2000")),
    "SCRAPER": int(os.getenv("SCRAPER_TOKEN_BUDGET", "1000")),
    "PR_HEAD": int(os.getenv("PR_HEAD_TOKEN_BUDGET", "1500")),
    "CONTENT_WRITER": int(os.getenv("CONTENT_WRITER_TOKEN_BUDGET", "1000")),
}

# ── PORTAL SCOUT CANARY (Sprint 79 — GATE-79) ──────────────────────────────────
PORTAL_SCOUT_MIN_LISTINGS_CANARY: int = 10

# ── GV FRESHNESS (Sprint 78 — GATE-78) ────────────────────────────────────────
# If the gazette year is more than this many months old, flag as stale
GV_FRESHNESS_WARN_MONTHS: int = 18

# ── AGENT RUN STATUSES ────────────────────────────────────────────────────────
AGENT_RUN_STATUSES = ["in_progress", "completed", "failed", "skipped"]
