# Contributing to RE_OS

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/Mac/Linux)
- Python 3.11+ (for running linting locally)
- Git

## 5-Step Setup (< 15 minutes)

### 1. Clone and configure

git clone https://github.com/jinujon007/RE_OS.git
cd RE_OS
cp .env.example .env

Open `.env`. Minimum required: set `DB_PASSWORD` to any strong password.
Optional but recommended: add `GROQ_API_KEY` (free at console.groq.com — no card required).

### 2. Start the stack

docker compose up -d

Wait ~60 seconds for first boot. Verify:

docker compose ps

All 5 services (`re_os_db`, `re_os_agents`, `re_os_scheduler`, `re_os_ollama`, `re_os_redis`) should show `running` or `healthy`.

### 3. Pull the local LLM (one-time, optional — ~4 GB)

docker compose exec ollama ollama pull llama3.1:8b

Skip if you have a Groq API key — the system uses cloud LLMs by default.

### 4. Run unit tests

docker compose exec agents pytest tests/ -q -m unit

Expected: all tests pass, no failures.

### 4b. Run integration tests (optional, requires Docker stack up)

docker compose exec agents pytest tests/ -m integration -v --tb=short

Integration tests verify DB schema, live endpoints, and end-to-end flows.
They are excluded from CI (which runs `pytest -m "not integration"`).

### 5. Verify the dashboard

curl http://localhost:8050/api/health

Expected: JSON with `"status": "healthy"` or `"degraded"`.
Open http://localhost:8050 in a browser to see the full dashboard.

## Run the intelligence pipeline

docker compose exec agents python crews/market_intel_crew.py --market Yelahanka

## Architecture

See the [Architecture section in README.md](README.md#architecture) for the full system diagram.

## Development Protocol

- **Architect:** Claude Code — writes task specs, reviews code, commits
- **Implementer:** Kilo Code — executes task specs from `TASK_BRIEFS.md`
- **All new dashboard routes:** `dashboard/app_fastapi.py`
- **Before marking any task done:** `ruff check .` and `pytest tests/ -q -m unit` must pass

## Code Style

- Formatter: [ruff](https://docs.astral.sh/ruff/) — run `ruff format .` before committing
- Linter: ruff — run `ruff check .` before committing
- Python version: 3.11

## Running the full CI checks locally

pip install ruff pytest pytest-cov
ruff check .
ruff format --check .
pytest tests/ -q -m unit --cov=agents --cov=config --cov=crews --cov=scrapers --cov=utils --cov=dashboard

## RERA Fine-Tuning (optional, requires GPU)

The QLoRA RERA extractor fine-tune requires a GPU with ≥4GB VRAM (RTX 3050 or better).

### Generate training data

python scripts/generate_rera_training_data.py --market Devanahalli

### Run fine-tune

pip install torch transformers accelerate peft trl bitsandbytes datasets
python scripts/finetune_rera_qwen.py

Output: `models/rera_qwen_adapter/` — LoRA adapter weights.
After fine-tuning, create the Ollama model:

ollama create rera-qwen -f models/Modelfile.rera
python scripts/load_rera_ollama.py

The `RERAExtractor` in `utils/rera_extractor.py` will auto-detect the Ollama model
and prefer it over the regex fallback.

### Telegram webhook setup

Register a bot with `t.me/BotFather`, get the token, add to `.env`:

TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_WEBHOOK_SECRET=your_secret

For local testing with ngrok:

ngrok http 8050
python scripts/register_telegram_webhook.py --url https://your-ngrok-url.ngrok.io
