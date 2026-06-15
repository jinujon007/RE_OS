# RE_OS — Quick Start

> **Zero to first intelligence scan in 20 minutes.**

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Docker Desktop | Latest | Runs all containers |
| Git | Any | Clone the repo |
| At least one free API key | — | LLM inference (see Step 3) |

---

## Step 1 — Clone and Configure

```bash
git clone https://github.com/jinujon007/RE_OS.git
cd RE_OS
cp .env.example .env
```

Open `.env` and fill in at minimum one free LLM key. The fastest path is Cerebras (1M tokens/day free):

```
CEREBRAS_API_KEY=csk_your-key-here    # cloud.cerebras.ai → API Keys
```

Full `.env.example` documents all 8 provider tiers. You only need one to start.

---

## Step 2 — Start the Stack

```bash
docker compose up -d
docker compose ps    # all 7 containers should show "running"
```

First boot takes 3–5 minutes (pulls images, initialises PostGIS, runs Alembic migrations).

---

## Step 3 — Pull the Local AI Model (One-Time)

```bash
docker compose exec re_os_ollama ollama pull llama3.1:8b
```

This downloads ~5 GB. Required for the light-scraper tier and offline fallback.

---

## Step 4 — Run Your First Scan

```bash
docker compose exec agents python crews/market_intel_crew.py --market Yelahanka
```

Expected runtime: 3–5 minutes. The output is a structured market brief:

```
── YELAHANKA INTELLIGENCE BRIEF  ·  2026-06-13 02:17 IST ──────────────────────

MARKET SNAPSHOT
  Active RERA projects     : 165+
  Grade A competition      : Prestige, Godrej, Sobha
  90-day absorption        : 18.4 units/month
  PSF range (all grades)   : ₹5,200 – ₹9,400

CEO RECOMMENDATION
  Entry at ₹6,200–₹6,800 PSF captures demand below the Grade A
  saturation zone while maintaining headroom to price up as supply clears.
```

Report saved to: `outputs/yelahanka/intel_report_YYYYMMDD_HHMM.txt`

---

## Step 5 — Open the Dashboard

Navigate to `http://localhost:8050` in your browser.

Health check: `curl http://localhost:8050/api/health`

---

## Available Markets

| Market | RERA Projects (live) | Primary Use |
|--------|---------------------|-------------|
| Yelahanka | 165+ | North Bengaluru land entry |
| Devanahalli | 317+ | Airport corridor, industrial |
| Hebbal | 736+ | CBD-adjacent, premium demand |

---

## Daily Operation

The scheduler runs automatically once started. Key jobs:

| Time (IST) | Job |
|------------|-----|
| 2:00 AM | Full RERA refresh — all markets |
| 3:00 AM | Kaveri deed ingestion |
| 5:00 AM | PSF forecast update |
| 6:00 AM | Market snapshot |
| Weekly | Agent memory decay, Alembic check, BERTScore eval |

---

## Next Steps

- **Full setup guide (first-time):** [docs/setup.md](setup.md)
- **Daily operation + troubleshooting:** [docs/operations.md](operations.md)
- **All commands:** `make help` or read the [Makefile](../Makefile)
- **Architecture deep-dive:** [ARCHITECTURE.md](../ARCHITECTURE.md)
- **API reference:** [docs/api-reference.md](api-reference.md)
