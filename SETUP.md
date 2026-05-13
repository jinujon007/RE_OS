# RE_OS — Setup Guide
### From zero to running in 20 minutes

---

## Step 1: Install Docker Desktop

1. Go to: https://www.docker.com/products/docker-desktop/
2. Download **Docker Desktop for Windows**
3. Install it (default settings, yes to WSL2 if it asks)
4. Restart your computer
5. Open Docker Desktop — wait for it to say "Engine running" (green dot)

---

## Step 2: Install Ollama (local LLM — free)

1. Go to: https://ollama.ai
2. Download and install for Windows
3. Open a terminal (Windows key + R, type `cmd`)
4. Run: `ollama pull llama3.1:8b`
   - This downloads the 8B model (~5GB) — do this once
   - Takes 10-20 min depending on internet speed

---

## Step 3: Get an OpenRouter API key (free)

1. Go to: https://openrouter.ai
2. Sign up (Google login works)
3. Go to API Keys → Create Key
4. Copy the key — starts with `sk-or-v1-...`
5. Free tier gives you access to Llama 3.1, Gemma, Mistral — zero cost

---

## Step 4: Configure RE_OS

Open your `RE_OS` folder. Copy `.env.example` to `.env`:

```
copy .env.example .env
```

Open `.env` and fill in:
```
OPENROUTER_API_KEY=sk-or-v1-your-key-here
TARGET_MARKETS=Yelahanka,Devanahalli,Hebbal
```

---

## Step 5: Boot the system

Open a terminal in the `RE_OS` folder:

```bash
# Start everything
docker compose up -d

# Watch the logs
docker compose logs -f agents
```

First boot takes 3-5 minutes (pulls images, sets up database).

---

## Step 6: Pull the Ollama model into Docker

```bash
docker exec re_os_ollama ollama pull llama3.1:8b
```

---

## Step 7: Run your first intelligence scan

```bash
# Yelahanka market intelligence — full run
docker exec re_os_agents python crews/market_intel_crew.py --market Yelahanka

# Just the RERA scraper — faster, data only
docker exec re_os_agents python scrapers/rera_karnataka.py --market Yelahanka

# Generate report from existing DB data (no scraping)
docker exec re_os_agents python crews/market_intel_crew.py --report-only Yelahanka
```

Output appears in: `RE_OS/outputs/yelahanka/`

---

## Day-to-Day Usage

The system runs automatically once started:

| Time | What happens |
|------|--------------|
| 2:00 AM IST | Full RERA refresh — all markets |
| 6:00 AM IST | Market snapshots updated |
| Every 6 hrs | Listings scan |

**Manual queries:**
```bash
# Get today's brief for a market
docker exec re_os_agents python crews/market_intel_crew.py --report-only Yelahanka

# Add a new market
# Edit .env → TARGET_MARKETS and restart
docker compose restart agents scheduler
```

---

## System Architecture

```
Your Machine
├── Docker Desktop (container engine)
│   ├── re_os_db       PostgreSQL + PostGIS (the brain's memory)
│   ├── re_os_ollama   Llama 3.1 local (free AI — parsing grunt work)
│   ├── re_os_redis    Task queue (agents communicate here)
│   ├── re_os_agents   The crew (CEO + Scraper + Parser + Organizer + Analyst)
│   └── re_os_scheduler  Runs everything on schedule
└── outputs/           Reports land here — open in any text editor
```

**Agent roles:**
- **CEO** — orchestrates the team, produces final strategic read
- **Scraper** — pulls raw data from RERA Karnataka, listings portals
- **Parser** — cleans and structures messy scraped data (Ollama handles this free)
- **Organizer** — writes clean data to PostgreSQL, handles deduplication
- **Analyst** — queries DB, calculates metrics, generates market brief (OpenRouter free)

---

## Troubleshooting

**Docker won't start:** Make sure WSL2 is enabled. In Windows Features, enable "Windows Subsystem for Linux".

**Ollama model not responding:** `docker exec re_os_ollama ollama list` — if model not listed, pull it again.

**Database connection error:** `docker compose ps` — check postgres is healthy (status = healthy).

**RERA scraper returns 0 results:** The portal may have changed its structure. Check `logs/rera_scraper.log`. The scraper has HTML fallback but may need an endpoint update.

---

## Expanding to Other Cities

When Bengaluru is solid, expanding to another city = 3 changes:

1. Add city markets to `config/settings.py` → `MARKET_RERA_KEYWORDS`
2. Add the RERA state URL for that state (each state has its own RERA portal)
3. Update `TARGET_MARKETS` in `.env`

The schema already supports multi-city — `micro_markets` table has `city` and `state` columns.

---

*RE_OS v0.1 — Yelahanka seed | May 2026*
